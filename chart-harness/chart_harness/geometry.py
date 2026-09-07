"""Deterministic raster localization and calibration, with explicit abstention.

The model interprets marks and associates series; this module alone computes
numbers. All coordinates refer to the original supplied image. Localization
scores are image diagnostics, not probabilities of correctness. Pixel tolerance
intervals are conditional sensitivity calculations, not confidence intervals.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage, optimize, signal


SCHEMA_VERSION = 1
MARKERS = {"ring", "blob", "template", "point"}
# Acceptance is relative to what the figure itself resolves, never an absolute
# pixel count: two pixels is nothing on a 600 dpi page whose ticks stand 200 px
# apart and hopeless on a thumbnail whose ticks stand 8 px apart. The criterion
# is a fraction of the closest printed tick spacing, so it carries over to any
# scan, crop or zoom of the same plot. The fraction is fixed in code, never read
# from a model response.
CALIBRATION_RESIDUAL_FRACTION_OF_TICK_GAP = 0.05


def _canonical_unit(unit):
    """Normalize explicitly recognized typography only; never convert quantities."""
    normalized = unit.strip().replace("µ", "u").replace("μ", "u")
    aliases = {f"{mass}/{volume}": f"{mass}/mL"
               for mass in ("g", "mg", "ug", "ng", "pg")
               for volume in ("mL", "ML", "ml", "Ml")}
    aliases.update({v: "day" for v in ("Day", "Days", "days", "day", "d")})
    aliases.update({v: "h" for v in ("Hours", "hours", "hour", "hr", "hrs", "h")})
    return aliases.get(normalized, normalized)


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _bbox(box, width, height, name="plot_bbox"):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError(f"{name} must contain left, top, right, bottom")
    l, t, r, b = [_number(v, name) for v in box]
    if r <= l or b <= t:
        raise ValueError(f"{name} is empty or inverted")
    clipped = [max(0., l), max(0., t), min(float(width), r), min(float(height), b)]
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise ValueError(f"{name} is outside the image")
    return clipped


class Axis:
    """Affine calibration per explicit segment, in linear or log10 data space."""

    def __init__(self, definition, name):
        if not isinstance(definition, dict):
            raise ValueError(f"{name} must be an axis object")
        self.name = name
        self.scale = definition.get("scale")
        if self.scale not in {"linear", "log"}:
            raise ValueError(f"{name}.scale must be linear or log")
        self.unit = definition.get("unit", "")
        if not isinstance(self.unit, str):
            raise ValueError(f"{name}.unit must be a string")
        self.extrapolate = definition.get("allow_extrapolation", False)
        if not isinstance(self.extrapolate, bool):
            raise ValueError(f"{name}.allow_extrapolation must be boolean")
        self.segments = []
        self.fit_diagnostics = []
        segments = definition.get("segments")
        if segments is not None and (not isinstance(segments, list) or not segments):
            raise ValueError(f"{name}.segments must be a nonempty list")
        for item in segments if segments is not None else [definition]:
            if "scale" in item and item["scale"] != self.scale:
                raise ValueError(f"{name} segment scale differs from axis scale")
            anchors = item.get("anchors")
            if not isinstance(anchors, list) or len(anchors) < 2:
                raise ValueError(f"{name} requires at least two anchors per segment")
            pairs = []
            for a in anchors:
                p = _number(a["pixel"], f"{name} anchor pixel")
                v = _number(a["value"], f"{name} anchor value")
                if self.scale == "log" and v <= 0:
                    raise ValueError(f"{name} log anchor values must be positive")
                pairs.append((p, math.log10(v) if self.scale == "log" else v))
            pairs.sort()
            pixels, values = np.asarray(pairs, dtype=float).T
            if np.any(np.diff(pixels) <= 0):
                raise ValueError(f"{name} anchor pixels must be distinct")
            changes = np.diff(values)
            if not (np.all(changes > 0) or np.all(changes < 0)):
                raise ValueError(f"{name} anchor values must be strictly monotone")
            # Fit all ticks together. Interpolating each adjacent pair would hide
            # an OCR error by silently changing the scale between printed ticks.
            centered = pixels - pixels.mean()
            slope = float(np.dot(centered, values - values.mean()) / np.dot(centered, centered))
            fitted = values.mean() + slope * centered
            if not math.isfinite(slope) or slope == 0 or not np.all(np.isfinite(fitted)):
                raise ValueError(f"{name} calibration fit is not finite or invertible")
            residual_pixels = np.abs(values - fitted) / abs(slope)
            max_residual = float(np.max(residual_pixels))
            gap = float(np.min(np.diff(pixels)))
            limit = gap * CALIBRATION_RESIDUAL_FRACTION_OF_TICK_GAP
            if max_residual > limit + 1e-9:
                raise ValueError(
                    f"{name} tick calibration residual {max_residual:.3g} px is "
                    f"{max_residual / gap:.1%} of the closest tick spacing "
                    f"({gap:.3g} px); the anchors do not sit on one scale")
            lo = _number(item.get("pixel_min", pixels[0]), f"{name}.pixel_min")
            hi = _number(item.get("pixel_max", pixels[-1]), f"{name}.pixel_max")
            if lo >= hi:
                raise ValueError(f"{name} segment has invalid domain")
            if (lo < pixels[0] or hi > pixels[-1]) and not self.extrapolate:
                raise ValueError(f"{name} segment domain exceeds its anchors")
            self.segments.append((lo, hi, pixels, fitted))
            self.fit_diagnostics.append({
                "pixel_min": lo, "pixel_max": hi, "anchor_count": len(pixels),
                "slope_in_calibration_space": slope,
                "max_residual_pixels": max_residual,
                "closest_tick_spacing_pixels": gap,
                "residual_fraction_of_tick_spacing": max_residual / gap,
                "residual_limit_pixels": limit,
            })
        # What this axis can resolve: the closest spacing between printed ticks.
        # Every pixel tolerance on this axis is expressed as a fraction of it.
        self.tick_gap = min(float(np.min(np.diff(ps))) for _, _, ps, _ in self.segments)
        self.segments.sort(key=lambda s: s[0])
        for first, second in zip(self.segments, self.segments[1:]):
            if first[1] >= second[0]:
                raise ValueError(f"{name} piecewise segments overlap or share a boundary")

    def transformed(self, pixel):
        p = _number(pixel, f"{self.name} pixel")
        seg = next((s for s in self.segments if s[0] <= p <= s[1]), None)
        if seg is None and self.extrapolate:
            # An explicit break remains a gap even when outer extrapolation is allowed.
            if p < self.segments[0][0]:
                seg = self.segments[0]
            elif p > self.segments[-1][1]:
                seg = self.segments[-1]
        if seg is None:
            return None
        _, _, pixels, values = seg
        index = min(max(int(np.searchsorted(pixels, p)) - 1, 0), len(pixels) - 2)
        return float(values[index] + (p - pixels[index]) *
                     (values[index + 1] - values[index]) / (pixels[index + 1] - pixels[index]))

    def value(self, pixel):
        value = self.transformed(pixel)
        if value is None:
            return None
        try:
            mapped = 10. ** value if self.scale == "log" else value
        except OverflowError:
            return None
        return float(mapped) if math.isfinite(mapped) and (self.scale != "log" or mapped > 0) else None

    def span(self):
        values = [v for _, _, _, vs in self.segments for v in vs]
        return float(max(values) - min(values))


def _validate_interpretation(interpretation, width, height):
    if not isinstance(interpretation, dict):
        raise ValueError("interpretation must be an object")
    bbox = _bbox(interpretation.get("plot_bbox", [0, 0, width, height]), width, height)
    if interpretation.get("unsupported"):
        return bbox, None, None, []
    axes = [Axis(interpretation.get(name), name) for name in ("x_axis", "y_axis")]
    series = interpretation.get("series", [])
    if not isinstance(series, list):
        raise ValueError("series must be a list")
    seen = set()
    for s in series:
        sid = s.get("id")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("series IDs must be nonempty unique strings")
        seen.add(sid)
        if s.get("marker", "point") not in MARKERS:
            raise ValueError(f"unknown marker type for {sid}")
        if not isinstance(s.get("seeds", []), list):
            raise ValueError(f"{sid}.seeds must be a list")
        if s.get("template_bbox") is not None:
            _bbox(s["template_bbox"], width, height, "template_bbox")
    return bbox, axes[0], axes[1], series


def _load_image(path):
    path = Path(path).resolve()
    with Image.open(path) as source:
        image = source.convert("RGB")
    gray = np.asarray(image.convert("L"), dtype=float) / 255.
    return path, image, gray


def _in_bbox(x, y, bbox):
    return bbox[0] <= x < bbox[2] and bbox[1] <= y < bbox[3]


def _ring_refine(gray, seed, series, bbox):
    x, y = seed["x"], seed["y"]
    radius = _number(seed.get("radius", series.get("radius", 6)), "ring radius")
    if radius <= 0:
        raise ValueError("ring radius must be positive")
    rrange = series.get("radius_range", [max(1.8, radius * .55), radius * 1.6])
    rmin, rmax = [_number(v, "radius_range") for v in rrange]
    if not 0 < rmin < rmax <= 100:
        raise ValueError("radius_range must be positive, increasing, and at most 100")
    reach = _number(series.get("search_radius", max(3., radius)), "search_radius")
    if not 0 < reach <= 100:
        raise ValueError("search_radius must be in (0, 100]")
    angles = np.arange(64) * (2 * np.pi / 64)
    cosine, sine = np.cos(angles), np.sin(angles)

    def samples(params, factor):
        cx, cy, rx, ry = params
        return ndimage.map_coordinates(gray, [cy + factor * ry * sine,
                                               cx + factor * rx * cosine],
                                        order=1, mode="nearest")

    def evidence(params):
        ring = np.minimum.reduce([samples(params, f) for f in (.94, 1., 1.06)])
        inner, outer = samples(params, .5), samples(params, 1.5)
        contrast = (inner + outer) / 2 - ring
        return contrast, inner - ring, outer - ring

    def loss(params):
        contrast, inner, outer = evidence(params)
        ellipticity = abs(math.log(params[2] / params[3]))
        return -(float(np.mean(np.clip(contrast, -.25, .6))) +
                 .35 * float(np.median(contrast))) + .025 * ellipticity

    bounds = [(max(bbox[0], x - reach), min(bbox[2] - 1e-6, x + reach)),
              (max(bbox[1], y - reach), min(bbox[3] - 1e-6, y + reach)),
              (rmin, rmax), (rmin, rmax)]
    fits = []
    starts = [[x,y,r,r] for r in (max(rmin, radius*.8),min(rmax,radius),min(rmax,radius*1.2))]
    if series.get("coarse_ring_search", False):
        # Search across the model's bounded seed window before local fitting.
        # This avoids treating an optimizer's local minimum as precise geometry.
        coarse = [[cx,cy,r,r] for cx in np.linspace(*bounds[0],11)
                  for cy in np.linspace(*bounds[1],11)
                  for r in np.linspace(rmin,rmax,5)]
        ranked=sorted(coarse,key=loss)
        selected=[]
        for point in ranked:
            if all(math.hypot(point[0]-q[0],point[1]-q[1]) > max(3,radius/2) for q in selected):
                selected.append(point)
            if len(selected)==4:break
        starts += selected
    for start_index, initial in enumerate(starts):
        local_bounds=bounds
        if start_index>=3:
            step=max((bounds[0][1]-bounds[0][0])/10,(bounds[1][1]-bounds[1][0])/10)
            local_bounds=[(max(bounds[k][0],initial[k]-step),min(bounds[k][1],initial[k]+step)) for k in (0,1)]+bounds[2:]
        fit = optimize.minimize(loss, initial, method="Powell", bounds=local_bounds,
                                options={"maxiter": 35, "xtol": .025, "ftol": 1e-4})
        if np.all(np.isfinite(fit.x)):
            fits.append(fit)
    if not fits:
        return x, y, "unsupported", {"method": "annular_contrast", "failure": "optimizer_failed"}
    best = min(fits, key=lambda f: f.fun)
    cx, cy, rx, ry = map(float, best.x)
    contrast, inner, outer = evidence(best.x)
    coverage = float(np.mean((contrast > .045) & (inner > .02) & (outer > .02)))
    clipped = cx - 1.5 * rx < bbox[0] or cx + 1.5 * rx >= bbox[2] or cy - 1.5 * ry < bbox[1] or cy + 1.5 * ry >= bbox[3]
    supported = coverage >= .62 and float(np.median(inner)) > .04 and not clipped
    diagnostics = {"method": "annular_contrast_axis_aligned_ellipse", "rx": rx, "ry": ry,
                   "annular_contrast": float(np.median(contrast)), "angular_support_fraction": coverage,
                   "optimizer_success": bool(best.success), "sample_region_clipped": bool(clipped)}
    if not supported:
        diagnostics["failure"] = "insufficient_isolated_ring_support"
        # Do not replace an interpretation seed with a failed local optimum.
        return x, y, "unsupported", diagnostics
    return cx, cy, "supported", diagnostics


def _blob_refine(gray, seed, series, bbox):
    x, y = seed["x"], seed["y"]
    radius = _number(series.get("search_radius", 10), "blob search_radius")
    if not 1 <= radius <= 100:
        raise ValueError("blob search_radius must be in [1, 100]")
    l, t = max(int(bbox[0]), int(x - radius)), max(int(bbox[1]), int(y - radius))
    r, b = min(int(bbox[2]), int(x + radius + 1)), min(int(bbox[3]), int(y + radius + 1))
    patch = gray[t:b, l:r]
    threshold = float(np.quantile(patch, .85)) - .18
    labels, count = ndimage.label(patch < threshold)
    choices = []
    for k in range(1, count + 1):
        ys, xs = np.where(labels == k)
        if len(xs) >= 3:
            distance = np.min((xs + l - x) ** 2 + (ys + t - y) ** 2)
            choices.append((distance, xs, ys))
    if not choices:
        return x, y, "unsupported", {"method": "local_component", "failure": "no_ink_component"}
    _, xs, ys = min(choices, key=lambda c: c[0])
    touches = bool(np.any((xs == 0) | (xs == patch.shape[1] - 1) | (ys == 0) | (ys == patch.shape[0] - 1)))
    w, h = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
    aspect = max(w / h, h / w)
    diagnostics = {"method": "local_component", "component_pixels": int(len(xs)),
                   "component_bbox": [int(xs.min() + l), int(ys.min() + t), int(xs.max() + l + 1), int(ys.max() + t + 1)],
                   "touches_search_boundary": touches, "aspect_ratio": aspect}
    if touches or aspect > 2.5 or len(xs) > .6 * patch.size:
        diagnostics["failure"] = "component_may_include_trace_or_error_bar"
        return x, y, "unsupported", diagnostics
    weights = np.maximum(0., threshold - patch[ys, xs])
    return float(np.average(xs + l, weights=weights)), float(np.average(ys + t, weights=weights)), "supported", diagnostics


def _ncc(gray, template):
    """Valid-window zero-mean normalized cross correlation."""
    h, w = template.shape
    if min(h, w) < 3 or h > gray.shape[0] or w > gray.shape[1]:
        return None
    centered = template - template.mean()
    energy = float(np.sum(centered ** 2))
    if energy < 1e-8:
        return None
    sums = signal.correlate2d(gray, np.ones((h, w)), mode="valid") if h * w < 16 else signal.fftconvolve(gray, np.ones((h, w)), mode="valid")
    squares = signal.fftconvolve(gray * gray, np.ones((h, w)), mode="valid")
    numerator = signal.fftconvolve(gray, centered[::-1, ::-1], mode="valid")
    denominator = np.sqrt(np.maximum(squares - sums * sums / (h * w), 0) * energy)
    result = np.zeros_like(numerator)
    np.divide(numerator, denominator, out=result, where=denominator > 1e-10)
    return np.clip(result, -1., 1.)


def _template_candidates(gray, image, series, bbox, seeds):
    if series.get("template_bbox") is None:
        return [], "template_bbox_missing"
    tb = _bbox(series["template_bbox"], image.width, image.height, "template_bbox")
    template = gray[int(tb[1]):int(math.ceil(tb[3])), int(tb[0]):int(math.ceil(tb[2]))]
    if template.size == 0 or min(template.shape) < 3 or np.std(template) < .025:
        return [], "template_is_empty_small_or_uninformative"
    scales = series.get("template_scales", [1.])
    if not isinstance(scales, list) or not 1 <= len(scales) <= 5:
        raise ValueError("template_scales requires one to five values")
    scales = [_number(s, "template scale") for s in scales]
    if any(s < .5 or s > 2 for s in scales):
        raise ValueError("template scales must lie in [0.5, 2]")
    threshold = _number(series.get("match_threshold", .72), "match_threshold")
    if not -1 <= threshold <= 1:
        raise ValueError("match_threshold must lie in [-1, 1]")
    max_candidates = series.get("max_candidates", 100)
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or not 1 <= max_candidates <= 1000:
        raise ValueError("max_candidates must be an integer in [1, 1000]")
    search_radius = _number(series.get("search_radius", 8), "template search_radius")
    if not 0 < search_radius <= 100:
        raise ValueError("template search_radius must lie in (0, 100]")
    l, t, r, b = [int(v) for v in bbox]
    found = []
    for seed_index, seed in enumerate(seeds if seeds else [None]):
        matches = []
        for scale in scales:
            h, w = [max(3, round(n * scale)) for n in template.shape]
            scaled = np.asarray(Image.fromarray(np.uint8(template * 255)).resize((w, h), Image.Resampling.BILINEAR), dtype=float) / 255.
            if seed is None:
                sl, st, sr, sb = l, t, r, b
            else:
                sl = max(l, int(seed["x"] - search_radius - w / 2))
                st = max(t, int(seed["y"] - search_radius - h / 2))
                sr = min(r, int(math.ceil(seed["x"] + search_radius + w / 2 + 1)))
                sb = min(b, int(math.ceil(seed["y"] + search_radius + h / 2 + 1)))
            corr = _ncc(gray[st:sb, sl:sr], scaled)
            if corr is None:
                continue
            if seed is not None:
                iy, ix = np.unravel_index(int(np.argmax(corr)), corr.shape)
                hits = [(int(iy), int(ix))]
            else:
                maxima = corr == ndimage.maximum_filter(corr, size=max(3, min(h, w) // 2))
                ys, xs = np.where(maxima & (corr >= threshold))
                order = np.argsort(corr[ys, xs])[::-1][:max_candidates * 3]
                hits = [(int(ys[i]), int(xs[i])) for i in order]
            for iy, ix in hits:
                cx, cy = sl + ix + (w - 1) / 2, st + iy + (h - 1) / 2
                if seed is not None and math.hypot(cx - seed["x"], cy - seed["y"]) > search_radius * 1.5:
                    continue
                score = float(corr[iy, ix])
                matches.append({"x": cx, "y": cy, "score": score, "scale": scale,
                                "template_width": w, "template_height": h})
        matches.sort(key=lambda m: -m["score"])
        chosen = []
        for m in matches:
            if any(math.hypot(m["x"] - k["x"], m["y"] - k["y"]) < min(m["template_width"], m["template_height"]) * .45 for k in chosen):
                continue
            chosen.append(m)
            if len(chosen) >= (1 if seed is not None else max_candidates):
                break
        if seed is not None and not chosen:
            chosen = [{"x": seed["x"], "y": seed["y"], "score": -1., "scale": 1.}]
        for m in chosen:
            supported = m["score"] >= threshold
            diagnostics = {"method": "normalized_cross_correlation", "ncc": m["score"], "scale": m["scale"],
                           "threshold": threshold, "seed_index": seed_index if seed is not None else None,
                           "template_bbox": tb, "score_is_probability": False}
            if not supported:
                diagnostics["failure"] = "template_match_below_threshold"
            found.append((m["x"] if supported or seed is None else seed["x"],
                          m["y"] if supported or seed is None else seed["y"],
                          "supported" if supported else "unsupported", diagnostics))
    return found, None


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _reading(row):
    """What this mark was deduced to be, in the figure's own units."""
    if not row or row.get("x") is None or row.get("y") is None:
        return None
    def number(value):
        magnitude = abs(value)
        if magnitude and (magnitude < .01 or magnitude >= 10000):
            return f"{value:.2g}"
        return f"{value:.4g}"
    return f"{number(row['x'])},{number(row['y'])}"


def _overlay(image, candidates, path, rows=None, label=None, stage=None):
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", max(12, min(20, image.width // 90)))
    except OSError:
        font = ImageFont.load_default()
    if label:
        # Overlays from different readers are compared side by side, so each one
        # says whose reading it is, and which pass of that reading.
        title = label.upper() + " ANNOTATION" + (" — " + stage.upper() if stage else "")
        box = draw.textbbox((8, 8), title, font=font)
        draw.rectangle((box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4), fill="#111111")
        draw.text((8, 8), title, fill="#ffffff", font=font)
    row_by_id = {r["candidate_id"]: r for r in rows or []}
    for c in candidates:
        x, y = c["pixel"]["x"], c["pixel"]["y"]
        row = row_by_id.get(c["candidate_id"])
        color = "#13a34a" if row and row["status"] == "observed" else "#e63563"
        radius = 7
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=2)
        reading = _reading(row)
        series = (row or {}).get("series_label") or (row or {}).get("series_id")
        text = " ".join(part for part in (c["candidate_id"], series, reading) if part)
        tx, ty = min(max(0, x + 8), max(0, image.width - 60)), max(0, y - 16)
        rect = draw.textbbox((tx, ty), text, font=font)
        draw.rectangle(rect, fill="white")
        draw.text((tx, ty), text, fill=color, font=font)
    canvas.save(path)


def analyze(image_path, interpretation: dict, outdir) -> dict:
    """Localize visible candidate marks and save the source image plus numbered overlay.

    Seeds carry association hypotheses, never measured data values. Missing seeds
    require an explicit raster template; this module never samples a plotted line.
    """
    path, image, gray = _load_image(image_path)
    bbox, xaxis, yaxis, series = _validate_interpretation(interpretation, image.width, image.height)
    out = Path(outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = out / "original.png"
    image.save(original)
    proposals = {"schema_version": SCHEMA_VERSION, "status": "proposed", "image": {
        "path": str(path), "width": image.width, "height": image.height,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, "plot_bbox": bbox,
        "candidates": [], "diagnostics": [], "original_image_path": str(original),
        "overlay_path": str(out / "proposals_overlay.png"),
        "proposals_path": str(out / "proposals.json")}
    if bbox != interpretation.get("plot_bbox", bbox):
        proposals["diagnostics"].append({"code": "plot_bbox_clamped_to_image"})
    if interpretation.get("unsupported"):
        proposals["status"] = "unsupported"
        proposals["diagnostics"].append({"code": "interpretation_unsupported", "reason": interpretation.get("reason", "unspecified")})
    raw = []
    for s in series:
        marker = s.get("marker", "point")
        seeds = []
        for index, seed in enumerate(s.get("seeds", [])):
            x, y = _number(seed["x"], "seed.x"), _number(seed["y"], "seed.y")
            if not _in_bbox(x, y, bbox):
                proposals["diagnostics"].append({"code": "seed_outside_plot", "series_id": s["id"], "seed_index": index, "pixel": {"x": x, "y": y}})
                continue
            seeds.append({**seed, "x": x, "y": y})
        if marker == "template" or (not seeds and s.get("template_bbox") is not None):
            found, failure = _template_candidates(gray, image, s, bbox, seeds)
            if failure:
                proposals["diagnostics"].append({"code": failure, "series_id": s["id"]})
            for x, y, support, diag in found:
                raw.append({"pixel": {"x": float(x), "y": float(y)}, "possible_series": [s["id"]], "marker": "template", "support": support, "diagnostics": diag})
        elif seeds:
            for seed in seeds:
                if marker == "ring":
                    x, y, support, diag = _ring_refine(gray, seed, s, bbox)
                elif marker == "blob":
                    x, y, support, diag = _blob_refine(gray, seed, s, bbox)
                else:
                    x, y, support = seed["x"], seed["y"], "unrefined"
                    diag = {"method": "raw_seed", "failure": "pixel_center_not_refined", "requires_visual_review": True}
                diag["seed_pixel"] = {"x": seed["x"], "y": seed["y"]}
                raw.append({"pixel": {"x": float(x), "y": float(y)}, "possible_series": [s["id"]], "marker": marker, "support": support, "diagnostics": diag})
        else:
            proposals["diagnostics"].append({"code": "no_observed_seeds_or_template", "series_id": s["id"], "reason": "Continuous traces are not evidence of individual observations."})
    merge_distance = _number(interpretation.get("merge_distance", 2.), "merge_distance")
    if not 0 <= merge_distance <= 20:
        raise ValueError("merge_distance must lie in [0, 20]")
    rank = {"supported": 0, "unrefined": 1, "unsupported": 2}
    merged = []
    for candidate in sorted(raw, key=lambda c: (rank[c["support"]], c["pixel"]["x"], c["pixel"]["y"], c["possible_series"][0])):
        neighbor = next((c for c in merged if math.hypot(c["pixel"]["x"] - candidate["pixel"]["x"], c["pixel"]["y"] - candidate["pixel"]["y"]) <= merge_distance), None)
        if neighbor is None:
            merged.append(candidate)
        else:
            neighbor["possible_series"] = sorted(set(neighbor["possible_series"] + candidate["possible_series"]))
            neighbor["diagnostics"].setdefault("merged_hypotheses", []).append(copy.deepcopy(candidate))
            neighbor["diagnostics"]["coincident_candidates_require_review"] = True
    merged.sort(key=lambda c: (c["pixel"]["x"], c["pixel"]["y"], c["possible_series"]))
    tolerance = _number(interpretation.get("pixel_tolerance", 1.), "pixel_tolerance")
    if not 0 <= tolerance <= 100:
        raise ValueError("pixel_tolerance must lie in [0, 100]")
    for index, candidate in enumerate(merged, 1):
        candidate["candidate_id"] = f"p{index:04d}"
        candidate["pixel_uncertainty"] = {"x": tolerance, "y": tolerance, "kind": "assumed_pixel_tolerance", "confidence_interval": False}
    proposals["candidates"] = merged
    if not merged:
        proposals["status"] = "unsupported"
        proposals["diagnostics"].append({"code": "no_resolvable_observation_candidates"})
    elif any(c["support"] != "supported" or len(c["possible_series"]) > 1 for c in merged) or proposals["diagnostics"]:
        proposals["status"] = "review_required"
    _overlay(image, merged, proposals["overlay_path"], label=interpretation.get("overlay_label"),
             stage="proposals")
    _write_json(proposals["proposals_path"], proposals)
    return proposals


def _axis_agreement(axis, independent, pixels, fraction):
    if independent.scale != axis.scale or _canonical_unit(independent.unit) != _canonical_unit(axis.unit):
        return {"accepted": False, "reason": "axis_scale_or_unit_mismatch", "primary_scale": axis.scale,
                "review_scale": independent.scale, "primary_unit": axis.unit, "review_unit": independent.unit}
    test_pixels = sorted(set(pixels + [float(p) for lo, hi, ps, _ in axis.segments for p in (lo, (lo + hi) / 2, hi, *ps)] +
                             [float(p) for lo, hi, ps, _ in independent.segments for p in (lo, (lo + hi) / 2, hi, *ps)]))
    differences, unsupported = [], []
    tolerance = max(axis.span() * fraction, .01 if axis.scale == "log" else 1e-10)

    def comparison_value(calibration, p):
        value = calibration.transformed(p)
        if value is not None:
            return value, False
        # Independent readers can place the same outer tick a fraction of a
        # pixel apart. Extend only for this comparison, at the two outer ends;
        # internal break boundaries and exported data keep their strict domains.
        first, last = calibration.segments[0], calibration.segments[-1]
        segment = None
        margin = calibration.tick_gap * CALIBRATION_RESIDUAL_FRACTION_OF_TICK_GAP
        if first[0] - margin <= p < first[0]:
            segment = first
        elif last[1] < p <= last[1] + margin:
            segment = last
        if segment is None:
            return None, False
        _, _, ps, vs = segment
        return float(vs[0] + (p - ps[0]) * (vs[-1] - vs[0]) / (ps[-1] - ps[0])), True

    for p in test_pixels:
        (first, extended_first), (second, extended_second) = comparison_value(axis, p), comparison_value(independent, p)
        if first is None or second is None:
            if first != second:
                unsupported.append(p)
        else:
            differences.append({"pixel": p, "primary_value": axis.value(p), "review_value": independent.value(p),
                                "difference_in_calibration_space": abs(first - second),
                                "outer_endpoint_tolerance_used": extended_first or extended_second})
    maximum = max((d["difference_in_calibration_space"] for d in differences), default=math.inf)
    accepted = bool(not unsupported and bool(differences) and maximum <= tolerance)
    return {"accepted": accepted, "reason": "within_tolerance" if accepted else "high_impact_axis_mismatch",
            "primary_unit": axis.unit, "review_unit": independent.unit,
            "canonical_unit": _canonical_unit(axis.unit), "unit_conversion_performed": False,
            "comparison_space": "log10(data)" if axis.scale == "log" else "data", "tolerance": tolerance,
            "outer_endpoint_comparison_tolerance_pixels": axis.tick_gap * CALIBRATION_RESIDUAL_FRACTION_OF_TICK_GAP,
            "closest_tick_spacing_pixels": axis.tick_gap,
            "primary_tick_fit": axis.fit_diagnostics, "review_tick_fit": independent.fit_diagnostics,
            "max_difference": maximum if math.isfinite(maximum) else None,
            "domain_mismatch_pixels": unsupported, "checks": differences}


def _interval(axis, pixel, tolerance):
    # A broken-axis gap cannot be bridged by a sensitivity interval.
    lo, hi = pixel - tolerance, pixel + tolerance
    if any(lo < second[0] and hi > first[1] for first, second in zip(axis.segments, axis.segments[1:])):
        return None, None
    values = [axis.value(lo), axis.value(hi)]
    if any(v is None for v in values):
        return None, None
    return min(values), max(values)


def finalize(image_path, interpretation, proposals, review, outdir) -> dict:
    """Validate independent review and export calibrated pixel-derived values.

    Review decisions may classify candidate IDs but may not supply data values or
    substitute coordinates. Unresolved/rejected rows never enter observed.csv.
    """
    path, image, gray = _load_image(image_path)
    bbox, xaxis, yaxis, series = _validate_interpretation(interpretation, image.width, image.height)
    if not isinstance(proposals, dict) or not isinstance(review, dict):
        raise ValueError("proposals and review must be objects")
    expected = proposals.get("image", {}).get("sha256")
    if expected and expected != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError("proposal image differs from the image supplied for finalization")
    if review.get("status") not in {"accepted", "review_required", "unsupported"}:
        raise ValueError("review.status must be accepted, review_required, or unsupported")
    candidates = proposals.get("candidates", [])
    candidate_by_id = {}
    for candidate in candidates:
        cid = candidate.get("candidate_id")
        if not isinstance(cid, str) or not cid or cid in candidate_by_id:
            raise ValueError("proposal candidate IDs must be unique nonempty strings")
        x = _number(candidate["pixel"]["x"], "candidate.pixel.x")
        y = _number(candidate["pixel"]["y"], "candidate.pixel.y")
        if not _in_bbox(x, y, bbox):
            raise ValueError(f"candidate {cid} lies outside the plot")
        candidate_by_id[cid] = candidate
    decisions = review.get("decisions", [])
    if not isinstance(decisions, list):
        raise ValueError("review.decisions must be a list")
    decision_by_id = {}
    series_by_id = {s["id"]: s for s in series}
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("each review decision must be an object")
        unexpected = set(decision) - {"candidate_id", "series_id", "role", "reason"}
        if unexpected:
            raise ValueError(f"review decisions cannot provide coordinates or values; unknown fields: {sorted(unexpected)}")
        cid = decision.get("candidate_id")
        if cid not in candidate_by_id or cid in decision_by_id:
            raise ValueError(f"unknown or repeated review candidate ID: {cid}")
        role = decision.get("role")
        if role not in {"observed", "reject", "unresolved"}:
            raise ValueError(f"invalid review role for {cid}")
        sid = decision.get("series_id")
        if sid is not None and sid not in series_by_id:
            raise ValueError(f"unknown series ID: {sid}")
        if role == "observed" and sid is None:
            raise ValueError(f"observed candidate {cid} requires a series ID")
        decision_by_id[cid] = decision
    out = Path(outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": SCHEMA_VERSION, "status": review["status"], "rows": [], "diagnostics": [],
              "axis_agreement": {}, "uncertainty_note": "Bounds propagate an assumed pixel tolerance through fixed axis calibrations; they are not confidence intervals and exclude axis, association, and observation-count uncertainty.",
              "csv_path": str(out / "observed.csv"), "all_candidates_csv_path": str(out / "all_candidates.csv"),
              "json_path": str(out / "result.json"), "overlay_path": str(out / "final_overlay.png"),
              "original_image_path": proposals.get("original_image_path", str(path))}
    if xaxis is None or review["status"] == "unsupported" or proposals.get("status") == "unsupported":
        result["status"] = "unsupported"
    else:
        checks = review.get("axis_check", {})
        fraction = _number(interpretation.get("axis_tolerance_fraction", .02), "axis_tolerance_fraction")
        if not 0 < fraction <= .1:
            raise ValueError("axis_tolerance_fraction must lie in (0, 0.1]")
        for name, axis, coordinate in (("x_axis", xaxis, "x"), ("y_axis", yaxis, "y")):
            if not isinstance(checks, dict) or name not in checks:
                result["axis_agreement"][name] = {"accepted": False, "reason": "independent_axis_check_missing"}
            else:
                # A second reader may hand back an axis it cannot state properly.
                # That is a failed check, not a broken run: the reading survives
                # as unconfirmed rather than the whole figure being lost.
                try:
                    independent = Axis(checks[name], f"review.{name}")
                except ValueError as unusable:
                    result["axis_agreement"][name] = {"accepted": False,
                                                      "reason": "independent_axis_check_unusable",
                                                      "detail": str(unusable)}
                    continue
                result["axis_agreement"][name] = _axis_agreement(axis, independent, [c["pixel"][coordinate] for c in candidates], fraction)
        tick_check = interpretation.get("axis_tick_check")
        if isinstance(tick_check, dict) and tick_check.get("agrees"):
            # A measurement of the printed ticks outranks a second reader's
            # estimate of the same ticks, but only when both readers agree on
            # what kind of axis it is.
            for name in ("x_axis", "y_axis"):
                entry = result["axis_agreement"].get(name)
                if (entry and not entry["accepted"]
                        and entry.get("reason") not in {"axis_scale_or_unit_mismatch", "independent_axis_check_missing"}
                        and tick_check.get("axes", {}).get(name, {}).get("agrees")):
                    result["axis_agreement"][name] = {"accepted": True,
                                                      "reason": "anchors_confirmed_by_detected_ticks",
                                                      "independent_review": entry}
        for name in ("x_axis", "y_axis"):
            if not result["axis_agreement"].get(name, {"accepted": True})["accepted"]:
                result["status"] = "review_required"
        if isinstance(tick_check, dict):
            # Undetectable ticks are not evidence against the anchors, so only a
            # measured disagreement withholds export.
            inconclusive = bool(tick_check.get("inconclusive"))
            accepted = bool(tick_check.get("agrees")) or inconclusive
            entry = {"accepted": accepted,
                     "max_offset_px": max((v.get("max_offset_px", 0.) for v in tick_check.get("axes", {}).values()
                                           if v.get("checked")), default=None),
                     "tolerance_px": tick_check.get("tolerance_px")}
            if inconclusive:
                entry["reason"] = "detected_ticks_inconclusive"
            elif not accepted:
                entry["reason"] = "anchors_disagree_with_detected_ticks"
            result["axis_agreement"]["detected_ticks"] = entry
            if not accepted:
                result["status"] = "review_required"
        if review.get("missing_points"):
            result["status"] = "review_required"
            result["diagnostics"].append({"code": "additional_observations_require_new_proposal_pass", "missing_points": review["missing_points"]})
    # Reviewing the surviving candidates cannot establish that discarded seeds,
    # empty series, failed templates, or merged marks were completely recovered.
    # Preserve these structural omissions even if the reviewer says "accepted".
    completeness_diagnostics = copy.deepcopy(proposals.get("diagnostics", []))
    if interpretation.get("unresolved_regions"):
        completeness_diagnostics.append({
            "code": "interpretation_regions_unresolved",
            "unresolved_regions": copy.deepcopy(interpretation["unresolved_regions"]),
        })
    merged_ids = [c["candidate_id"] for c in candidates
                  if c.get("diagnostics", {}).get("coincident_candidates_require_review")
                  or len(c.get("possible_series", [])) > 1]
    if merged_ids:
        completeness_diagnostics.append({
            "code": "coincident_candidate_multiplicity_unresolved",
            "candidate_ids": merged_ids,
        })
    if completeness_diagnostics:
        result["diagnostics"].extend(completeness_diagnostics)
        if result["status"] != "unsupported":
            result["status"] = "review_required"
    axes_ok = bool(result["axis_agreement"]) and all(c["accepted"] for c in result["axis_agreement"].values())
    for candidate in candidates:
        cid = candidate["candidate_id"]
        decision = decision_by_id.get(cid, {"role": "unresolved", "series_id": None, "reason": "No review decision supplied."})
        role, sid = decision["role"], decision.get("series_id")
        x, y = candidate["pixel"]["x"], candidate["pixel"]["y"]
        xv, yv = (xaxis.value(x), yaxis.value(y)) if xaxis else (None, None)
        flags = []
        if cid in merged_ids:
            flags.append("coincident_candidate_multiplicity_unresolved")
        if cid not in decision_by_id:
            flags.append("review_decision_missing")
        if candidate.get("support") != "supported":
            flags.append("raw_pixel_support_" + candidate.get("support", "unknown"))
        if xv is None or yv is None:
            flags.append("outside_calibrated_domain")
        if not axes_ok:
            flags.append("axis_check_requires_review")
        if candidate.get("support") == "unsupported" and role == "observed":
            role = "unresolved"
            flags.append("unsupported_localization_cannot_be_accepted")
        if role == "observed" and (xv is None or yv is None or not axes_ok or result["status"] == "unsupported"):
            role = "unresolved"
        if role == "unresolved" and result["status"] != "unsupported":
            result["status"] = "review_required"
        tolerance = candidate.get("pixel_uncertainty", {"x": 1., "y": 1.})
        tx, ty = _number(tolerance.get("x", 1.), "pixel tolerance x"), _number(tolerance.get("y", 1.), "pixel tolerance y")
        if tx < 0 or ty < 0:
            raise ValueError("pixel tolerances cannot be negative")
        xl, xh = _interval(xaxis, x, tx) if xaxis else (None, None)
        yl, yh = _interval(yaxis, y, ty) if yaxis else (None, None)
        if xl is None or yl is None:
            flags.append("pixel_tolerance_crosses_calibration_boundary")
        row = {"candidate_id": cid, "parent_candidate_id": cid, "series_id": sid,
               "series_label": series_by_id[sid].get("label", sid) if sid in series_by_id else None,
               "pixel_x": x, "pixel_y": y, "x": xv, "y": yv,
               "x_unit": xaxis.unit if xaxis else None, "y_unit": yaxis.unit if yaxis else None,
               "x_low": xl, "x_high": xh, "y_low": yl, "y_high": yh,
               "status": role, "raw_image_support": candidate.get("support", "unknown"),
               "reason": decision.get("reason", ""), "flags": flags,
               "localization_diagnostics": candidate.get("diagnostics", {})}
        result["rows"].append(row)
    fields = ["candidate_id", "parent_candidate_id", "series_id", "series_label", "pixel_x", "pixel_y", "x", "y", "x_unit", "y_unit", "x_low", "x_high", "y_low", "y_high", "status", "raw_image_support", "reason", "flags"]
    for key, rows in (("csv_path", [r for r in result["rows"] if r["status"] == "observed"]), ("all_candidates_csv_path", result["rows"])):
        with Path(result[key]).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({**row, "flags": ";".join(row["flags"])})
    result["counts"] = {role: sum(row["status"] == role for row in result["rows"]) for role in ("observed", "reject", "unresolved")}
    _overlay(image, candidates, result["overlay_path"], result["rows"],
             label=interpretation.get("overlay_label"), stage="reviewed")
    _write_json(result["json_path"], result)
    return result

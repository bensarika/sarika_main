"""Local document search and coordinate-preserving image preparation.

PDF text stays local: manifests contain short snippets, never full page text or
base64 image data. Candidate ranking is deterministic and deliberately simple;
use one-based ``pages`` overrides for scans, unusual captions, or missed figures.
Optional OCR uses local Tesseract on pages without extractable text. PDF support
requires PyMuPDF; Pillow handles raster inputs.

Integer image coordinates denote pixel centers. Crop boxes use half-open pixel
edges, as in Pillow. A resized crop's center affine therefore includes a half-
pixel offset. Both center and edge affines are recorded to avoid ambiguity.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageOps


def _fitz():
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF rendering requires PyMuPDF: install pymupdf") from exc
    return fitz


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _save_png(image: Image.Image, output: Path) -> None:
    """Expose a complete PNG only after its encoder and file handle finish."""
    descriptor, name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            image.save(handle, format="PNG")
            handle.flush()
            if handle.tell() <= 8:
                raise OSError("PNG encoder produced an empty image")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def _check_output(source: Path, output: Path) -> None:
    if source.resolve() == output.resolve():
        raise ValueError("Output must differ from the source file")
    output.parent.mkdir(parents=True, exist_ok=True)


def _rgb(image: Image.Image) -> Image.Image:
    """Flatten alpha onto white, without changing orientation or pixel geometry."""
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return image.convert("RGB")


def _native_page_image(document: Any, page: Any) -> tuple[Image.Image | None, str]:
    """Extract only a conservative, undistorted single-image page.

    Any condition whose visual effect cannot be established here falls back to
    the PDF renderer, including masks, color decoding, page rotation, overlays,
    clipped/offset images, and image aspect ratios distorted by the PDF matrix.
    """
    if page.rotation != 0:
        return None, "page_rotation"
    images = page.get_image_info(xrefs=True)
    if len(images) != 1:
        return None, "not_one_displayed_image"
    info = images[0]
    if not info.get("xref"):
        return None, "inline_or_unresolved_image"
    if page.get_text("text").strip() or page.get_drawings(extended=True):
        return None, "text_or_vector_overlay"
    if page.first_annot is not None or page.first_widget is not None:
        return None, "annotation_or_widget"
    # Bounds alone do not reveal clipping, opacity, optional-content state, or
    # nested forms. Accept only direct image paint and matrix/save/restore ops.
    if page.get_xobjects():
        return None, "nested_form_xobject"
    contents = re.sub(rb"%[^\r\n]*", b"", page.read_contents())
    simple_image_stream = rb"(?:\s+|q\b|Q\b|cm\b|Do\b|[+-]?(?:\d+(?:\.\d*)?|\.\d+)|/[^\s()<>\[\]{}/%]+)*"
    if re.fullmatch(simple_image_stream, contents) is None:
        return None, "additional_pdf_graphics_state"
    a, b, c, d, e, f = info["transform"]
    if a <= 0 or d <= 0 or abs(b) > 1e-6 or abs(c) > 1e-6:
        return None, "rotated_flipped_or_sheared_image"
    rect = page.rect
    expected = (rect.x0, rect.y0, rect.x1, rect.y1)
    if any(abs(actual - target) > 0.01 for actual, target in zip(info["bbox"], expected)):
        return None, "image_does_not_cover_page"
    # A cropped page may show only part of an image despite ambiguous image info.
    if any(abs(actual - target) > 0.01 for actual, target in zip((e, f, e + a, f + d), expected)):
        return None, "image_transform_does_not_match_page"
    sx, sy = a / info["width"], d / info["height"]
    if not math.isclose(sx, sy, rel_tol=1e-5, abs_tol=1e-8):
        return None, "nonuniform_image_scale"
    xref = info["xref"]
    for key in ("SMask", "Mask", "Decode", "SMaskInData", "OC"):
        kind, value = document.xref_get_key(xref, key)
        if kind != "null" and value not in ("null", "0", "0 0 R"):
            return None, "image_mask_or_decode"
    kind, value = document.xref_get_key(xref, "ColorSpace")
    if value not in ("/DeviceRGB", "/DeviceGray"):
        return None, "image_color_space"
    if document.xref_get_key(xref, "BitsPerComponent")[1] not in ("1", "2", "4", "8"):
        return None, "image_bit_depth"
    extracted = document.extract_image(xref)
    if not extracted or extracted.get("smask", 0):
        return None, "image_extraction_unavailable"
    with Image.open(io.BytesIO(extracted["image"])) as opened:
        if opened.size != (info["width"], info["height"]):
            return None, "extracted_pixel_dimensions_mismatch"
        return _rgb(opened), "verified_full_page_image"


def _render_open_page(
    document: Any, page1: int, output: Path, source: Path, source_hash: str, dpi: int
) -> dict[str, Any]:
    page = document[page1 - 1]
    native, reason = _native_page_image(document, page)
    if native is not None:
        raster = native
        method = "native_image"
    else:
        fitz = _fitz()
        # Some scans use pixel dimensions as PDF points. Bound fallback rendering
        # before allocation, even when annotations make native extraction unsafe.
        zoom = min(dpi / 72., 4096. / max(page.rect.width, page.rect.height))
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False, annots=True)
        raster = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        method = "pdf_render"
    _save_png(raster, output)
    width, height = raster.size
    rect = page.rect
    # Page coordinates here refer to the visible, rotated page rectangle; they
    # are not unrotated PDF object coordinates. Pixel coordinates remain exact.
    sx, sy = (rect.width / width, rect.height / height) if method == "native_image" else (1 / zoom, 1 / zoom)
    metadata = {
        "image_path": str(output),
        "source_path": str(source),
        "source_sha256": source_hash,
        "page_number": page1,
        "method": method,
        "native_extraction_reason": reason,
        "pixel_size": [width, height],
        "image_sha256": sha256_file(output),
        "requested_render_dpi": dpi,
        "fallback_max_side": 4096,
        "page_rotation_degrees": page.rotation,
        "page_rect_points": list(rect),
        "pixel_centers_to_visible_page_points": [
            [sx, 0.0, rect.x0 + sx / 2],
            [0.0, sy, rect.y0 + sy / 2],
            [0.0, 0.0, 1.0],
        ],
        "coordinate_convention": "integer x/y are pixel centers; top-left center is (0, 0)",
    }
    _write_json(Path(str(output) + ".json"), metadata)
    return metadata


def render_page(
    pdf: str | Path, page1: int, out: str | Path, dpi: int = 144
) -> Path:
    """Write a one-based PDF page as PNG and its provenance as ``<out>.json``.

    Verified full-page embedded images retain their native pixels; other pages
    render in RGB at ``dpi``. Consult the sidecar before interpreting resolution.
    A PDF rendering, including annotations, is the canonical source raster when
    native extraction is unsafe. The original PDF file is never modified.
    """
    source, output = Path(pdf).resolve(), Path(out).resolve()
    if isinstance(page1, bool) or not isinstance(page1, int) or page1 < 1:
        raise ValueError("page1 must be a positive one-based integer")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("dpi must be a positive integer")
    _check_output(source, output)
    _check_output(source, Path(str(output) + ".json"))
    with _fitz().open(source) as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if page1 > len(document):
            raise ValueError(f"Page {page1} is outside this {len(document)}-page PDF")
        _render_open_page(document, page1, output, source, sha256_file(source), dpi)
    return output


def crop_image(
    image: str | Path,
    box: Sequence[float],
    out: str | Path,
    max_side: int | None = None,
) -> dict[str, Any]:
    """Crop an original raster, optionally downsize, and preserve its coordinates.

    ``box`` is (left, top, right, bottom), with right/bottom excluded. Fractional
    requests round outward to contain the requested region. Out-of-bounds boxes
    raise, rather than silently padding or altering the requested coordinate frame.
    The return value is also saved as ``<out>.json``. No EXIF rotation is applied.
    """
    source, output = Path(image).resolve(), Path(out).resolve()
    if len(box) != 4 or any(not math.isfinite(float(value)) for value in box):
        raise ValueError("box must contain four finite coordinates")
    requested = [float(value) for value in box]
    if requested[2] <= requested[0] or requested[3] <= requested[1]:
        raise ValueError("box must have positive width and height")
    if max_side is not None and (
        isinstance(max_side, bool) or not isinstance(max_side, int) or max_side <= 0
    ):
        raise ValueError("max_side must be a positive integer")
    _check_output(source, output)
    _check_output(source, Path(str(output) + ".json"))
    with Image.open(source) as opened:
        width, height = opened.size
        if requested[0] < 0 or requested[1] < 0 or requested[2] > width or requested[3] > height:
            raise ValueError(f"box is outside the source image ({width} x {height})")
        left, top = math.floor(requested[0]), math.floor(requested[1])
        right, bottom = math.ceil(requested[2]), math.ceil(requested[3])
        cropped = _rgb(opened.crop((left, top, right, bottom)))
    crop_width, crop_height = cropped.size
    if max_side is not None and max(cropped.size) > max_side:
        ratio = max_side / max(cropped.size)
        target = (max(1, round(crop_width * ratio)), max(1, round(crop_height * ratio)))
        cropped = cropped.resize(target, Image.Resampling.LANCZOS)
    _save_png(cropped, output)
    output_width, output_height = cropped.size
    sx, sy = crop_width / output_width, crop_height / output_height
    metadata = {
        "image_path": str(output),
        "source_path": str(source),
        "source_sha256": sha256_file(source),
        "source_size": [width, height],
        "requested_box": requested,
        "crop_box": [left, top, right, bottom],
        "output_size": [output_width, output_height],
        "image_sha256": sha256_file(output),
        "output_to_source": [
            [sx, 0.0, left + (sx - 1.0) / 2],
            [0.0, sy, top + (sy - 1.0) / 2],
            [0.0, 0.0, 1.0],
        ],
        "output_edges_to_source_edges": [
            [sx, 0.0, left], [0.0, sy, top], [0.0, 0.0, 1.0]
        ],
        "coordinate_convention": "integer x/y are pixel centers; crop_box is half-open pixel edges",
        "resampling": "lanczos" if cropped.size != (crop_width, crop_height) else "none",
    }
    _write_json(Path(str(output) + ".json"), metadata)
    return metadata


def rotate_image(image: str | Path, clockwise: int, out: str | Path) -> dict[str, Any]:
    """Apply a lossless quarter-turn and retain a mapping to original pixels.

    Only 0, 90, 180, or 270 clockwise degrees are accepted. The affine maps pixel
    centers in the returned image back to the supplied source raster, so it can
    be composed with a subsequent crop's ``output_to_source`` matrix.
    """
    if isinstance(clockwise, bool) or clockwise not in (0, 90, 180, 270):
        raise ValueError("clockwise must be 0, 90, 180, or 270")
    source, output = Path(image).resolve(), Path(out).resolve()
    _check_output(source, output)
    _check_output(source, Path(str(output) + ".json"))
    with Image.open(source) as opened:
        raster = _rgb(opened)
    width, height = raster.size
    operations = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}
    matrices = {
        0: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        90: [[0, 1, 0], [-1, 0, height - 1], [0, 0, 1]],
        180: [[-1, 0, width - 1], [0, -1, height - 1], [0, 0, 1]],
        270: [[0, -1, width - 1], [1, 0, 0], [0, 0, 1]],
    }
    if clockwise:
        raster = raster.transpose(operations[clockwise])
    _save_png(raster, output)
    metadata = {
        "image_path": str(output),
        "source_path": str(source),
        "source_sha256": sha256_file(source),
        "source_size": [width, height],
        "output_size": list(raster.size),
        "clockwise_degrees": clockwise,
        "output_to_source": matrices[clockwise],
        "image_sha256": sha256_file(output),
        "coordinate_convention": "integer x/y are pixel centers; top-left center is (0, 0)",
        "resampling": "none",
    }
    _write_json(Path(str(output) + ".json"), metadata)
    return metadata


def _ocr_image(image: Path, cache_dir: Path, psm: int = 1) -> tuple[str, str]:
    """Run Tesseract locally; the cache is keyed by the exact OCR raster hash."""
    cache_path = cache_dir / f"tesseract-psm{psm}-{sha256_file(image)}.json"
    text, status = None, "cache_hit"
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and isinstance(cached.get("text"), str):
                text = cached["text"]
        except (OSError, ValueError):
            pass
    if text is None:
        try:
            result = subprocess.run(
                ["tesseract", str(image), "stdout", "-l", "eng", "--psm", str(psm)],
                capture_output=True, text=True, check=True, timeout=45,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )
        except (OSError, subprocess.SubprocessError):
            return "", "failed"
        text, status = result.stdout, "complete"
        # Full OCR output stays in local cache files, never the public manifest.
        _write_json(cache_path, {"text": text, "engine": "tesseract", "psm": psm})
    if psm == 1 and len(text.split()) < 180:
        # Automatic layout can omit isolated Fig. labels. Sparse mode complements
        # it on drawing pages; the automatic pass still handles page orientation.
        sparse, sparse_status = _ocr_image(image, cache_dir, psm=11)
        if sparse:
            text += "\n\n" + sparse
        if sparse_status != "cache_hit":
            status = "complete" if sparse_status == "complete" else status
    return text, status


def _tokens(value: str) -> list[str]:
    value = re.sub(r"\bfig(?:ure)?s?\.?", "figure ", value.lower())
    return re.findall(r"[a-z0-9]+", value)


def _normalize_figure_numerals(text: str) -> str:
    """Handle isolated OCR I/l/O only immediately after a figure label.

    Keep snippets unchanged so the original recognition remains auditable. This
    narrow repair does not reinterpret numbers in axes, values, or normal prose.
    """
    return re.sub(
        r"(\bfig(?:ure)?\.?\s*)([IiLlOo])(?=\s|[.,:;]|$)",
        lambda match: match.group(1) + ("0" if match.group(2) in "Oo" else "1"),
        text, flags=re.I,
    )


def _score_text(text: str, query: str, image_count: int, drawing_count: int) -> tuple[float, int]:
    text = _normalize_figure_numerals(text)
    tokens = _tokens(text)
    wanted = set(_tokens(query)) - {"the", "of", "a", "an", "and", "in", "on", "for"}
    token_set = set(tokens)
    matched = len(wanted & token_set)
    score = 6.0 * matched
    if wanted and wanted <= token_set:
        score += 12.0
    figures = re.findall(r"\bfig(?:ure)?\.?\s*(\d+[a-z]?)\b", query, flags=re.I)
    for figure in figures:
        caption = rf"(?:fig(?:ure)?\.?\s*{re.escape(figure)})\b"
        if re.search(caption, text, flags=re.I):
            score += 25.0
        if re.search(rf"^\s*{caption}[.\s]*$", text, flags=re.I | re.M):
            score += 25.0
    # Low-text visual pages are useful when captions are image-only. Blank pages
    # receive no bonus. This is only a tie-breaking heuristic, not figure OCR.
    if image_count or drawing_count:
        score += max(0.0, 4.0 - len(tokens) / 75)
    return round(score, 4), matched


def _snippet(text: str, query: str, limit: int = 360) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    targets = sorted(set(_tokens(query)), key=lambda term: (-len(term), term))
    offsets = [match.start() for term in targets if (match := re.search(rf"\b{re.escape(term)}\b", compact, re.I))]
    figures = re.findall(r"\bfig(?:ure)?\.?\s*(\d+[a-z]?)\b", query, flags=re.I)
    caption_offsets = [
        match.start() for number in figures
        if (match := re.search(rf"\bfig(?:ure)?\.?\s*{re.escape(number)}\b", _normalize_figure_numerals(compact), re.I))
    ]
    if caption_offsets:
        offsets = caption_offsets
    start = max(0, min(offsets) - 90) if offsets else 0
    start = min(start, len(compact) - limit)
    return ("…" if start else "") + compact[start : start + limit] + ("…" if start + limit < len(compact) else "")


def _contact_sheet(candidates: list[dict[str, Any]], output: Path) -> None:
    columns = min(3, len(candidates))
    cell_width, cell_height = 320, 270
    rows = math.ceil(len(candidates) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate(candidates):
        x, y = (index % columns) * cell_width, (index // columns) * cell_height
        with Image.open(item["thumbnail_path"]) as opened:
            thumb = ImageOps.contain(_rgb(opened), (cell_width - 16, cell_height - 40))
            sheet.paste(thumb, (x + (cell_width - thumb.width) // 2, y + 8))
        label = f"Page {item['page_number']} | score {item['score']:g}"
        draw.text((x + 8, y + cell_height - 25), label, fill="#111111")
    _save_png(sheet, output)


def _explicit_pages(pages: Iterable[int] | None, total: int, cap: int) -> list[int] | None:
    if pages is None:
        return None
    selected = list(dict.fromkeys(pages))
    if not selected:
        raise ValueError("pages must contain at least one one-based page number")
    if any(isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= total for number in selected):
        raise ValueError(f"Explicit pages must be integers from 1 to {total}")
    if len(selected) > cap:
        raise ValueError("Explicit page count exceeds max_candidates; increase the cap")
    return selected


def inspect_document(
    path: str | Path,
    outdir: str | Path,
    query: str = "",
    max_candidates: int = 12,
    pages: Iterable[int] | None = None,
    ocr: bool = False,
) -> dict[str, Any]:
    """Search a PDF locally and write candidate PNGs, thumbnails, and a manifest.

    ``pages`` explicitly selects one-based pages in the supplied order. Otherwise
    candidates sort by text/figure-caption score and then page number. Full text
    is discarded after scoring; only candidate snippets (at most 362 characters)
    are returned. Set ``ocr=True`` to search image-only PDF pages with local
    Tesseract (English, orientation detection plus sparse-page caption recovery,
    at most 110 dpi / 1600 pixels per
    side and four workers). The pixel cap also handles PDFs with huge MediaBoxes.
    OCR results are cached by raster hash in ``outdir/ocr-cache``. Recognition
    can miss sparse or rotated captions; explicit pages always remain available.
    Raster inputs yield one candidate and preserve their raw pixel orientation.
    ``max_candidates`` bounds preview generation and manifest text volume.
    """
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or max_candidates < 1:
        raise ValueError("max_candidates must be a positive integer")
    source, destination = Path(path).resolve(), Path(outdir).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.mkdir(parents=True, exist_ok=True)
    for reserved in (destination / "contact-sheet.png", destination / "manifest.json"):
        _check_output(source, reserved)
    source_hash = sha256_file(source)
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    # File signature also supports extensionless PDFs and mislabeled downloads.
    with source.open("rb") as handle:
        is_pdf = b"%PDF-" in handle.read(1024)
    if is_pdf:
        with _fitz().open(source) as document:
            if document.needs_pass:
                raise ValueError("Password-protected PDFs are not supported")
            total = len(document)
            if not total:
                raise ValueError("Document contains no pages")
            selected = _explicit_pages(pages, total, max_candidates)
            ranked = []
            text_pages = 0
            ocr_available = bool(ocr and shutil.which("tesseract"))
            cache_dir = destination / "ocr-cache"
            if ocr_available:
                cache_dir.mkdir(exist_ok=True)
            elif ocr:
                warnings.append("OCR was requested but Tesseract is unavailable; install tesseract-ocr or use explicit pages.")
            with tempfile.TemporaryDirectory(prefix="chart-ocr-") as temporary, ThreadPoolExecutor(max_workers=4) as executor:
                pending = []
                for index, page in enumerate(document):
                    text = page.get_text("text")
                    text_pages += bool(text.strip())
                    images, drawings = len(page.get_images()), len(page.get_drawings())
                    item = {
                        "page_number": index + 1,
                        "embedded_image_count": images,
                        "vector_drawing_count": drawings,
                        "text_source": "pdf_text" if text.strip() else "none",
                    }
                    future = None
                    if not text.strip() and ocr_available and (selected is None or index + 1 in selected):
                        raster_path = Path(temporary) / f"page-{index + 1}.png"
                        fitz = _fitz()
                        scale = min(110 / 72, 1600 / max(page.rect.width, page.rect.height))
                        page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False).save(raster_path)
                        future = executor.submit(_ocr_image, raster_path, cache_dir)
                    pending.append((item, text, future))
                failures = 0
                for item, text, future in pending:
                    if future is not None:
                        text, status = future.result()
                        item["ocr_status"] = status
                        item["text_source"] = "tesseract" if text.strip() else "none"
                        failures += status == "failed"
                    score, matched = _score_text(text, query, item["embedded_image_count"], item["vector_drawing_count"])
                    item.update({
                        "score": score,
                        "matched_query_tokens": matched,
                        "text_snippet": _snippet(text, query),
                        "text_character_count": len(text),
                    })
                    ranked.append(item)
                if failures:
                    warnings.append(f"Local OCR failed or timed out on {failures} pages; these pages remain available through explicit selection.")
            if selected is None:
                ranked.sort(key=lambda row: (-row["score"], row["page_number"]))
                candidates = ranked[:max_candidates]
            else:
                lookup = {item["page_number"]: item for item in ranked}
                candidates = [lookup[number] for number in selected]
            if text_pages < total:
                suffix = "Local OCR was attempted for selected image-only pages." if ocr_available else "Image-only labels are not searched unless ocr=True."
                warnings.append(f"{total - text_pages} of {total} pages contain no extracted text. {suffix}")
            if query and not any(item["matched_query_tokens"] for item in ranked):
                warnings.append("No query tokens were found in extracted text. Review the contact sheet or select explicit one-based pages.")
            for item in candidates:
                output = destination / f"page-{item['page_number']:04d}.png"
                _check_output(source, output)
                _check_output(source, Path(str(output) + ".json"))
                item.update(_render_open_page(document, item["page_number"], output, source, source_hash, 144))
        kind = "pdf"
    else:
        total = 1
        _explicit_pages(pages, total, max_candidates)
        output = destination / "page-0001.png"
        _check_output(source, output)
        _check_output(source, Path(str(output) + ".json"))
        with Image.open(source) as opened:
            image = _rgb(opened)
            frame_count = getattr(opened, "n_frames", 1)
            if frame_count > 1:
                warnings.append(f"Raster contains {frame_count} frames; only the first frame is inspected.")
            if opened.getexif().get(274, 1) != 1:
                warnings.append("EXIF orientation was not applied; coordinates refer to the original stored pixels.")
        _save_png(image, output)
        candidates = [{
            "page_number": 1,
            "score": 0.0,
            "matched_query_tokens": 0,
            "text_snippet": "",
            "image_path": str(output),
            "source_path": str(source),
            "source_sha256": source_hash,
            "pixel_size": list(image.size),
            "image_sha256": sha256_file(output),
            "method": "raster_pixels",
            "coordinate_convention": "integer x/y are pixel centers; top-left center is (0, 0)",
        }]
        _write_json(Path(str(output) + ".json"), candidates[0])
        kind = "image"
        if query:
            warnings.append("Text search is unavailable for raster inputs without OCR.")
    for item in candidates:
        thumbnail_path = destination / f"thumbnail-{item['page_number']:04d}.png"
        _check_output(source, thumbnail_path)
        with Image.open(item["image_path"]) as opened:
            thumb = _rgb(opened)
            thumb.thumbnail((480, 480), Image.Resampling.LANCZOS)
            _save_png(thumb, thumbnail_path)
        item["thumbnail_path"] = str(thumbnail_path)
    contact = destination / "contact-sheet.png"
    _contact_sheet(candidates, contact)
    manifest_path = destination / "manifest.json"
    manifest = {
        "schema_version": 1,
        "source_path": str(source),
        "source_sha256": source_hash,
        "document_kind": kind,
        "page_count": total,
        "query": query,
        "selection": "explicit_pages" if pages is not None else "ranked",
        "ranking": "local token/caption matches with a sparse visual-page bonus",
        "figure_label_normalization": "isolated OCR I/l becomes 1 and O becomes 0 after Fig./Figure; snippets retain original OCR",
        "ocr_requested": bool(ocr),
        "candidates": candidates,
        "contact_sheet_path": str(contact),
        "manifest_path": str(manifest_path),
        "warnings": warnings,
    }
    _write_json(manifest_path, manifest)
    return manifest

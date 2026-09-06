"""Small synthetic checks of calibration, abstention, and visible-mark support."""
import copy
import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from chart_harness.geometry import Axis, _axis_agreement, analyze, finalize


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / "chart.png"
        Image.new("RGB", (200, 160), "white").save(self.image)
        self.interpretation = {
            "plot_bbox": [10, 10, 190, 150],
            "x_axis": {"scale": "linear", "unit": "h", "anchors": [{"pixel": 10, "value": 0}, {"pixel": 190, "value": 18}]},
            "y_axis": {"scale": "log", "unit": "ng/mL", "anchors": [{"pixel": 10, "value": 1000}, {"pixel": 150, "value": 1}]},
            "series": [{"id": "drug", "label": "Drug", "marker": "point", "seeds": [{"x": 100, "y": 80}]}],
        }

    def tearDown(self):
        self.temp.cleanup()

    def review(self, proposals):
        return {"status": "accepted", "axis_check": {name: copy.deepcopy(self.interpretation[name]) for name in ("x_axis", "y_axis")},
                "decisions": [{"candidate_id": c["candidate_id"], "series_id": "drug", "role": "observed", "reason": "Visible isolated mark."} for c in proposals["candidates"]]}

    def test_linear_log_and_pixel_tolerance(self):
        p = analyze(self.image, self.interpretation, self.root / "proposal")
        self.assertEqual(p["status"], "review_required")
        self.assertEqual(p["candidates"][0]["support"], "unrefined")
        final = finalize(self.image, self.interpretation, p, self.review(p), self.root / "final")
        self.assertEqual(final["status"], "accepted")
        row = final["rows"][0]
        self.assertAlmostEqual(row["x"], 9.)
        self.assertAlmostEqual(row["y"], 1000 ** .5)
        self.assertLess(row["y_low"], row["y"])
        self.assertGreater(row["y_high"], row["y"])
        self.assertIn("raw_pixel_support_unrefined", row["flags"])
        with open(final["csv_path"], newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 1)
        self.assertTrue(Path(final["overlay_path"]).is_file())

    def test_axis_shift_and_units_prevent_acceptance(self):
        p = analyze(self.image, self.interpretation, self.root / "proposal")
        for change in ("value", "unit", "scale"):
            with self.subTest(change=change):
                review = self.review(p)
                if change == "value":
                    review["axis_check"]["x_axis"]["anchors"][1]["value"] = 36
                elif change == "unit":
                    review["axis_check"]["y_axis"]["unit"] = "mg/mL"
                else:
                    review["axis_check"]["y_axis"]["scale"] = "linear"
                result = finalize(self.image, self.interpretation, p, review, self.root / change)
                self.assertEqual(result["status"], "review_required")
                self.assertEqual(result["counts"]["observed"], 0)

    def test_no_observation_is_invented_from_trace(self):
        image = Image.open(self.image)
        ImageDraw.Draw(image).line([(20, 30), (100, 110), (180, 135)], fill="black", width=2)
        image.save(self.image)
        self.interpretation["series"][0]["seeds"] = []
        p = analyze(self.image, self.interpretation, self.root / "proposal")
        self.assertEqual(p["status"], "unsupported")
        self.assertEqual(p["candidates"], [])

    def test_explicit_unit_typography_aliases_do_not_convert_values(self):
        self.interpretation["y_axis"]["unit"] = "µg/mL"
        p = analyze(self.image, self.interpretation, self.root / "proposal")
        for unit in ("ug/mL", "μg/ML", "µg/ml"):
            with self.subTest(unit=unit):
                review = self.review(p)
                review["axis_check"]["y_axis"]["unit"] = unit
                result = finalize(self.image, self.interpretation, p, review, self.root / "alias")
                self.assertEqual(result["status"], "accepted")
                self.assertEqual(result["rows"][0]["y_unit"], "µg/mL")
                self.assertAlmostEqual(result["rows"][0]["y"], 1000 ** .5)
                self.assertFalse(result["axis_agreement"]["y_axis"]["unit_conversion_performed"])
        review["axis_check"]["y_axis"]["unit"] = "ng/mL"
        result = finalize(self.image, self.interpretation, p, review, self.root / "different_mass")
        self.assertEqual(result["status"], "review_required")

    def test_missing_review_and_missing_points_require_review(self):
        p = analyze(self.image, self.interpretation, self.root / "proposal")
        review = self.review(p)
        review["decisions"] = []
        result = finalize(self.image, self.interpretation, p, review, self.root / "missing")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["counts"]["observed"], 0)
        review = self.review(p)
        review["missing_points"] = [{"series_id": "drug", "pixel": {"x": 50, "y": 50}}]
        result = finalize(self.image, self.interpretation, p, review, self.root / "new")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(len(result["rows"]), 1)

    def test_reject_duplicate_unknown_and_model_values(self):
        p = analyze(self.image, self.interpretation, self.root / "proposal")
        for kind in ("duplicate", "unknown", "value", "unknown_series"):
            with self.subTest(kind=kind):
                review = self.review(p)
                if kind == "duplicate":
                    review["decisions"] *= 2
                elif kind == "unknown":
                    review["decisions"][0]["candidate_id"] = "p9999"
                elif kind == "value":
                    review["decisions"][0]["y"] = 42
                else:
                    review["decisions"][0]["series_id"] = "other"
                with self.assertRaises(ValueError):
                    finalize(self.image, self.interpretation, p, review, self.root / kind)

    def test_merge_retains_possible_series(self):
        self.interpretation["series"].append({"id": "other", "marker": "point", "seeds": [{"x": 101, "y": 80}]})
        p = analyze(self.image, self.interpretation, self.root / "proposal")
        self.assertEqual(len(p["candidates"]), 1)
        self.assertEqual(p["candidates"][0]["possible_series"], ["drug", "other"])
        self.assertEqual(p["status"], "review_required")
        again = analyze(self.image, self.interpretation, self.root / "again")
        self.assertEqual(p["candidates"], again["candidates"])

    def test_bbox_clamp_and_outside_seed(self):
        self.interpretation["plot_bbox"] = [-20, -5, 220, 160]
        self.interpretation["series"][0]["seeds"].append({"x": -1, "y": 30})
        p = analyze(self.image, self.interpretation, self.root / "proposal")
        self.assertEqual(p["plot_bbox"], [0., 0., 200., 160.])
        self.assertEqual(len(p["candidates"]), 1)
        self.interpretation["plot_bbox"] = [40, 40, 20, 10]
        with self.assertRaises(ValueError):
            analyze(self.image, self.interpretation, self.root / "bad")

    def test_dropped_seed_or_empty_series_cannot_be_forgotten_at_finalization(self):
        for omission in ("outside_seed", "empty_series"):
            with self.subTest(omission=omission):
                interpretation = copy.deepcopy(self.interpretation)
                if omission == "outside_seed":
                    interpretation["series"][0]["seeds"].append({"x": 5, "y": 80})
                    expected = "seed_outside_plot"
                else:
                    interpretation["series"].append({"id": "other", "marker": "point", "seeds": []})
                    expected = "no_observed_seeds_or_template"
                proposals = analyze(self.image, interpretation, self.root / omission)
                # A reviewer accepts every surviving point but misses the lost item.
                result = finalize(self.image, interpretation, proposals, self.review(proposals), self.root / (omission + "_final"))
                self.assertEqual(result["status"], "review_required")
                self.assertEqual(result["counts"]["observed"], 1)
                self.assertIn(expected, [d["code"] for d in result["diagnostics"]])

    def test_coincident_same_or_different_series_cannot_imply_complete_recovery(self):
        for same_series in (True, False):
            with self.subTest(same_series=same_series):
                interpretation = copy.deepcopy(self.interpretation)
                if same_series:
                    interpretation["series"][0]["seeds"].append({"x": 101, "y": 80})
                else:
                    interpretation["series"].append({"id": "other", "marker": "point", "seeds": [{"x": 101, "y": 80}]})
                proposals = analyze(self.image, interpretation, self.root / "merged")
                result = finalize(self.image, interpretation, proposals, self.review(proposals), self.root / "merged_final")
                self.assertEqual(len(result["rows"]), 1)
                self.assertEqual(result["status"], "review_required")
                self.assertIn("coincident_candidate_multiplicity_unresolved", result["rows"][0]["flags"])

    def test_unresolved_region_prevents_whole_chart_acceptance(self):
        self.interpretation["unresolved_regions"] = [{"reason": "Early observations overlap."}]
        proposals = analyze(self.image, self.interpretation, self.root / "proposal")
        result = finalize(self.image, self.interpretation, proposals, self.review(proposals), self.root / "final")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["counts"]["observed"], 1)

    def test_ring_refinement_and_blank_abstention(self):
        image = Image.open(self.image)
        draw = ImageDraw.Draw(image)
        draw.ellipse((93, 73, 107, 87), outline="black", width=2)
        image.save(self.image)
        self.interpretation["series"][0].update(marker="ring", radius=6.5, seeds=[{"x": 102, "y": 78}])
        p = analyze(self.image, self.interpretation, self.root / "ring")
        candidate = p["candidates"][0]
        self.assertEqual(candidate["support"], "supported", candidate)
        self.assertLess(abs(candidate["pixel"]["x"] - 100), 1.)
        self.assertLess(abs(candidate["pixel"]["y"] - 80), 1.)
        Image.new("RGB", (200, 160), "white").save(self.image)
        p = analyze(self.image, self.interpretation, self.root / "blank")
        self.assertEqual(p["candidates"][0]["support"], "unsupported")
        result = finalize(self.image, self.interpretation, p, self.review(p), self.root / "blank_final")
        self.assertEqual(result["counts"]["observed"], 0)

    def test_template_finds_visible_shapes_and_refines_seed(self):
        image = Image.open(self.image)
        draw = ImageDraw.Draw(image)
        for x, y in ((50, 50), (100, 80), (150, 110)):
            draw.polygon([(x, y - 5), (x + 5, y), (x, y + 5), (x - 5, y)], fill="black")
        image.save(self.image)
        self.interpretation["series"][0].update(marker="template", template_bbox=[42, 42, 59, 59], seeds=[], match_threshold=.9)
        p = analyze(self.image, self.interpretation, self.root / "auto")
        self.assertEqual(len(p["candidates"]), 3)
        self.assertTrue(all(c["support"] == "supported" for c in p["candidates"]))
        self.interpretation["series"][0]["seeds"] = [{"x": 103, "y": 78}]
        p = analyze(self.image, self.interpretation, self.root / "seeded")
        self.assertEqual(len(p["candidates"]), 1)
        self.assertAlmostEqual(p["candidates"][0]["pixel"]["x"], 100.)
        self.assertAlmostEqual(p["candidates"][0]["pixel"]["y"], 80.)

    def test_trace_connected_blob_is_unsupported(self):
        image = Image.open(self.image)
        draw = ImageDraw.Draw(image)
        draw.line((10, 80, 190, 80), fill="black", width=2)
        draw.ellipse((95, 75, 105, 85), fill="black")
        image.save(self.image)
        self.interpretation["series"][0]["marker"] = "blob"
        p = analyze(self.image, self.interpretation, self.root / "blob")
        self.assertEqual(p["candidates"][0]["support"], "unsupported")
        self.assertTrue(p["candidates"][0]["diagnostics"]["touches_search_boundary"])

    def test_invalid_axis_and_piecewise_gap(self):
        for axis in (
            {"scale": "log", "anchors": [{"pixel": 0, "value": 0}, {"pixel": 10, "value": 100}]},
            {"scale": "linear", "anchors": [{"pixel": 0, "value": 1}, {"pixel": 0, "value": 2}]},
            {"scale": "linear", "anchors": [{"pixel": 0, "value": 1}, {"pixel": 10, "value": float("inf")}]},
            {"scale": "category", "anchors": []},
        ):
            with self.assertRaises(ValueError):
                Axis(axis, "test")
        axis = Axis({"scale": "linear", "segments": [
            {"pixel_min": 0, "pixel_max": 40, "anchors": [{"pixel": 0, "value": 0}, {"pixel": 40, "value": 4}]},
            {"pixel_min": 60, "pixel_max": 100, "anchors": [{"pixel": 60, "value": 20}, {"pixel": 100, "value": 24}]},
        ]}, "broken")
        self.assertEqual(axis.value(20), 2.)
        self.assertIsNone(axis.value(50))
        self.assertIsNone(axis.value(-1))
        self.assertEqual(axis.value(80), 22.)

    def test_tick_fit_rejects_inconsistent_linear_and_log_scales(self):
        for scale, values in (("linear", [0, 10, 100]), ("log", [1, 10, 1000])):
            with self.subTest(scale=scale):
                definition = {"scale": scale, "anchors": [
                    {"pixel": p, "value": v} for p, v in zip((0, 50, 100), values)],
                    "calibration_pixel_tolerance": 100, "axis_tolerance_fraction": 1}
                with self.assertRaisesRegex(ValueError, "fixed 2 px limit"):
                    Axis(definition, "bad_ticks")

    def test_noisy_ticks_fit_one_scale_instead_of_warping_between_ticks(self):
        linear = Axis({"scale": "linear", "anchors": [
            {"pixel": 0, "value": 0}, {"pixel": 49, "value": 5}, {"pixel": 100, "value": 10}]}, "linear")
        # The one-pixel middle-tick error is allowed, but does not create a kink.
        self.assertAlmostEqual(linear.value(25) - linear.value(0), linear.value(75) - linear.value(50))
        self.assertNotAlmostEqual(linear.value(49), 5, places=4)
        self.assertLess(linear.fit_diagnostics[0]["max_residual_pixels"], 1)
        logarithmic = Axis({"scale": "log", "anchors": [
            {"pixel": 0, "value": 1}, {"pixel": 49, "value": 10}, {"pixel": 100, "value": 100}]}, "log")
        self.assertAlmostEqual(logarithmic.value(25) / logarithmic.value(0), logarithmic.value(75) / logarithmic.value(50))

    def test_comparison_tolerates_only_small_outer_endpoint_disagreement(self):
        primary = Axis(self.interpretation["x_axis"], "primary")
        for shift, accepted in ((.1, True), (2.1, False)):
            with self.subTest(shift=shift):
                definition = copy.deepcopy(self.interpretation["x_axis"])
                for anchor in definition["anchors"]:
                    anchor["pixel"] += shift
                review = Axis(definition, "review")
                # A generous data-space tolerance isolates the endpoint rule.
                agreement = _axis_agreement(primary, review, [100], .1)
                self.assertEqual(agreement["accepted"], accepted)
                if accepted:
                    self.assertTrue(any(c["outer_endpoint_tolerance_used"] for c in agreement["checks"]))
        broken = {"scale": "linear", "segments": [
            {"anchors": [{"pixel": 0, "value": 0}, {"pixel": 40, "value": 4}]},
            {"anchors": [{"pixel": 60, "value": 20}, {"pixel": 100, "value": 24}]}]}
        changed = copy.deepcopy(broken)
        changed["segments"][0]["anchors"][1] = {"pixel": 40.1, "value": 4.01}
        agreement = _axis_agreement(Axis(broken, "primary"), Axis(changed, "review"), [20, 80], .1)
        self.assertFalse(agreement["accepted"])
        self.assertIn(40.1, agreement["domain_mismatch_pixels"])

    def test_endpoint_comparison_tolerance_does_not_extend_export_domain(self):
        self.interpretation["plot_bbox"] = [0, 10, 200, 150]
        self.interpretation["series"][0]["seeds"] = [{"x": 9.9, "y": 80}]
        proposals = analyze(self.image, self.interpretation, self.root / "proposal")
        review = self.review(proposals)
        for anchor in review["axis_check"]["x_axis"]["anchors"]:
            anchor["pixel"] -= .1
        result = finalize(self.image, self.interpretation, proposals, review, self.root / "final")
        self.assertTrue(result["axis_agreement"]["x_axis"]["accepted"])
        self.assertEqual(result["counts"]["observed"], 0)
        self.assertIsNone(result["rows"][0]["x"])
        self.assertIn("outside_calibrated_domain", result["rows"][0]["flags"])

    def test_measured_ticks_outrank_a_reviewer_reread_of_the_same_axis(self):
        proposals = analyze(self.image, self.interpretation, self.root / "proposal")
        review = self.review(proposals)
        for anchor in review["axis_check"]["x_axis"]["anchors"]:
            anchor["pixel"] -= 6
        self.interpretation["axis_tick_check"] = {"agrees": True, "inconclusive": False,
                                                  "axes": {"x_axis": {"agrees": True, "checked": True},
                                                           "y_axis": {"agrees": True, "checked": True}}}
        result = finalize(self.image, self.interpretation, review=review, proposals=proposals, outdir=self.root / "final")
        agreement = result["axis_agreement"]["x_axis"]
        self.assertTrue(agreement["accepted"])
        self.assertEqual(agreement["reason"], "anchors_confirmed_by_detected_ticks")
        self.assertFalse(agreement["independent_review"]["accepted"])

    def test_measured_ticks_do_not_override_a_scale_disagreement(self):
        proposals = analyze(self.image, self.interpretation, self.root / "proposal")
        review = self.review(proposals)
        review["axis_check"]["x_axis"] = {"scale": "log", "unit": "h",
                                          "anchors": [{"pixel": a["pixel"], "value": a["value"] + 1}
                                                      for a in review["axis_check"]["x_axis"]["anchors"]]}
        self.interpretation["axis_tick_check"] = {"agrees": True, "inconclusive": False,
                                                  "axes": {"x_axis": {"agrees": True, "checked": True}}}
        result = finalize(self.image, self.interpretation, review=review, proposals=proposals, outdir=self.root / "final")
        self.assertFalse(result["axis_agreement"]["x_axis"]["accepted"])
        self.assertEqual(result["status"], "review_required")

    def test_image_identity_is_enforced(self):
        p = analyze(self.image, self.interpretation, self.root / "proposal")
        Image.new("RGB", (200, 160), "black").save(self.image)
        with self.assertRaises(ValueError):
            finalize(self.image, self.interpretation, p, self.review(p), self.root / "final")


if __name__ == "__main__":
    unittest.main()

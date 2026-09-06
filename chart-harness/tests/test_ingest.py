"""Coordinate and PDF fidelity regressions; run with unittest, no network."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from chart_harness.ingest import crop_image, inspect_document, render_page, rotate_image, _score_text

try:
    import fitz
except ImportError:
    fitz = None


class CropTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.png"
        y, x = np.mgrid[:60, :100]
        self.pixels = np.stack([x, y, x + y], axis=-1).astype(np.uint8)
        Image.fromarray(self.pixels).save(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def test_lossless_crop_retains_source_coordinates_and_hash(self):
        out = self.root / "crop.png"
        result = crop_image(self.source, [10, 20, 70, 50], out)
        np.testing.assert_array_equal(np.asarray(Image.open(out)), self.pixels[20:50, 10:70])
        transform = np.array(result["output_to_source"])
        np.testing.assert_allclose(transform @ [7, 8, 1], [17, 28, 1])
        self.assertEqual(result["source_sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(json.loads(Path(str(out) + ".json").read_text()), result)

    def test_resize_maps_pixel_centers_and_edges_separately(self):
        result = crop_image(self.source, [10, 20, 70, 50], self.root / "small.png", max_side=20)
        self.assertEqual(result["output_size"], [20, 10])
        center = np.array(result["output_to_source"])
        edges = np.array(result["output_edges_to_source_edges"])
        np.testing.assert_allclose(center @ [0, 0, 1], [11, 21, 1])
        np.testing.assert_allclose(center @ [19, 9, 1], [68, 48, 1])
        np.testing.assert_allclose(edges @ [20, 10, 1], [70, 50, 1])

    def test_fractional_crop_rounds_outward_and_rejects_padding(self):
        result = crop_image(self.source, [10.2, 20.8, 69.2, 49.1], self.root / "fractional.png")
        self.assertEqual(result["crop_box"], [10, 20, 70, 50])
        for box in ([-1, 0, 5, 5], [0, 0, 101, 10], [5, 5, 5, 10], [0, 0, float("nan"), 2]):
            with self.assertRaises(ValueError):
                crop_image(self.source, box, self.root / "invalid.png")

    def test_does_not_overwrite_input(self):
        original = self.source.read_bytes()
        with self.assertRaises(ValueError):
            crop_image(self.source, [0, 0, 10, 10], self.source)
        self.assertEqual(self.source.read_bytes(), original)

    def test_all_quarter_turns_map_each_pixel_back_to_original(self):
        for angle in (0, 90, 180, 270):
            output = self.root / f"rotated-{angle}.png"
            metadata = rotate_image(self.source, angle, output)
            with Image.open(output) as opened:
                pixels = np.asarray(opened)
            y, x = np.mgrid[:pixels.shape[0], :pixels.shape[1]]
            points = np.stack([x.ravel(), y.ravel(), np.ones(x.size)], axis=0)
            mapped = (np.array(metadata["output_to_source"]) @ points).astype(int)
            np.testing.assert_array_equal(pixels.reshape(-1, 3), self.pixels[mapped[1], mapped[0]])


@unittest.skipIf(fitz is None, "PyMuPDF is not installed")
class PDFTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / "embedded.png"
        y, x = np.mgrid[:100, :160]
        self.pixels = np.stack([x, y, (x + y) % 256], axis=-1).astype(np.uint8)
        Image.fromarray(self.pixels).save(self.image)

    def tearDown(self):
        self.temp.cleanup()

    def make_image_pdf(self, name, *, width=80, height=50, rotation=0, overlay=False):
        output = self.root / name
        with fitz.open() as document:
            page = document.new_page(width=width, height=height)
            page.insert_image(page.rect, filename=str(self.image), keep_proportion=False)
            # PyMuPDF tags newly inserted RGB PNGs with its sRGB ICC profile.
            # Use direct DeviceRGB to exercise the conservative safe path.
            document.xref_set_key(page.get_images()[0][0], "ColorSpace", "/DeviceRGB")
            if overlay:
                page.draw_rect(fitz.Rect(10, 10, 30, 30), color=(1, 0, 0), fill=(1, 0, 0))
            page.set_rotation(rotation)
            document.save(output)
        return output

    def metadata(self, image):
        return json.loads(Path(str(image) + ".json").read_text())

    def test_single_undistorted_image_keeps_exact_native_pixels(self):
        pdf = self.make_image_pdf("native.pdf")
        output = render_page(pdf, 1, self.root / "native.png", dpi=72)
        metadata = self.metadata(output)
        self.assertEqual(metadata["method"], "native_image")
        self.assertEqual(metadata["pixel_size"], [160, 100])
        np.testing.assert_array_equal(np.asarray(Image.open(output)), self.pixels)
        self.assertEqual(metadata["source_sha256"], hashlib.sha256(pdf.read_bytes()).hexdigest())

    def test_rotated_and_distorted_pages_render_in_visible_geometry(self):
        pdf = self.make_image_pdf("rotated.pdf", rotation=90)
        rotated = render_page(pdf, 1, self.root / "rotated.png", dpi=72)
        meta = self.metadata(rotated)
        self.assertEqual(meta["method"], "pdf_render")
        self.assertEqual(meta["native_extraction_reason"], "page_rotation")
        self.assertEqual(meta["pixel_size"], [50, 80])
        pdf = self.make_image_pdf("distorted.pdf", width=80, height=80)
        distorted = render_page(pdf, 1, self.root / "distorted.png", dpi=72)
        self.assertEqual(self.metadata(distorted)["native_extraction_reason"], "nonuniform_image_scale")
        with Image.open(distorted) as image:
            self.assertEqual(image.size, (80, 80))

    def test_vector_overlay_is_preserved_by_rendering(self):
        pdf = self.make_image_pdf("overlay.pdf", overlay=True)
        output = render_page(pdf, 1, self.root / "overlay.png", dpi=72)
        self.assertEqual(self.metadata(output)["method"], "pdf_render")
        self.assertEqual(Image.open(output).getpixel((20, 20)), (255, 0, 0))

    def test_unusual_page_dimensions_cannot_trigger_unbounded_dpi_render(self):
        pdf = self.make_image_pdf('large-points.pdf',width=8000,height=5000,overlay=True)
        output = render_page(pdf,1,self.root/'bounded.png',dpi=216)
        metadata = self.metadata(output)
        self.assertLessEqual(max(metadata['pixel_size']),4096)
        self.assertEqual(metadata['method'],'pdf_render')
        self.assertAlmostEqual(metadata['pixel_centers_to_visible_page_points'][0][0],8000/4096)

    def test_clipped_full_page_image_falls_back_to_pdf_renderer(self):
        pdf = self.make_image_pdf("unclipped.pdf")
        clipped = self.root / "clipped.pdf"
        with fitz.open(pdf) as document:
            page = document[0]
            content = page.read_contents()
            document.update_stream(page.get_contents()[0], b"q 0 0 20 20 re W n " + content + b" Q")
            document.save(clipped)
        output = render_page(clipped, 1, self.root / "clipped.png", dpi=72)
        self.assertEqual(self.metadata(output)["method"], "pdf_render")
        with Image.open(output) as opened:
            self.assertEqual(opened.getpixel((60, 20)), (255, 255, 255))

    def test_query_prioritizes_figure_caption_and_explicit_page_overrides(self):
        pdf = self.root / "search.pdf"
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((30, 30), "Results discussed in Figure 2 appear later in this document.")
            page = document.new_page()
            page.insert_text((30, 30), "Methods and controls")
            page = document.new_page()
            page.insert_text((30, 30), "FIG. 2")
            page.draw_rect(fitz.Rect(30, 70, 400, 500))
            document.save(pdf)
        result = inspect_document(pdf, self.root / "ranked", "figure 2", max_candidates=2)
        self.assertEqual([item["page_number"] for item in result["candidates"]], [3, 1])
        self.assertTrue(Path(result["contact_sheet_path"]).is_file())
        self.assertLessEqual(len(result["candidates"][0]["text_snippet"]), 362)
        explicit = inspect_document(pdf, self.root / "explicit", "figure 2", pages=[2])
        self.assertEqual([item["page_number"] for item in explicit["candidates"]], [2])
        self.assertEqual(explicit["selection"], "explicit_pages")
        with self.assertRaises(ValueError):
            inspect_document(pdf, self.root / "bad-pages", pages=[0])
        with self.assertRaises(ValueError):
            render_page(pdf, 0, self.root / "zero.png")

    def test_isolated_ocr_caption_confusion_does_not_change_other_values(self):
        exact, _ = _score_text("Fig. 1\nTime (days)", "figure 1", 1, 0)
        confused, _ = _score_text("Fig. I\nTime (days)", "figure 1", 1, 0)
        unrelated, _ = _score_text("Fig. 2\nDose I", "figure 1", 1, 0)
        self.assertEqual(confused, exact)
        self.assertLess(unrelated, confused)

    def test_scan_without_ocr_has_bounded_visual_candidates_and_warning(self):
        pdf = self.make_image_pdf("scan.pdf")
        result = inspect_document(pdf, self.root / "scan", "figure 99")
        self.assertEqual(result["candidates"][0]["text_snippet"], "")
        self.assertEqual(result["candidates"][0]["method"], "native_image")
        self.assertTrue(any("no extracted text" in message for message in result["warnings"]))
        self.assertTrue(any("No query tokens" in message for message in result["warnings"]))


if __name__ == "__main__":
    unittest.main()

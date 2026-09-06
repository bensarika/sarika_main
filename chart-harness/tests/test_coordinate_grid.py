import tempfile
import unittest
from pathlib import Path
from PIL import Image
from chart_harness.coordinate_grid import coordinate_grid

class CoordinateGridTest(unittest.TestCase):
    def test_grid_preserves_pixel_frame_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.png'; target=Path(directory)/'grid.png'
            Image.new('RGB',(143,217),'black').save(source)
            original=source.read_bytes()
            coordinate_grid(source,target,100)
            self.assertEqual(source.read_bytes(),original)
            with Image.open(target) as image:
                self.assertEqual(image.size,(143,217))
                self.assertEqual(image.getpixel((100,180)),(110,180,225))
                self.assertEqual(image.getpixel((80,180)),(0,0,0))

if __name__=='__main__':unittest.main()

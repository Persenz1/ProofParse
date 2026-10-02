"""Wrapped formulas keep their baselines and exclude intervening page content."""
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from proofparse.preprocess.render import crop_fragments


class FragmentCropTests(unittest.TestCase):
    def test_stitch_keeps_baselines_and_excludes_union_box_prose(self):
        source = Image.new("RGB", (80, 60), "white")
        source.putpixel((20, 20), (255, 0, 0))
        source.putpixel((5, 40), (0, 0, 255))
        source.putpixel((10, 28), (0, 255, 0))  # prose outside the fragments
        page = MagicMock()
        page.render.return_value.to_pil.return_value = source
        pdf = MagicMock()
        pdf.__enter__.return_value = pdf
        pdf.__getitem__.return_value = page
        captured = []
        with patch("proofparse.preprocess.render.pdfium.PdfDocument", return_value=pdf), \
             patch.object(Path, "mkdir"), patch.object(Image.Image, "save",
                autospec=True, side_effect=lambda image, path: captured.append(image.copy())):
            crop_fragments(Path("page.pdf"), [(0, [[20, 10, 40, 25], [5, 35, 15, 50]],
                                                 [20, 40], Path("output/crop.png"), 0)], scale=1)
        pixels = captured[0].load()
        red = [(x, y) for y in range(captured[0].height) for x in range(captured[0].width)
               if pixels[x, y] == (255, 0, 0)]
        blue = [(x, y) for y in range(captured[0].height) for x in range(captured[0].width)
                if pixels[x, y] == (0, 0, 255)]
        self.assertEqual(red[0][1], blue[0][1])
        self.assertFalse(any(pixels[x, y] == (0, 255, 0)
                             for y in range(captured[0].height) for x in range(captured[0].width)))


if __name__ == "__main__":
    unittest.main()

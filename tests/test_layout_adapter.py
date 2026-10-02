"""PP-DocLayoutV3 result conversion checks, without model/framework imports."""
import unittest

from proofparse import ir
from proofparse.engines.paddle_layout import convert


def box(label, coordinates, order, polygon=None):
    result = {"cls_id": 22, "label": label, "score": 0.9,
              "coordinate": coordinates, "order": order}
    if polygon is not None:
        result["polygon_points"] = polygon
    return result


class LayoutAdapterTests(unittest.TestCase):
    def test_pixels_and_polygon_become_points_in_model_order(self):
        regions = convert({"boxes": [
            box("text", [200, 300, 400, 500], 1, [[200, 300], [400, 500]]),
            box("text", [20, 20, 100, 80], 2),
        ]}, 2.0)["regions"]
        self.assertEqual([region["bbox"] for region in regions],
                         [[100, 150, 200, 250], [10, 10, 50, 40]])
        self.assertEqual([region["order"] for region in regions], [1, 2])
        self.assertEqual(regions[0]["meta"]["polygon_pt"], [[100, 150], [200, 250]])

    def test_skipped_orders_preserve_complete_model_sequence(self):
        regions = convert({"boxes": [
            box("text", [0, 0, 200, 100], 1),
            box("image", [0, 200, 200, 300], None),
            box("figure_title", [0, 300, 200, 320], None),
            box("text", [220, 0, 420, 100], 2),
        ]}, 1.0)["regions"]
        self.assertEqual([region["order"] for region in regions], [1, 2, 3, 4])
        self.assertEqual(regions[2]["kind"], ir.CAPTION)
        self.assertNotIn("parent", regions[2])

    def test_formula_number_remains_distinct_text(self):
        number, = convert({"boxes": [box("formula_number", [180, 40, 200, 60], 1)]}, 2.0)["regions"]
        self.assertEqual(number["kind"], ir.TEXT)
        self.assertEqual(number["bbox"], [90, 20, 100, 30])
        self.assertTrue(number["meta"]["formula_number"])

    def test_inline_formula_uses_smallest_containing_prose(self):
        regions = convert({"boxes": [
            box("text", [0, 0, 400, 200], 1),
            box("text", [100, 20, 300, 100], 2),
            box("inline_formula", [120, 40, 160, 70], 3),
            box("inline_formula", [420, 40, 460, 70], 4),
        ]}, 2.0)["regions"]
        self.assertEqual(regions[2]["parent"], 1)
        self.assertEqual(regions[2]["bbox"], [60, 20, 80, 35])
        self.assertEqual(regions[3]["kind"], ir.OTHER)
        self.assertTrue(regions[3]["meta"]["orphan_inline"])


if __name__ == "__main__":
    unittest.main()

"""Checks of text-layer integration failures observed on the model pilot page."""
import unittest

from proofparse import ir
from proofparse.stages.text import build_lines, compose, math_runs, text_from_layer


def glyph(text, x, *, y=100.0, font="Prose", size=10.0, width=5.0):
    return {"text": text, "font": font, "size_pt": size,
            "origin_pt": [x, y], "bbox_pt": [x, y - 7, x + width, y + 3],
            "source_index": [int(y), int(10 * x)]}


def line(text, math_indices):
    return [glyph(c, 5 * i, font="CMMI10" if i in math_indices else "Prose")
            for i, c in enumerate(text)]


def native_runs(chars):
    return ["".join(c["text"] for c in chars[start:end]) for start, end in math_runs(chars, 10.0)]


class TextIntegrationTests(unittest.TestCase):
    def test_extension_operator_does_not_create_a_false_line_or_steal_subscript(self):
        chars = [glyph("C", 50, y=469.18, font="CMMI10"),
                 glyph("L", 56, y=470.68, font="CMMI7", size=7),
                 glyph("C", 20, y=481.14, font="CMMI10"),
                 glyph("⊗", 0, y=473.67, font="ABCDEF+CMEX10", width=11),
                 glyph("4", 11, y=476.13, size=7),
                 glyph("l", 11, y=484.13, font="CMMI7", size=7)]
        chars[3]["bbox_pt"] = [0, 473.05, 11, 483.01]
        lines = build_lines(chars)
        self.assertEqual(len(lines), 2)
        self.assertEqual("".join(c["text"] for c in lines[0]), "CL")
        self.assertIn(chars[3], lines[1])
        self.assertIn(chars[4], lines[1])
        self.assertIn(chars[5], lines[1])

    def test_ligature_continuation_does_not_insert_space_in_first(self):
        chars = [glyph("f", 0, width=5.5), glyph("i", 0, width=0),
                 glyph("r", 5.5), glyph("s", 10.5), glyph("t", 15.5),
                 glyph("f", 25.5), glyph("o", 30.5), glyph("r", 35.5)]
        self.assertEqual(compose([chars], [[]]), ("first for", []))

    def test_prose_list_bullet_stays_in_text_and_math_bullet_stays_in_formula(self):
        chars = [glyph("•", 0, font="CMSY10"), glyph("W", 12), glyph("e", 17)]
        self.assertEqual(math_runs(chars, 10), [])
        self.assertEqual(compose([chars], [[]])[0], "• We")
        self.assertEqual(native_runs([glyph("x", 0, font="CMMI10"),
                                      glyph("•", 5, font="CMSY10"),
                                      glyph("y", 10, font="CMMI10")]), ["x•y"])

    def test_compound_hyphens_and_prose_parentheses_are_not_in_crops(self):
        cases = [("controlled-U(i.e.,details)", {11}, ["U"]),
                 ("i-th", {0}, ["i"]),
                 ("QC'(thequbits)", {0, 1, 2}, ["QC'"])]
        for text, indices, expected in cases:
            with self.subTest(text=text):
                chars = line(text, indices)
                self.assertEqual(native_runs(chars), expected)
                prose, slots = compose([chars], [math_runs(chars, 10)])
                for slot in slots:
                    prose = prose.replace(ir.INLINE_SLOT, "".join(c["text"] for c in slot), 1)
                self.assertEqual(prose, text)

    def test_math_minus_and_mathematical_parentheses_are_preserved(self):
        for text, indices in (("-x", {1}), ("x-y", {0, 2}), ("x-(y)", {0, 3}),
                              ("x(y)", {0, 2})):
            with self.subTest(text=text):
                self.assertEqual(native_runs(line(text, indices)), [text])

    def test_bracketed_wrap_is_one_slot_and_never_skips_intervening_prose(self):
        first = [glyph("p", 0), glyph("r", 5), glyph("e", 10),
                 glyph("x", 20, font="CMMI10"), glyph("[", 25),
                 glyph("A", 30, font="CMMI10"), glyph("→", 35, font="CMSY10")]
        second = [glyph("B", 0, y=112, font="CMMI10"), glyph("]", 5, y=112),
                  glyph(".", 10, y=112), glyph("M", 20, y=112), glyph("o", 25, y=112),
                  glyph("r", 30, y=112), glyph("e", 35, y=112)]
        runs = [math_runs(row, 10) for row in (first, second)]
        prose, slots = compose([first, second], runs)
        self.assertEqual(prose, "pre " + ir.INLINE_SLOT + ". More")
        self.assertEqual(["".join(c["text"] for c in part) for part in slots], ["x[A→B]"])
        self.assertEqual(len(build_lines(slots[0], 10)), 2)
        block = ir.Block(id="text", page=0, bbox=[0, 90, 50, 120], kind=ir.TEXT)
        child, = text_from_layer(block, first + second, [], 10)
        self.assertEqual(len(child.extra["crop_regions"]), 2)
        self.assertEqual(child.extra["crop_baselines"], [100.0, 112.0])
        # Neither trailing prose nor a prose prefix may be crossed by a join.
        first_with_prose = first + [glyph("a", 45), glyph("n", 50), glyph("d", 55)]
        second_with_prose = [glyph("s", -15, y=112), glyph("o", -10, y=112)] + second
        for rows in ((first_with_prose, second), (first, second_with_prose)):
            with self.subTest(rows=rows):
                _, parts = compose(list(rows), [math_runs(row, 10) for row in rows])
                self.assertEqual(len(parts), 2)


if __name__ == "__main__":
    unittest.main()

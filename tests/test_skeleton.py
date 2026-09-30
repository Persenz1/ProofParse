"""Small checks of the new pipeline skeleton; no models, no TeX."""
import unittest

from proofparse import ir
from proofparse.eval.score import score
from proofparse.gold import arxiv, macros, texscan
from proofparse.ir import Block, Candidate, Document, Page
from proofparse.stages import escalate, reconcile
from proofparse.stages.text import compose, math_runs


class TexScanTests(unittest.TestCase):
    def test_delimiters_comments_and_definitions(self):
        src = (r"\newcommand{\R}{\mathbb{R}} \begin{document}"
               "Let $x\\in\\R$ % $not math$\n"
               r"and \verb|$no$| then \[a+b\] \begin{align} a&=b\\ c&=d\\ \end{align}"
               r"\text{$y$} \end{document}")
        segs = texscan.scan(src, body_only=True)
        bodies = [src[s.body_start:s.body_end] for s in segs]
        self.assertEqual(bodies[:2], [r"x\in\R", "a+b"])
        self.assertEqual([s.env for s in segs][2], "align")
        align = segs[2]
        _, close = texscan.marker_positions(src, align)
        self.assertTrue(src[align.body_start:close].rstrip().endswith("c&=d"))

    def test_inline_math_inside_text_command_is_not_a_segment_end(self):
        src = r"$a \text{ if $b$ } c$"
        seg, = texscan.scan(src)
        self.assertEqual(src[seg.body_start:seg.body_end], r"a \text{ if $b$ } c")


class MacroTests(unittest.TestCase):
    def test_expand_common_definitions(self):
        defs, _ = macros.collect(r"\newcommand{\R}{\mathbb{R}}\newcommand\norm[1]{\lVert #1\rVert}"
                                 r"\DeclareMathOperator{\tr}{tr}\def\e#1{e^{#1}}"
                                 r"\DeclarePairedDelimiter\abs{\lvert}{\rvert}")
        out, ok = macros.expand(r"\norm{x}\in\R, \tr A, \e{t}, \abs*{y}", defs)
        self.assertTrue(ok)
        self.assertEqual(out, r"\lVert x\rVert\in\mathbb{R}, \operatorname{tr} A, e^{t}, \left\lvert y\right\rvert")

    def test_recursive_definition_stops(self):
        defs, _ = macros.collect(r"\newcommand{\a}{\a x}")
        _, ok = macros.expand(r"\a", defs)
        self.assertFalse(ok)


class GoldColorTests(unittest.TestCase):
    def test_color_ids_round_trip_and_black_is_not_an_id(self):
        for n in (0, 1, 39, 40, 1599, 60000):
            rgb = [float(f"{v:.4f}") for v in arxiv.color_of(n)]
            self.assertEqual(arxiv.decode_color(rgb), n)
        self.assertIsNone(arxiv.decode_color((0.0, 0.0, 0.0)))
        self.assertIsNone(arxiv.decode_color((1.0, 0.0, 0.0)))


def glyph(text, x, size=10.0, font="CMR10", y=100.0):
    return {"text": text, "bbox_pt": [x, y - 7, x + 5, y + 2], "origin_pt": [x, y], "size_pt": size,
            "font": font, "render_type": 0, "opacity": 1, "source_index": [0, int(x)]}


class InlineMathTests(unittest.TestCase):
    def test_run_covers_math_and_trims_punctuation(self):
        line = [glyph(c, 10 + 6 * i) for i, c in enumerate("let")]
        line += [glyph("x", 40, font="CMMI10"), glyph("=", 46), glyph("1", 52), glyph(",", 58)]
        line += [glyph(c, 68 + 6 * i) for i, c in enumerate("so")]
        runs = math_runs(line, 10.0)
        self.assertEqual([(s, e) for s, e in runs], [(3, 6)])
        text, slots = compose([line], [runs])
        self.assertEqual(text, "let " + ir.INLINE_SLOT + ", so")
        self.assertEqual("".join(g["text"] for g in slots[0]), "x=1")


def math_block(*cands):
    b = Block(id="p000b000", page=0, bbox=[0, 0, 10, 10], kind=ir.DISPLAY_MATH)
    b.candidates = [Candidate(engine=e, family=f, content=c) for e, f, c in cands]
    return b


class ReconcileTests(unittest.TestCase):
    def test_two_families_agree(self):
        d = reconcile.decide_formula(math_block(("a", "fa", "x^2"), ("b", "fb", "x^{2}")), ["a", "b"])
        self.assertEqual((d.status, d.rule), (ir.ACCEPTED, "unanimous:fa+fb"))

    def test_same_family_agreement_is_not_independent(self):
        d = reconcile.decide_formula(math_block(("m", "pp", "x"), ("l", "pp", "x")), ["m", "l"])
        self.assertEqual(d.status, ir.UNVERIFIED)

    def test_disagreement_is_a_conflict(self):
        d = reconcile.decide_formula(math_block(("a", "fa", "x_1"), ("b", "fb", "x_2")), ["a", "b"])
        self.assertEqual(d.status, ir.CONFLICT)


class EscalationTests(unittest.TestCase):
    def test_answers_are_validated_against_evidence(self):
        b = math_block(("a", "fa", "x_1"), ("b", "fb", "x_2"))
        b.decision = reconcile.decide_formula(b, ["a", "b"])
        good = {"input_hash": reconcile.evidence_hash(b), "choice": "custom", "latex": r"x_{1}"}
        self.assertEqual(escalate.validate(b, good), ("x_{1}", None))
        self.assertEqual(escalate.validate(b, good | {"input_hash": "old"})[1], "stale_input_hash")
        self.assertEqual(escalate.validate(b, good | {"latex": "$x$"})[1], "math_delimiters_in_latex")
        self.assertEqual(escalate.validate(b, good | {"latex": r"\frac{x"})[1][:13], "invalid_latex")


class ScoreAndIRTests(unittest.TestCase):
    def test_score_levels(self):
        s = score(r"\left( x \right) \tag{3}", r"(x)")
        self.assertFalse(s["strict"])
        self.assertTrue(s["loose"])
        self.assertFalse(score(r"\mathbf{x}", "x")["loose"])

    def test_document_round_trip(self):
        doc = Document(pages=[Page(0, 612, 792)], blocks=[math_block(("a", "fa", "x"))])
        again = Document.from_dict(doc.to_dict())
        self.assertEqual(again.blocks[0].candidates[0].content, "x")


if __name__ == "__main__":
    unittest.main()

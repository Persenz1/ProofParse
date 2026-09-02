"""人工复核后回滚 4 处错误修正：把块内容从 corrected 换回 parser 候选 A，
并在 qc.json 里标记 agent_override。一次性脚本。"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from proofparse.review.apply import rebuild_markdown, _flex_pattern

FIXES = [
    # (paper, formula_check kind, index)
    ("A_Survey_of_Motion_Planning_and_Control_Techniques_for_Self-Driving_Urban_Vehicles", "inline", 30),
    ("A_Survey_of_Motion_Planning_and_Control_Techniques_for_Self-Driving_Urban_Vehicles", "inline", 31),
    ("A_Survey_of_Motion_Planning_and_Control_Techniques_for_Self-Driving_Urban_Vehicles", "inline", 32),
    ("A_Survey_of_Motion_Planning_and_Control_Techniques_for_Self-Driving_Urban_Vehicles", "inline", 33),
    ("Visual_Servo_Control_Part_I_Basic_Approaches", "inline", 7),
]
OVERRIDE_REASON = {
    30: "裁剪图左缘被裁，B 多出的冒号无法证实；保守回滚为 parser",
    31: "custom 与 A 内容相同，统一记为 parser",
    32: "裁剪图区域错位（拍到散文），custom 把散文换进公式，回滚为 parser",
    33: "裁剪图拍到了邻行的 x_rnd，custom 换错了位置，回滚为 parser",
    7: "裁剪图拍到上方分式行，段落里的 Z 本身正确，回滚为 parser",
}

for paper, kind, idx in FIXES:
    pdir = Path("output/papers") / paper
    qc = json.loads((pdir / "qc.json").read_text(encoding="utf-8"))
    r = qc["formula_check"][kind][idx]
    fv = r["final_verdict"]
    corrected = fv.get("corrected_latex") or r["formula_ocr"]
    original = r["parser"]

    doc = json.loads((pdir / "document.json").read_text(encoding="utf-8"))
    pat = _flex_pattern(corrected)
    hit = False
    for b in doc["blocks"]:
        if b.get("page") == r["page"] and b.get("content") and pat.search(b["content"]):
            b["content"] = pat.sub(lambda m: original, b["content"], count=1)
            hit = True
            break
    if not hit:
        print(f"[warn] {paper[:20]} {kind}{idx}: 未找到 corrected 串，可能未曾应用")
    else:
        (pdir / "document.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    r["final_verdict"] = {
        "reviewed_at": fv.get("reviewed_at"), "layer": "multimodal",
        "status": "resolved", "choice": "parser", "corrected_latex": None,
        "confidence": fv.get("confidence", 0),
        "reason": "agent 人工复核推翻 MiMo 裁决：" + OVERRIDE_REASON[idx],
        "model": fv.get("model"), "agent_override": True,
        "previous_verdict": {k: fv.get(k) for k in ("choice", "corrected_latex", "reason")},
    }
    (pdir / "qc.json").write_text(
        json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")
    rebuild_markdown(pdir)
    print(f"[fix] {paper[:30]} {kind}{idx}: 已回滚并标记 override")

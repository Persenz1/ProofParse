"""一次性修复脚本：从 _mineru_raw 缓存复原被终审改过的 document.json / <name>.md。

不调用 MinerU / 公式模型（无 GPU、不重解析 PDF）：直接读缓存的
content_list.json，重跑确定性的 coverage -> filtering -> markdown 步骤。
qc.json 保留不动（裁决记录不丢）。同时用更大边距重生成复核裁剪图。

用法: python restore_pristine.py <paper_dir> [<paper_dir>...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from proofparse.models.document import Document
from proofparse.normalize.coverage import check_coverage
from proofparse.normalize.filtering import apply_filtering
from proofparse.normalize.markdown import build_markdown
from proofparse.parsers.mineru_parser import MinerUParser
from proofparse.pdf.render import render_crop

REVIEW_PAD = 60  # 复核图边距（scale=3 下约 20pt），给 VLM 足够上下文


def restore_paper(paper_dir: Path) -> None:
    paper_dir = Path(paper_dir)
    stem = paper_dir.name
    pdf_path = Path("test_pdfs") / f"{stem}.pdf"
    assert pdf_path.exists(), f"找不到 PDF: {pdf_path}"

    raws = sorted((paper_dir / "_mineru_raw").rglob(f"{stem}_content_list.json"))
    assert raws, f"{stem} 无 content_list.json 缓存"
    raw = json.loads(raws[0].read_text(encoding="utf-8"))

    parser = MinerUParser()
    doc = Document(source_pdf=str(pdf_path), parser={"name": "mineru", "backend": "pipeline"})
    for item in raw:
        doc.blocks.append(parser._convert_block(item))
    doc.metadata = parser._extract_metadata(doc.blocks)

    # 与 cli.process_pdf 相同的确定性步骤
    check_coverage(pdf_path, doc.blocks)
    kept, dropped, stats = apply_filtering(doc.blocks)
    md = build_markdown(doc, kept)
    md_path = paper_dir / f"{stem}.md"
    md_path.write_text(md, encoding="utf-8")

    old = json.loads((paper_dir / "document.json").read_text(encoding="utf-8"))
    document_json = doc.to_dict()
    document_json["pdf_sha256"] = old.get("pdf_sha256")
    kept_ids = {id(b) for b in kept}
    for b_dict, b_obj in zip(document_json["blocks"], doc.blocks):
        b_dict["in_markdown"] = id(b_obj) in kept_ids
    assert len(document_json["blocks"]) == len(old["blocks"]), \
        f"{stem} 块数变化 {len(old['blocks'])} -> {len(document_json['blocks'])}，block_index 会错位！"
    (paper_dir / "document.json").write_text(
        json.dumps(document_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[restore] {stem}: blocks={len(doc.blocks)} md 已复原")

    # 重生成复核图（大边距），文件名不变
    qc = json.loads((paper_dir / "qc.json").read_text(encoding="utf-8"))
    n_assets = 0
    for w in qc.get("warnings", []):
        if w.get("review_asset") and w.get("bbox"):
            render_crop(pdf_path, w["page"], w["bbox"],
                        paper_dir / w["review_asset"], pad=REVIEW_PAD)
            n_assets += 1
    fc = qc.get("formula_check") or {}
    import pypdfium2 as pdfium
    for kind in ("display", "inline"):
        for r in fc.get(kind, []):
            if r.get("verdict") != "REVIEW" or not r.get("review_asset"):
                continue
            bbox = r["bbox"]
            if kind == "inline":  # PDF 点 -> 1000 归一化
                pdf = pdfium.PdfDocument(str(pdf_path))
                w_pt, h_pt = pdf[r["page"]].get_size()
                pdf.close()
                bbox = [bbox[0] / w_pt * 1000, bbox[1] / h_pt * 1000,
                        bbox[2] / w_pt * 1000, bbox[3] / h_pt * 1000]
            render_crop(pdf_path, r["page"], bbox,
                        paper_dir / r["review_asset"], pad=REVIEW_PAD)
            n_assets += 1
    print(f"[assets] {stem}: 重生成 {n_assets} 张复核图（pad={REVIEW_PAD}）")

    # 清掉非 parser 的裁决（含 warnings 内嵌 span 的镜像），让它们重裁
    n_cleared = 0
    for w in qc.get("warnings", []):
        fv = w.get("final_verdict")
        if fv and fv.get("choice") not in (None, "parser"):
            del w["final_verdict"]; n_cleared += 1
        for s in w.get("formula_spans", []):
            fv = s.get("final_verdict")
            if fv and fv.get("choice") not in (None, "parser"):
                del s["final_verdict"]
    for kind in ("display", "inline"):
        for r in fc.get(kind, []):
            fv = r.get("final_verdict")
            if fv and fv.get("choice") not in (None, "parser"):
                del r["final_verdict"]; n_cleared += 1
    (paper_dir / "qc.json").write_text(
        json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[qc] {stem}: 清除 {n_cleared} 条非 parser 裁决，待重裁")


if __name__ == "__main__":
    for d in sys.argv[1:]:
        restore_paper(Path(d))

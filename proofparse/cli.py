"""命令行入口：proofparse paper.pdf | proofparse ./pdf_folder/

全流程编排：
    parse (MinerU)
      -> 文本覆盖率检查与自动补回（coverage）
      -> References 截断 / Figure-Table 过滤（filtering）
      -> 语义 Markdown 构建（markdown）
      -> 本地 QC（qc）+ 复核图生成（review_assets）

输出结构：
    <output_root>/<stem>/
        ├── <stem>.md
        ├── document.json      （统一中间模型，含被丢弃块，供追溯）
        ├── qc.json            （auto-fixed / needs-review 分级）
        ├── review_assets/     （needs_review 警告的裁剪图/整页图）
        └── _mineru_raw/       （parser 原始输出）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

from . import config
from .models.document import Document
from .normalize.coverage import check_coverage
from .normalize.filtering import apply_filtering
from .normalize.markdown import build_markdown
from .formula.qc import run_qc
from .formula.double_check import double_check
from .formula.recognizer import release_formula_ocr
from .parsers.mineru_parser import MinerUParser
from .pdf.render import render_crop, render_page

_PARSERS = {"mineru": MinerUParser}


def pdf_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _generate_review_assets(qc: dict, pdf_path: Path, out_dir: Path) -> None:
    """为每条 needs_review 警告生成复核图：有 bbox 裁剪区域，无 bbox 渲染整页。"""
    assets_dir = out_dir / "review_assets"
    if assets_dir.exists():
        for old in assets_dir.glob("*.png"):  # 清除上次运行的残留
            old.unlink()
    for n, w in enumerate(qc["warnings"]):
        w["id"] = f"{w['id']}_{n}"  # 同页多条警告避免文件名冲突
        try:
            if w.get("bbox"):
                out = assets_dir / f"{w['id']}.png"
                render_crop(pdf_path, w["page"], w["bbox"], out)
            elif w.get("page") is not None:
                out = assets_dir / f"{w['id']}_page.png"
                render_page(pdf_path, w["page"], out)
            else:
                continue
            w["review_asset"] = str(out.relative_to(out_dir))
        except Exception as e:
            w["review_asset_error"] = str(e)

    # 双识别判定为 REVIEW 的公式也配裁剪图
    fc = qc.get("formula_check") or {}
    for kind in ("display", "inline"):
        for n, r in enumerate(fc.get(kind, [])):
            if r.get("verdict") != "REVIEW" or not r.get("bbox"):
                continue
            try:
                out = assets_dir / f"formula_{kind}_{n}_p{r['page']}.png"
                if kind == "display":
                    render_crop(pdf_path, r["page"], r["bbox"], out)  # 1000 归一化
                else:
                    # inline span 的 bbox 是 PDF 点，先转归一化
                    import pypdfium2 as pdfium
                    pdf = pdfium.PdfDocument(str(pdf_path))
                    w_pt, h_pt = pdf[r["page"]].get_size()
                    pdf.close()
                    bb = r["bbox"]
                    norm = [bb[0] / w_pt * 1000, bb[1] / h_pt * 1000,
                            bb[2] / w_pt * 1000, bb[3] / h_pt * 1000]
                    render_crop(pdf_path, r["page"], norm, out)
                r["review_asset"] = str(out.relative_to(out_dir))
            except Exception as e:
                r["review_asset_error"] = str(e)


def process_pdf(pdf_path: Path, output_root: Path, parser_name: str = "mineru",
                force: bool = False, formula_check: bool = True) -> Path:
    pdf_path = Path(pdf_path)
    out_dir = output_root / pdf_path.stem
    md_path = out_dir / f"{pdf_path.stem}.md"

    if md_path.exists() and not force:
        print(f"[skip] 已存在: {md_path}")
        return md_path

    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "_mineru_raw"

    # 1) 解析
    parser = _PARSERS[parser_name]()
    doc: Document = parser.parse(pdf_path, work_dir)

    # 2) 文本覆盖率检查（在过滤前做，References 截断不算召回丢失）
    coverage_result = check_coverage(pdf_path, doc.blocks)

    # 3) 确定性过滤
    kept, dropped, stats = apply_filtering(doc.blocks)

    # 4) Markdown 构建
    markdown = build_markdown(doc, kept)
    md_path.write_text(markdown, encoding="utf-8")

    # 5) document.json（含全部块 + 是否进入 markdown）
    document_json = doc.to_dict()
    document_json["pdf_sha256"] = pdf_hash(pdf_path)
    kept_ids = {id(b) for b in kept}
    for b_dict, b_obj in zip(document_json["blocks"], doc.blocks):
        b_dict["in_markdown"] = id(b_obj) in kept_ids
    (out_dir / "document.json").write_text(
        json.dumps(document_json, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6) QC + 公式双识别 + 复核图
    qc = run_qc(doc, kept, dropped, stats, coverage_result)
    if formula_check:
        try:
            double_check(pdf_path, out_dir, kept, qc, device=config.MINERU_DEVICE)
        except Exception as e:  # 双识别失败不中断主流程
            qc["formula_check"] = {"error": str(e)}
    _generate_review_assets(qc, pdf_path, out_dir)
    (out_dir / "qc.json").write_text(
        json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")

    fc = qc.get("formula_check") or {}
    print(f"[ok] {pdf_path.name} -> {md_path}  "
          f"(blocks {stats['n_blocks_kept']}/{stats['n_blocks_total']}, "
          f"auto-fixed {qc['n_auto_fixed']}, "
          f"needs-review {qc['summary']['n_needs_review']}, "
          f"eq-review {fc.get('n_display_review', '-')}/{fc.get('n_display_checked', '-')})")
    return md_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="proofparse",
        description="本地优先的科研 PDF -> Markdown 解析工具（MinerU pipeline 后端）",
    )
    ap.add_argument("input", help="PDF 文件或包含 PDF 的目录")
    ap.add_argument("-o", "--output", default=str(config.DEFAULT_OUTPUT_ROOT),
                    help="输出根目录")
    ap.add_argument("-p", "--parser", default="mineru", choices=list(_PARSERS))
    ap.add_argument("-f", "--force", action="store_true", help="已有输出时强制重跑")
    ap.add_argument("--no-formula-check", action="store_true",
                    help="跳过公式双识别（PP-FormulaNet+ 二次复核）")
    args = ap.parse_args(argv)

    input_path = Path(args.input)
    output_root = Path(args.output)

    if input_path.is_dir():
        pdfs = sorted(input_path.glob("*.pdf"))
        if not pdfs:
            print(f"目录中没有 PDF: {input_path}", file=sys.stderr)
            return 1
    elif input_path.is_file():
        pdfs = [input_path]
    else:
        print(f"输入不存在: {input_path}", file=sys.stderr)
        return 1

    n_ok, n_fail = 0, 0
    try:
        for pdf in pdfs:
            try:
                process_pdf(pdf, output_root, args.parser, args.force,
                            formula_check=not args.no_formula_check)
                n_ok += 1
            except Exception as e:  # 单篇失败不终止批处理
                n_fail += 1
                err_dir = output_root / pdf.stem
                err_dir.mkdir(parents=True, exist_ok=True)
                (err_dir / "error.log").write_text(
                    f"{e}\n\n{traceback.format_exc()}", encoding="utf-8")
                print(f"[fail] {pdf.name}: {e}", file=sys.stderr)
    finally:
        release_formula_ocr()  # 批处理结束卸载公式模型、清空显存

    print(f"完成: {n_ok} 成功, {n_fail} 失败")
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

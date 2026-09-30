"""Export a self-contained delivery: one Markdown file and its images directory."""
import argparse
from pathlib import Path
import shutil

from .normalize.markdown import build_markdown
from .review.apply import _load_document


def export_paper(paper_dir: Path, destination: Path) -> Path:
    paper_dir, destination = Path(paper_dir), Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"交付目录非空，请选择新目录：{destination}")
    doc, raw = _load_document(paper_dir)
    kept = [b for b, data in zip(doc.blocks, raw) if data.get("in_markdown")]
    assets = {}
    for block in kept:
        if block.type == 'equation':
            from .formula.qc import check_latex
            if check_latex(block.content):
                raise ValueError(f'公式 LaTeX 尚未修复，不能用截图代替交付：{block.block_id}')
        if block.type not in ("figure", "table", "unknown"):
            continue
        asset = block.extra.get("asset")
        if not asset or not (paper_dir / asset).is_file():
            raise FileNotFoundError(f"原图缺失：{block.block_id}")
        source = (paper_dir / asset).resolve()
        if source not in assets:
            assets[source] = f"images/image_{len(assets)+1:04d}{source.suffix}"
        block.extra["asset"] = assets[source]
    markdown = build_markdown(doc, kept, delivery=True)
    (destination / "images").mkdir(parents=True, exist_ok=True)
    for source, relative in assets.items():
        shutil.copy2(source, destination / relative)
    path = destination / f"{paper_dir.name}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="单篇工作目录或包含多篇论文的工作根目录")
    parser.add_argument("-o", "--output", type=Path, required=True, help="独立的最终交付目录")
    args = parser.parse_args(argv)
    papers = [args.input] if (args.input / "document.json").is_file() else sorted(p.parent for p in args.input.glob("*/document.json"))
    if not papers:
        parser.error("没有找到 document.json")
    for paper in papers:
        destination = args.output if (args.input / "document.json").is_file() else args.output / paper.name
        print(export_paper(paper, destination))
    print("已导出 Markdown 和图片目录；导出不会改变或提升复查状态。")
    return 0


if __name__ == "__main__": raise SystemExit(main())

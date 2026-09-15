"""终审编排：collect -> 裁决 -> 写回 -> 应用 -> review_summary.json。

全程只读 qc.json / review_assets / document.json，不重新解析 PDF。
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from .apply import APPLY_CONFIDENCE, apply_to_document, paper_status, rebuild_markdown, write_verdicts
from .collect import ReviewItem, collect
from .agent import FileVLM, REVIEW_INSTRUCTIONS


def export_worklist(output_root: Path, path: Path, force: bool = False) -> int:
    """导出待裁决清单（agent 裁决官模式）：看图后填 verdicts 再 --from-json 导回。"""
    items = collect(output_root, skip_done=not force)
    rows = [{
        "uid": it.uid, "kind": it.kind, "page": it.page,
        "asset": str((output_root / it.paper / it.review_asset).resolve()) if it.review_asset else None,
        "document": str((output_root / it.paper / "document.json").resolve()),
        "source_pdf": str((output_root / it.paper / "source.pdf").resolve()),
        "page_asset": str((output_root / it.paper / "review_assets" / f"page_{it.page:04d}.png").resolve()) if it.page is not None else None,
        "bbox": it.bbox,
        "likely_cause": it.likely_cause,
        "candidate_A_parser": it.candidate_a,
        "candidate_B": it.candidate_b,
        "input_hash": it.input_hash, "block_id": it.block_id,
        "context": {k:v for k,v in it.extra.items() if k != "target_content" or v != it.candidate_a},
    } for it in items]
    Path(path).write_text(json.dumps({"schema_version": 2, "instructions": REVIEW_INSTRUCTIONS, "items": rows}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return len(rows)


def run_review(output_root: Path, vlm=None, force: bool = False,
               dry_run: bool = False, verbose: bool = True,
               workers: int = 4) -> dict:
    output_root = Path(output_root)
    items = collect(output_root, skip_done=not force)

    def log(msg: str):
        if verbose:
            print(msg, flush=True)

    if dry_run:
        by_paper: dict[str, int] = defaultdict(int)
        for it in items:
            by_paper[it.paper] += 1
        log(f"[dry-run] 待裁决 {len(items)} 条：")
        for p, n in sorted(by_paper.items()):
            log(f"  {p}: {n}")
        return {"dry_run": True, "n_items": len(items), "by_paper": dict(by_paper)}

    if vlm is None:
        raise ValueError("请先导出清单，由当前多模态 agent 看图裁决，再用 --from-json 导入")

    if isinstance(vlm, FileVLM):
        items = [it for it in items if it.uid in vlm.verdicts]

    by_paper_items: dict[str, list[ReviewItem]] = defaultdict(list)
    for it in items:
        by_paper_items[it.paper].append(it)

    summary: dict[str, dict] = {}
    for paper, paper_items in sorted(by_paper_items.items()):
        paper_dir = output_root / paper
        log(f"[review] {paper}: {len(paper_items)} 条待裁决")
        results: list = [None] * len(paper_items)
        t0 = time.time()

        def _adjudicate(n: int, it: ReviewItem):
            asset = paper_dir / it.review_asset if it.review_asset else None
            if not asset or not asset.exists():
                return (it, None, f"review_asset 缺失: {it.review_asset}")
            try:
                return (it, vlm.adjudicate(it, asset), None)
            except Exception as e:
                return (it, None, str(e))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_adjudicate, n, it): n
                       for n, it in enumerate(paper_items)}
            done = 0
            for fut in as_completed(futures):
                n = futures[fut]
                results[n] = fut.result()
                done += 1
                it, verdict, error = results[n]
                if error:
                    log(f"  ({done}/{len(paper_items)}) {it.kind} p{it.page}: {error}")
                else:
                    log(f"  ({done}/{len(paper_items)}) {it.kind} p{it.page}: "
                        f"{verdict['choice']} conf={verdict['confidence']:.2f} "
                        f"{verdict['reason'][:60]}")

        # 应用确认的正确答案到 document.json，之后统一重建一次 md
        n_applied = n_confirmed = n_skipped = 0
        for it, verdict, error in results:
            if not verdict:
                n_skipped += 1
                continue
            try:
                r = apply_to_document(paper_dir, it, verdict)
            except (ValueError, KeyError, TypeError) as exc:
                r = f"skipped:invalid_patch:{exc}"
            if r.startswith("applied"):
                n_applied += 1
            elif r == "confirmed":
                n_confirmed += 1
            else:
                n_skipped += 1
                log(f"    [skip] {it.kind} p{it.page}: {r}")
            verdict["application"] = r
        if n_applied:
            md_path = rebuild_markdown(paper_dir)
            log(f"  已重建 {md_path.name}（应用 {n_applied} 处修正）")

        current = {it.uid: it.input_hash for it in collect(output_root, skip_done=False)}
        for it, verdict, error in results:
            if verdict and verdict.get("application") == "applied":
                verdict["input_hash"] = current[it.uid]
        qc = write_verdicts(paper_dir, results)

        summary[paper] = {
            "status": paper_status(qc),
            "n_reviewed": len(results),
            "n_applied": n_applied,
            "n_confirmed": n_confirmed,
            "n_skipped": n_skipped,
            "seconds": round(time.time() - t0, 1),
        }
        log(f"  => {summary[paper]['status']}"
            f"（修正 {n_applied} / 确认 {n_confirmed} / 搁置 {n_skipped}）")

    # 没跑到的论文（本轮无待审条目）也要进 summary
    for qc_path in sorted(output_root.glob("*/qc.json")):
        paper = qc_path.parent.name
        if paper not in summary:
            qc = json.loads(qc_path.read_text(encoding="utf-8"))
            summary[paper] = {"status": paper_status(qc), "n_reviewed": 0,
                              "n_applied": 0, "n_confirmed": 0, "n_skipped": 0}

    # 已确认页的内容被后续区域修正时，不能继续宣称已完成整页复查。
    for it in collect(output_root):
        if it.paper in summary:
            summary[it.paper]["status"] = "still_open"

    out = output_root / "review_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    n_open = sum(1 for s in summary.values() if s["status"] == "still_open")
    log(f"[done] summary -> {out}；still_open {n_open}/{len(summary)} 篇")
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m proofparse.review",
        description="QC 第 3 层：多模态终审（只读 qc.json，不重新解析 PDF）")
    ap.add_argument("output_root", help="输出根目录（含各论文子目录）")
    ap.add_argument("-f", "--force", action="store_true",
                    help="忽略已有 final_verdict，全部重裁")
    ap.add_argument("--dry-run", action="store_true",
                    help="只列出待裁决清单，不调用模型")
    ap.add_argument("-j", "--workers", type=int, default=4, help="并发裁决线程数")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--export", metavar="WORKLIST.json",
                    help="导出待裁决清单后退出（agent 裁决官模式）")
    mode.add_argument("--from-json", metavar="VERDICTS.json",
                    help="导入当前多模态 agent 看图后生成的 JSON 裁决")
    mode.add_argument("--api", action="store_true", help="明确授权向指定 API 发送本轮待审图片和文本")
    ap.add_argument("--api-url", help="OpenAI-compatible base URL")
    ap.add_argument("--api-model", help="Vision model name")
    ap.add_argument("--max-requests", type=int, default=20, help="API 新请求数上限；不是货币预算")
    ap.add_argument("--max-output-tokens", type=int, default=4096)
    args = ap.parse_args(argv)

    if args.export or (not args.from_json and not args.api and not args.dry_run):
        export_path = Path(args.export) if args.export else Path(args.output_root) / "review_worklist.json"
        n = export_worklist(Path(args.output_root), export_path,
                            force=args.force)
        print(f"[export] {n} 条 -> {export_path}；导出不代表已终审。")
        print("请由当前多模态 agent 打开 asset 图片逐条裁决，再用 --from-json 导入结果。")
        return 0

    try:
        if args.dry_run:
            vlm = None
        elif args.from_json:
            vlm = FileVLM(args.from_json)
        elif args.api:
            if not args.api_url or not args.api_model:
                ap.error("--api requires --api-url and --api-model")
            from .api import APIReviewer
            vlm = APIReviewer(args.output_root,args.api_url,args.api_model,args.max_requests,args.max_output_tokens)
    except (OSError, ValueError) as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    summary = run_review(Path(args.output_root), vlm=vlm,
                         force=args.force, dry_run=args.dry_run,
                         workers=args.workers)
    if args.dry_run:
        return 0
    return 1 if any(s["status"] == "still_open" for s in summary.values()) else 0


if __name__ == "__main__":
    sys.exit(main())

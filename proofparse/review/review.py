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
from .vlm import OpenAICompatVLM, VLMError


class FileVLM:
    """离线裁决后端：从 JSON 文件读取 agent 人工裁决结果。

    文件格式：{ "<uid>": {"choice": "parser|ocr|custom",
                          "corrected_latex": ...|null, "confidence": 0-1,
                          "reason": "..."} }
    uid 即 collect.ReviewItem.uid（--export 导出的清单里有）。
    """

    def __init__(self, path: Path):
        self.verdicts = json.loads(Path(path).read_text(encoding="utf-8"))

    def adjudicate(self, item, image_path, retries: int = 0) -> dict:
        v = self.verdicts.get(item.uid)
        if v is None:
            raise VLMError(f"verdicts 文件中缺少 {item.uid}")
        return {"choice": v["choice"], "corrected_latex": v.get("corrected_latex"),
                "confidence": float(v.get("confidence", 1.0)),
                "reason": str(v.get("reason", "")), "model": "agent"}


def export_worklist(output_root: Path, path: Path, force: bool = False) -> int:
    """导出待裁决清单（agent 裁决官模式）：看图后填 verdicts 再 --from-json 导回。"""
    items = collect(output_root, skip_done=not force)
    rows = [{
        "uid": it.uid, "kind": it.kind, "page": it.page,
        "asset": str(Path(it.paper) / it.review_asset) if it.review_asset else None,
        "likely_cause": it.likely_cause,
        "candidate_A_parser": it.candidate_a,
        "candidate_B": it.candidate_b,
    } for it in items]
    Path(path).write_text(json.dumps(rows, ensure_ascii=False, indent=2),
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
        vlm = OpenAICompatVLM()

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

        # 写回 qc.json
        qc = write_verdicts(paper_dir, results)

        # 应用确认的正确答案到 document.json，之后统一重建一次 md
        n_applied = n_confirmed = n_skipped = 0
        for it, verdict, error in results:
            if not verdict:
                n_skipped += 1
                continue
            r = apply_to_document(paper_dir, it, verdict)
            if r == "applied":
                n_applied += 1
            elif r == "confirmed":
                n_confirmed += 1
            else:
                n_skipped += 1
                log(f"    [skip] {it.kind} p{it.page}: {r}")
        if n_applied:
            md_path = rebuild_markdown(paper_dir)
            log(f"  已重建 {md_path.name}（应用 {n_applied} 处修正）")

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
    ap.add_argument("--base-url", help="覆盖 PROOFPARSE_VLM_BASE_URL")
    ap.add_argument("--api-key", help="覆盖 PROOFPARSE_VLM_API_KEY")
    ap.add_argument("--model", help="覆盖 PROOFPARSE_VLM_MODEL")
    ap.add_argument("-j", "--workers", type=int, default=4, help="并发裁决线程数")
    ap.add_argument("--export", metavar="WORKLIST.json",
                    help="导出待裁决清单后退出（agent 裁决官模式）")
    ap.add_argument("--from-json", metavar="VERDICTS.json",
                    help="从 JSON 文件读取裁决结果（agent 人工裁决），不调用外部模型")
    args = ap.parse_args(argv)

    if args.export:
        n = export_worklist(Path(args.output_root), Path(args.export),
                            force=args.force)
        print(f"[export] {n} 条 -> {args.export}")
        return 0

    try:
        if args.dry_run:
            vlm = None
        elif args.from_json:
            vlm = FileVLM(args.from_json)
        else:
            vlm = OpenAICompatVLM(
                base_url=args.base_url, api_key=args.api_key, model=args.model)
    except VLMError as e:
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

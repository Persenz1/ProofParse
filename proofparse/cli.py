"""Command line. Every command is resumable; `status` always says what to run next.

    proofparse run PDF_OR_DIR... -o OUT      parse (resumes unfinished stages)
    proofparse run --resume OUT              continue an existing output directory
    proofparse status OUT [--json]           progress, blocking items and the next command
    proofparse tasks export OUT [-o FILE]    unresolved items for the controlling agent
    proofparse tasks import OUT ANSWERS      validate and apply the agent's answers
    proofparse tasks api OUT                 answer unresolved items with the configured API
    proofparse export OUT -o DELIVERY        Markdown + images per paper
    proofparse engines                       registered engines and configured interpreters
    proofparse gold build ARXIV_ROOT         build formula gold data from LaTeX sources
    proofparse bench formula GOLD_ROOT -e A,B   score formula engines on the gold set
    proofparse bench inline GOLD_ROOT        score text-layer inline-math detection
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config as config_mod
from . import engines, pipeline
from .ir import read_json
from .stages import assemble, escalate


def _pdfs(inputs: list[str]) -> list[Path]:
    found = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            found += sorted(path.glob("*.pdf"))
        elif path.is_file():
            found.append(path)
        else:
            raise FileNotFoundError(raw)
    if not found:
        raise FileNotFoundError("no PDF found in the given inputs")
    return found


def _status(out: Path, cfg) -> dict:
    papers = pipeline.load_papers(out)
    rows, blocking_total, incomplete = [], 0, False
    for p in papers:
        done = [s for s in pipeline.STAGES if p.done(s)]
        blocked = len(assemble.blocking(p.doc)) if p.done("reconcile") else None
        failed = (p.dir / "error.log").is_file() and len(done) < len(pipeline.STAGES)
        incomplete |= len(done) < len(pipeline.STAGES)
        blocking_total += blocked or 0
        rows.append({"paper": p.key, "stages_done": done, "blocking": blocked, "failed": failed})
    if incomplete:
        nxt = f"proofparse run --resume {out}"
    elif blocking_total and cfg.escalation == "agent":
        nxt = f"proofparse tasks export {out}  (then answer the tasks and: proofparse tasks import {out} ANSWERS.json)"
    elif blocking_total and cfg.escalation == "api":
        nxt = f"proofparse tasks api {out}"
    elif blocking_total:
        nxt = f"escalation is disabled; deliver with: proofparse export {out} -o DELIVERY --allow-unresolved"
    else:
        nxt = f"proofparse export {out} -o DELIVERY"
    return {"papers": rows, "blocking": blocking_total, "escalation": cfg.escalation, "next": nxt}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="proofparse", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, help="config.toml (default: see proofparse/config.py)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run")
    p.add_argument("inputs", nargs="*")
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("--resume", type=Path, metavar="OUT")
    p.add_argument("--stages", help=f"comma list from {','.join(pipeline.STAGES)}")
    p.add_argument("-f", "--force", action="store_true", help="re-run selected stages even if done")

    p = sub.add_parser("status")
    p.add_argument("output", type=Path)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("tasks")
    p.add_argument("action", choices=["export", "import", "api"])
    p.add_argument("output", type=Path)
    p.add_argument("answers", nargs="?", type=Path)
    p.add_argument("-o", "--out-file", type=Path)

    p = sub.add_parser("export")
    p.add_argument("output", type=Path)
    p.add_argument("-o", "--delivery", type=Path, required=True)
    p.add_argument("--allow-unresolved", action="store_true")

    sub.add_parser("engines")

    p = sub.add_parser("gold")
    p.add_argument("action", choices=["build"])
    p.add_argument("root", type=Path)
    p.add_argument("--only", nargs="*")

    p = sub.add_parser("bench")
    p.add_argument("kind", choices=["formula", "inline"])
    p.add_argument("root", type=Path)
    p.add_argument("-e", "--engines", default="")
    p.add_argument("--kinds", default="display,inline")
    p.add_argument("--limit", type=int)
    p.add_argument("--render-compare", action="store_true", help="also compare canonical TeX rendering")

    args = ap.parse_args(argv)
    cfg = config_mod.load(args.config)

    if args.cmd == "run":
        if args.resume:
            out = args.resume
            papers = pipeline.load_papers(out)
        else:
            if not args.output or not args.inputs:
                ap.error("run needs inputs and -o OUT, or --resume OUT")
            out = args.output
            papers = pipeline.open_papers(_pdfs(args.inputs), out)
        stages = tuple(args.stages.split(",")) if args.stages else pipeline.STAGES
        failed = pipeline.run(papers, cfg, out / "_work", stages=stages, force=args.force)
        status = _status(out, cfg)
        print(json.dumps({"failed": failed, "blocking": status["blocking"], "next": status["next"]},
                         ensure_ascii=False, indent=1))
        return 2 if failed else 0

    if args.cmd == "status":
        status = _status(args.output, cfg)
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=1))
        else:
            for row in status["papers"]:
                print(f"{row['paper']}: {len(row['stages_done'])}/{len(pipeline.STAGES)} stages, "
                      f"blocking {row['blocking'] if row['blocking'] is not None else '-'}"
                      + ("  FAILED (see error.log)" if row["failed"] else ""))
            print(f"next: {status['next']}")
        return 0

    if args.cmd == "tasks":
        papers = pipeline.load_papers(args.output)
        if args.action == "export":
            path = args.out_file or args.output / "tasks.json"
            n = escalate.export_tasks(papers, path)
            print(f"{n} tasks -> {path}")
        elif args.action == "import":
            if not args.answers:
                ap.error("tasks import needs ANSWERS.json")
            result = escalate.apply_answers(papers, read_json(args.answers))
            _reassemble(papers)
            print(json.dumps(result, ensure_ascii=False, indent=1))
        else:
            result = escalate.resolve_with_api(papers, cfg, args.output / "_work")
            _reassemble(papers)
            print(json.dumps({k: v for k, v in result.items() if k != "errors"} | {"n_errors": len(result["errors"])},
                             ensure_ascii=False, indent=1))
        print(f"next: {_status(args.output, cfg)['next']}")
        return 0

    if args.cmd == "export":
        code = 0
        for paper in pipeline.load_papers(args.output):
            try:
                md = assemble.export(paper, args.delivery, allow_unresolved=args.allow_unresolved)
                print(f"[ok] {md}")
            except ValueError as exc:
                print(f"[blocked] {exc}", file=sys.stderr)
                code = 2
        return code

    if args.cmd == "engines":
        print(f"config: {cfg.path or '(none; defaults)'}  layout={cfg.layout}  formula={cfg.formula}  "
              f"fallback={cfg.formula_fallback}  "
              f"escalation={cfg.escalation}")
        for name, spec in sorted(engines.REGISTRY.items()):
            print(f"  {name:24} tasks={','.join(sorted(spec.tasks)):12} python={cfg.engine(name).python}")
        return 0

    if args.cmd == "gold":
        from .gold.arxiv import build_all
        results = build_all(args.root, only=args.only)
        bad = [r for r in results if r["status"] != "ok"]
        for r in bad:
            print(f"[{r['status']}] {r['paper']}: {r.get('reason')}", file=sys.stderr)
        return 0 if not bad else 2

    if args.cmd == "bench":
        from .eval import bench
        if args.kind == "formula":
            names = [n for n in args.engines.split(",") if n]
            if not names:
                ap.error("bench formula needs -e ENGINE[,ENGINE...]")
            bench.bench_formula(args.root, cfg, names, kinds=tuple(args.kinds.split(",")), limit=args.limit,
                                render_compare=args.render_compare)
        else:
            bench.bench_inline(args.root)
        return 0
    return 1


def _reassemble(papers) -> None:
    for paper in papers:
        assemble.write_working(paper)
        paper.save()


if __name__ == "__main__":
    sys.exit(main())

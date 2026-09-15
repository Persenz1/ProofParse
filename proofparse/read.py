"""Small, portable reading interface; never loads images into an agent automatically."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path, help="Paper directory or exported worklist JSON")
    ap.add_argument("--page", type=int, help="Zero-based source page")
    ap.add_argument("--block", help="Stable block ID")
    ap.add_argument("--kind", help="Worklist kind filter")
    ap.add_argument("--paper", help="Worklist paper directory name filter")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--render", type=Path, help="Render the selected source page/crop to this PNG")
    ap.add_argument("--crop", type=float, nargs=4, help="Visible-page bbox x1 y1 x2 y2, 0..1000")
    ap.add_argument("--scale", type=float, default=3)
    args = ap.parse_args(argv)
    if args.path.is_file():
        data = json.loads(args.path.read_text(encoding="utf-8"))
        items = data["items"]
        if args.kind: items = [x for x in items if x["kind"] == args.kind]
        if args.paper: items = [x for x in items if x["uid"].split("::")[0] == args.paper]
        if args.page is not None: items = [x for x in items if x["page"] == args.page]
        result = {"total":len(items),"items":items[args.offset:args.offset+args.limit]}
    else:
        data = json.loads((args.path / "document.json").read_text(encoding="utf-8"))
        if args.render:
            if args.page is None: ap.error("--render requires --page")
            from .pdf.render import render_crop, render_page
            source = args.path / data["source_pdf"]
            if args.crop: render_crop(source,args.page,args.crop,args.render,scale=args.scale)
            else: render_page(source,args.page,args.render,scale=args.scale)
            result = {"image":str(args.render.resolve())}
        elif args.block:
            result = next((b for b in data["blocks"] if b["block_id"] == args.block),None)
        elif args.page is not None:
            result = [b for b in data["blocks"] if b["page"] == args.page]
        else:
            result = {"metadata":data["metadata"],"pages":len({b["page"] for b in data["blocks"]}),
                      "contents":[{"block_id":b["block_id"],"page":b["page"],"type":b["type"],
                                   "label":b.get("extra",{}).get("caption") or b["content"][:160]}
                                  for b in data["blocks"] if b["type"] in ("title","heading","figure","table")]}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())

"""Download the planned ProofParse candidates without loading any model.

Uses Hugging Face's existing cache and automatic download resumption.
Run with --list to print the selection without accessing the network.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# key, official repository, revision checked on 2026-10-02, approximate GB
MODELS = (
    ("xiaomi", "SeerRay-Lab/Xiaomi-OCR-0",
     "e4d1c4a6804bd9ef342b93d705a73af003e2ef4e", 1.77),
    ("paddle-vl", "PaddlePaddle/PaddleOCR-VL-1.6",
     "c5630abae1d940eafe0697512a0325494b02ab42", 1.93),
    ("ovis", "ATH-MaaS/OvisOCR2",
     "1fc9221b7823a371d6e97f92d527cc847e24e107", 1.73),
    ("doclayout-v3", "PaddlePaddle/PP-DocLayoutV3",
     "241f8bdfc77a7c7bee915a5057aaee58c235a8d3", 0.132),
    ("teleocr", "XingChen-AGI/TeleOCR",
     "e92585356c0d0b7b7a65938f3da035c6593cc9a6", 2.85),
    ("mineru-pro", "opendatalab/MinerU2.5-Pro-2604-1.2B",
     "d3f5e08d073c21466bbabe21c71bb1e9c2e595da", 2.33),
    ("glm", "zai-org/GLM-OCR",
     "2e85a62840ccac27daa451df36c736c4636b8628", 2.66),
)
DEFAULT_CACHE = r"D:\DevTools\Models\huggingface\hub"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=("all", "first-batch"), default="all",
                        help="all seven candidates, or the first six without GLM")
    parser.add_argument("--models", nargs="+", choices=[m[0] for m in MODELS],
                        help="download only these candidates; overrides --group")
    parser.add_argument("--cache-dir", type=Path, default=Path(DEFAULT_CACHE),
                        help="shared Hugging Face cache directory")
    parser.add_argument("--workers", type=int, default=2,
                        help="parallel files within each model (default: 2)")
    parser.add_argument("--list", action="store_true",
                        help="list the selected models and exit; no network or writes")
    args = parser.parse_args(argv)

    if args.models:
        selected = [m for m in MODELS if m[0] in args.models]
    else:
        selected = list(MODELS if args.group == "all" else MODELS[:-1])
    cache_dir = args.cache_dir.expanduser().resolve()
    print(f"Cache: {cache_dir}", flush=True)
    for key, repo, _, gb in selected:
        print(f"  {key:<14} {gb:5.2f} GB  {repo}", flush=True)
    print(f"Selected: {len(selected)} models, approximately "
          f"{sum(m[3] for m in selected):.1f} GB (excluding environments).", flush=True)
    if args.list:
        return 0

    # Set before importing the Hub client; users can override these in their shell.
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Missing huggingface_hub. Install it in the selected Python environment:\n"
              f'  "{sys.executable}" -m pip install huggingface_hub', file=sys.stderr)
        return 1

    completed = []
    failed = []
    try:
        for index, (key, repo, revision, _) in enumerate(selected, 1):
            print(f"\n[{index}/{len(selected)}] {repo}", flush=True)
            try:
                path = snapshot_download(
                    repo_id=repo,
                    revision=revision,
                    cache_dir=str(cache_dir),
                    ignore_patterns=["assets/*", "example_pics/*", ".eval_results/*"],
                    max_workers=args.workers,
                    etag_timeout=30,
                    token=False,  # These repositories are public; no login is needed.
                )
            except Exception as exc:
                print(f"FAILED {key}: {exc}", file=sys.stderr, flush=True)
                failed.append(key)
                continue
            print(f"Ready: {path}", flush=True)
            completed.append((key, path))
    except KeyboardInterrupt:
        print("\nInterrupted. Keep the cache and rerun the same command to resume.",
              file=sys.stderr)
        return 130

    print(f"\nFinished: {len(completed)} ready, {len(failed)} failed.", flush=True)
    for key, path in completed:
        print(f"  {key}: {path}", flush=True)
    if failed:
        print("Rerun the same command to reuse downloaded files and retry failures.\n"
              "Failed selections: " + " ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

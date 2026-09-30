"""Worker entry point, executed inside an engine's own Python environment:

    python -m proofparse.engines.worker JOB.json

Reads the job, imports the adapter module, writes RESULT.json next to the job.
Only the standard library is imported here; the adapter brings its own deps.
"""
from __future__ import annotations

import importlib
import json
import os
import platform
import sys
import time
import traceback
from pathlib import Path


def _peak_vram_mb() -> float | None:
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            if torch.cuda.is_available():
                return round(torch.cuda.max_memory_allocated() / 1024**2, 1)
        except Exception:
            pass
    paddle = sys.modules.get("paddle")
    if paddle is not None:
        try:
            return round(paddle.device.cuda.max_memory_allocated() / 1024**2, 1)
        except Exception:
            pass
    return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    job_path = Path(argv[0])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    result_path = job_path.with_name("result.json")
    started = time.perf_counter()
    report = {"engine": job["engine"], "task": job["task"], "python": sys.executable,
              "platform": platform.platform(), "n_items": len(job["items"])}
    try:
        adapter = importlib.import_module(job["module"])
        outputs = adapter.run(job)
        missing = [item["id"] for item in job["items"] if item["id"] not in outputs]
        if missing:
            raise RuntimeError(f"adapter returned no output for {len(missing)} items, e.g. {missing[:3]}")
        report.update(status="ok", outputs=outputs, info=getattr(adapter, "INFO", {}))
        code = 0
    except Exception as exc:  # reported to the main process, never swallowed
        report.update(status="error", error=f"{type(exc).__name__}: {exc}",
                      traceback=traceback.format_exc())
        code = 1
    report["seconds"] = round(time.perf_counter() - started, 3)
    report["peak_vram_mb"] = _peak_vram_mb()
    tmp = result_path.with_name(result_path.name + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, result_path)
    return code


if __name__ == "__main__":
    sys.exit(main())

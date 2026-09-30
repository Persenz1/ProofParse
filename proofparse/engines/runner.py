"""Run one engine over a batch of items in a separate process.

One call = one model load. Stages collect items across every paper first and
call the runner once per engine, so models are never swapped per item. The
worker runs in the engine's configured interpreter, which isolates CUDA
frameworks (Paddle vs PyTorch) and frees VRAM when the process exits.

Outputs are cached by (engine, task, options, item content). Re-running a
stage after an interruption or on unchanged evidence costs nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .. import engines
from ..config import Config
from ..ir import read_json, write_json

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_FILE_FIELDS = ("image", "pdf")


class EngineError(RuntimeError):
    pass


@dataclass
class RunInfo:
    engine: str
    task: str
    n_items: int
    n_cached: int
    seconds: float = 0.0
    peak_vram_mb: float | None = None
    job_dir: str | None = None


def _file_digest(path: str, _cache: dict[str, str] = {}) -> str:
    stat = os.stat(path)
    key = f"{path}:{stat.st_mtime_ns}:{stat.st_size}"
    if key not in _cache:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _cache[key] = h.hexdigest()
    return _cache[key]


def item_key(engine: str, task: str, options: dict, item: dict) -> str:
    content = {k: (_file_digest(v) if k in _FILE_FIELDS else v)
               for k, v in item.items() if k != "id"}
    raw = json.dumps([engine, task, options, content], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def run_engine(cfg: Config, name: str, task: str, items: list[dict], work: Path,
               *, use_cache: bool = True, log=print) -> tuple[dict[str, dict], RunInfo]:
    spec = engines.get(name)
    if task not in spec.tasks:
        raise EngineError(f"engine {name} does not provide task {task!r} ({sorted(spec.tasks)})")
    ecfg = cfg.engine(name)
    options = {**spec.defaults, **ecfg.options}
    items = [{k: (str(Path(v).resolve()) if k in _FILE_FIELDS else v) for k, v in item.items()}
             for item in items]
    if len({item["id"] for item in items}) != len(items):
        raise EngineError("item ids must be unique within one engine call")

    cache_dir = Path(work) / "cache" / name
    keys = {item["id"]: item_key(name, task, options, item) for item in items}
    outputs, todo = {}, []
    for item in items:
        path = cache_dir / f"{keys[item['id']]}.json"
        if use_cache and path.is_file():
            outputs[item["id"]] = read_json(path)
        else:
            todo.append(item)
    info = RunInfo(name, task, len(items), len(items) - len(todo))
    if not todo:
        return outputs, info

    job_dir = Path(work) / "jobs" / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}-{task}"
    job_dir.mkdir(parents=True, exist_ok=True)
    job = {"engine": name, "module": spec.module, "task": task, "items": todo,
           "options": options, "device": ecfg.device, "batch_size": ecfg.batch_size,
           "job_dir": str(job_dir.resolve())}
    write_json(job_dir / "job.json", job)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(_PACKAGE_ROOT), env.get("PYTHONPATH")]))
    env["PYTHONIOENCODING"] = "utf-8"
    log(f"[engine] {name}/{task}: {len(todo)} items ({info.n_cached} cached) via {ecfg.python}")
    with open(job_dir / "log.txt", "wb") as logfile:
        proc = subprocess.run([ecfg.python, "-m", "proofparse.engines.worker", str(job_dir / "job.json")],
                              stdout=logfile, stderr=subprocess.STDOUT, env=env)
    result_path = job_dir / "result.json"
    if not result_path.is_file():
        tail = (job_dir / "log.txt").read_text(encoding="utf-8", errors="replace")[-3000:]
        raise EngineError(f"{name} worker exited {proc.returncode} without a result:\n{tail}")
    result = read_json(result_path)
    if result.get("status") != "ok":
        raise EngineError(f"{name} failed: {result.get('error')}\n{result.get('traceback', '')[-3000:]}")
    for item in todo:
        output = result["outputs"][item["id"]]
        write_json(cache_dir / f"{keys[item['id']]}.json", output)
        outputs[item["id"]] = output
    info.seconds, info.peak_vram_mb, info.job_dir = result["seconds"], result.get("peak_vram_mb"), str(job_dir)
    return outputs, info

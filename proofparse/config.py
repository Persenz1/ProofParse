"""User configuration: which engines run, in which Python environment, and
where unresolved items go. Written once by the installer, read by every run.

Lookup order: $PROOFPARSE_CONFIG, ./proofparse.toml, then the per-user file
(%APPDATA%/proofparse/config.toml or ~/.config/proofparse/config.toml).
Without a file, engines run in the current interpreter and unresolved items
are exported for the controlling agent.
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ESCALATION_MODES = ("agent", "api", "none")


@dataclass
class EngineConfig:
    name: str
    python: str = sys.executable
    device: str = "auto"
    batch_size: int = 16
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApiConfig:
    base_url: str = ""
    model: str = ""
    key_env: str = "PROOFPARSE_API_KEY"
    concurrency: int = 4
    max_requests: int = 200
    max_output_tokens: int = 4096


@dataclass
class Config:
    path: Path | None = None
    layout: str = "mineru_pipeline"
    formula: list[str] = field(default_factory=lambda: ["mineru_pipeline", "pp_formulanet_plus_m"])
    engines: dict[str, EngineConfig] = field(default_factory=dict)
    escalation: str = "agent"
    api: ApiConfig = field(default_factory=ApiConfig)
    render_scale: float = 3.0

    def engine(self, name: str) -> EngineConfig:
        return self.engines.get(name) or EngineConfig(name=name)


def user_config_path() -> Path:
    base = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME")
    return Path(base or Path.home() / ".config") / "proofparse" / "config.toml"


def find_config() -> Path | None:
    for candidate in (os.environ.get("PROOFPARSE_CONFIG"), "proofparse.toml", user_config_path()):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def load(path: Path | None = None) -> Config:
    path = path or find_config()
    if path is None:
        return Config()
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    pipeline = data.get("pipeline", {})
    engines = {}
    for name, raw in data.get("engines", {}).items():
        raw = dict(raw)
        known = {k: raw.pop(k) for k in ("python", "device", "batch_size") if k in raw}
        engines[name] = EngineConfig(name=name, options=raw, **known)
    esc = data.get("escalation", {})
    mode = esc.get("mode", "agent")
    if mode not in ESCALATION_MODES:
        raise ValueError(f"{path}: escalation.mode must be one of {ESCALATION_MODES}, got {mode!r}")
    cfg = Config(path=Path(path), layout=pipeline.get("layout", "mineru_pipeline"),
                 formula=list(pipeline.get("formula", Config().formula)),
                 engines=engines, escalation=mode,
                 api=ApiConfig(**esc.get("api", {})),
                 render_scale=float(pipeline.get("render_scale", 3.0)))
    return cfg

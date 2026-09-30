"""Model engines. Each engine runs in its own worker process and Python
environment (see runner.py); the main process never imports model code.

An adapter module exposes ``run(job) -> dict[item_id, output]``. Tasks:

- page_parse: items are documents {id, pdf}; output {"pages": {...}, "regions": [...]}
  with bbox_pt on the displayed page, kind (ir kinds), order, and optional
  content/format. Used for whole-pipeline baselines such as MinerU.
- layout:     items are page images {id, image, scale}; output {"regions": [...]}.
- formula:    items are crops {id, image, kind}; output {"latex": str}.
- table:      items are crops {id, image}; output {"html": str}.

``families`` names the model lineage per output kind. Candidates from one
family are never counted as independent confirmation of each other.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EngineSpec:
    name: str
    module: str
    tasks: frozenset[str]
    families: dict[str, str]
    defaults: dict = field(default_factory=dict)


def _spec(name, module, tasks, families, **defaults):
    return EngineSpec(name, module, frozenset(tasks), families, defaults)


# Engines not listed here are candidates from docs/MODEL_SELECTION_PLAN; they get an
# adapter once they have run on the benchmark, not before.
REGISTRY: dict[str, EngineSpec] = {s.name: s for s in (
    # MinerU 3.4.5 pipeline: PP-DocLayoutV2 layout, UniMERNet-small formulas.
    _spec("mineru_pipeline", "proofparse.engines.mineru_pipeline", {"page_parse"},
          {"layout": "pp-doclayout", "formula": "unimernet", "text": "mineru-ocr",
           "table": "mineru-table"}),
    _spec("unimernet_small", "proofparse.engines.mineru_mfr", {"formula"},
          {"formula": "unimernet"}, model="unimernet_small"),
    _spec("pp_formulanet_plus_m", "proofparse.engines.mineru_mfr", {"formula"},
          {"formula": "pp-formulanet"}, model="pp_formulanet_plus_m"),
    # plus-L ships as a Paddle inference model; set options.model_dir in the config.
    _spec("pp_formulanet_plus_l", "proofparse.engines.mineru_mfr", {"formula"},
          {"formula": "pp-formulanet"}, model="pp_formulanet_plus_l", backend="paddle"),
)}


def get(name: str) -> EngineSpec:
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown engine {name!r}; known: {', '.join(sorted(REGISTRY))}") from None


def family(name: str, kind: str) -> str:
    spec = REGISTRY.get(name)
    return (spec.families.get(kind) if spec else None) or name

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


# Candidate adapters are registered for benchmarking; registration alone does
# not select an engine for the default extraction pipeline.
REGISTRY: dict[str, EngineSpec] = {s.name: s for s in (
    _spec("pp_doclayout_v3", "proofparse.engines.paddle_layout", {"layout"},
          {"layout": "pp-doclayout"}),
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
    # Xiaomi and Ovis share the Qwen3.5-0.8B backbone; treat their agreement
    # conservatively until measured error correlations justify independence.
    _spec("xiaomi_ocr", "proofparse.engines.hf_ocr", {"formula"},
          {"formula": "qwen3.5-ocr"}),
    _spec("ovis_ocr", "proofparse.engines.hf_ocr", {"formula"},
          {"formula": "qwen3.5-ocr"}),
    _spec("paddleocr_vl", "proofparse.engines.hf_ocr", {"formula"},
          {"formula": "paddleocr-vl"}),
)}


def get(name: str) -> EngineSpec:
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown engine {name!r}; known: {', '.join(sorted(REGISTRY))}") from None


def family(name: str, kind: str) -> str:
    spec = REGISTRY.get(name)
    return (spec.families.get(kind) if spec else None) or name

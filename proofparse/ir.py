"""Intermediate representation shared by every stage.

Coordinates are PDF points on the displayed page, origin top-left (the same
space PyMuPDF reports after applying page rotation). Adapters convert their
native coordinates at the boundary; nothing downstream sees 0..1000 or pixels.

Prose is taken from the PDF text layer whenever that layer is usable. Inline
math inside a text block is a child block; the parent text stores one
INLINE_SLOT character per child, in order, so writing math back never depends
on searching for a LaTeX string.
"""
from __future__ import annotations

import gzip
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1
INLINE_SLOT = "￼"  # stripped from source text before slots are inserted

# Block kinds
TITLE = "title"
HEADING = "heading"
TEXT = "text"
LIST = "list"
CODE = "code"
ALGORITHM = "algorithm"
DISPLAY_MATH = "display_math"
INLINE_MATH = "inline_math"
FIGURE = "figure"
TABLE = "table"
CAPTION = "caption"
FOOTNOTE = "footnote"
REFERENCE = "reference"
FURNITURE = "furniture"  # running header/footer, page number, publisher marks
OTHER = "other"

KINDS = {TITLE, HEADING, TEXT, LIST, CODE, ALGORITHM, DISPLAY_MATH, INLINE_MATH,
         FIGURE, TABLE, CAPTION, FOOTNOTE, REFERENCE, FURNITURE, OTHER}
PROSE_KINDS = {TITLE, HEADING, TEXT, LIST, CAPTION, FOOTNOTE, REFERENCE}
MATH_KINDS = {DISPLAY_MATH, INLINE_MATH}

# Decision states. Only ACCEPTED and RESOLVED count as finished.
ACCEPTED = "accepted"        # independent evidence agreed under a calibrated rule
RESOLVED = "resolved"        # an escalation (agent/API) answered and passed validation
CONFLICT = "conflict"        # candidates disagree or contradict source evidence
UNVERIFIED = "unverified"    # a single candidate with nothing independent to check it
FAILED = "failed"            # no usable candidate
FINAL_STATES = {ACCEPTED, RESOLVED}


@dataclass
class Candidate:
    engine: str
    family: str          # model lineage; candidates of one family are not independent
    content: str
    format: str = "latex"  # latex | text | html | markdown
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    status: str
    value: str | None = None
    rule: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    by: str = "program"  # program | agent | api:<model>


@dataclass
class Block:
    id: str
    page: int
    bbox: list[float]
    kind: str
    order: float = 0.0
    parent: str | None = None
    level: int = 0
    source: str = ""                 # who proposed this region
    text: str = ""                   # prose with INLINE_SLOT placeholders
    inline: list[str] = field(default_factory=list)  # child ids, one per slot
    candidates: list[Candidate] = field(default_factory=list)
    decision: Decision | None = None
    asset: str | None = None         # relative path of a cropped image
    links: dict[str, Any] = field(default_factory=dict)  # caption_of, number, ...
    extra: dict[str, Any] = field(default_factory=dict)

    def candidate(self, engine: str) -> Candidate | None:
        return next((c for c in self.candidates if c.engine == engine), None)

    def set_candidate(self, cand: Candidate) -> None:
        self.candidates = [c for c in self.candidates if c.engine != cand.engine] + [cand]


@dataclass
class Page:
    index: int
    width: float
    height: float
    rotation: int = 0
    text_layer: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    source: dict[str, Any] = field(default_factory=dict)   # path, sha256, n_pages
    pages: list[Page] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema: int = SCHEMA_VERSION

    # ---------------------------------------------------------------- access
    def block(self, block_id: str) -> Block:
        for b in self.blocks:
            if b.id == block_id:
                return b
        raise KeyError(block_id)

    def children(self, block: Block) -> list[Block]:
        index = {b.id: b for b in self.blocks}
        return [index[i] for i in block.inline if i in index]

    def on_page(self, page: int) -> Iterator[Block]:
        return (b for b in self.blocks if b.page == page)

    def reading_order(self) -> list[Block]:
        return sorted((b for b in self.blocks if b.parent is None),
                      key=lambda b: (b.page, b.order))

    # ---------------------------------------------------------------- io
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Document":
        if data.get("schema") != SCHEMA_VERSION:
            raise ValueError(f"unsupported document schema {data.get('schema')!r}; re-run the pipeline")
        blocks = []
        for b in data.get("blocks", []):
            b = dict(b)
            b["candidates"] = [Candidate(**c) for c in b.get("candidates", [])]
            b["decision"] = Decision(**b["decision"]) if b.get("decision") else None
            blocks.append(Block(**b))
        return cls(source=data.get("source", {}),
                   pages=[Page(**p) for p in data.get("pages", [])],
                   blocks=blocks, stages=data.get("stages", {}),
                   metadata=data.get("metadata", {}), schema=data["schema"])

    def save(self, path: Path) -> None:
        write_json(path, self.to_dict())

    @classmethod
    def load(cls, path: Path) -> "Document":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_json(path: Path, data: Any, *, compress: bool = False) -> None:
    """Atomic write so an interrupted stage never leaves a truncated file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    raw = json.dumps(data, ensure_ascii=False, indent=None if compress else 1).encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(gzip.compress(raw, mtime=0) if compress else raw)
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))

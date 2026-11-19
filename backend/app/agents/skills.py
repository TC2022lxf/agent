"""Skill parsing (docs/architecture/agent-runtime.md). A Skill is Markdown with front matter; the id is its directory.

`audience` decides which Agents may use it: `pdp`, `image` and `canvas` are specialist-only,
`general` is usable by the general entry (which also aggregates the specialists).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

AUDIENCES = ("general", "pdp", "image", "canvas", "any")

_AGENT_AUDIENCE = {"amazon_pdp": "pdp", "image": "image", "canvas": "canvas", "general": "general"}


@dataclass(frozen=True)
class Skill:
    id: str
    description: str
    body: str
    content_hash: str
    audience: str = "general"
    revision: int = 0
    source: str = "file"  # file | edited | restored

    def to_json(self, *, body: bool = False) -> dict[str, object]:
        out: dict[str, object] = {
            "id": self.id,
            "description": self.description,
            "hash": self.content_hash,
            "audience": self.audience,
            "revision": self.revision,
            "source": self.source,
        }
        if body:
            out["body"] = self.body
        return out


def parse_skill(skill_id: str, text: str) -> Skill:
    """Front matter is data: a missing description makes registration fail at the caller."""
    meta = _front_matter(text)
    audience = meta.get("audience", "general").strip() or "general"
    if audience not in AUDIENCES:
        raise ValueError(f"skill {skill_id}: audience must be one of {AUDIENCES}")
    return Skill(
        id=skill_id,
        description=meta.get("description", ""),
        body=text,
        content_hash=content_hash(text),
        audience=audience,
    )


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def agent_audience(agent_key: str) -> str:
    """Specialists may only use their own audience; general may use everything."""
    return _AGENT_AUDIENCE.get(agent_key, "general")


def _front_matter(text: str) -> dict[str, str]:
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}
    block = text.split("---", 2)[1]
    out: dict[str, str] = {}
    for line in block.strip().splitlines():
        if ":" in line and not line.startswith((" ", "\t", "|", ">")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out

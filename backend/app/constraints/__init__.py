"""Platform constraint packs (docs/architecture/data-and-contracts.md). Numbers live in JSON, not in code."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=4)
def load_pack(pack_id: str = "amazon_com") -> dict[str, Any]:
    path = Path(__file__).with_name(f"{pack_id}.json")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def platform_constraints(pack_id: str = "amazon_com") -> dict[str, Any]:
    """Read-only list shown to the user. Users cannot rewrite these (docs/architecture/data-and-contracts.md).
    `value` is the number a UI may use for counters ("169 / 200")."""
    p = load_pack(pack_id)
    mi = p["main_image"]
    rows: list[dict[str, Any]] = [
        {"key": "title_max_chars", "slot": "title", "value": p["title"]["max_chars"],
         "summary": f"标题不超过 {p['title']['max_chars']} 字符"},
        {"key": "bullets_count", "slot": "bullets", "value": p["bullets"]["count"],
         "summary": f"五点共 {p['bullets']['count']} 条，每条不超过 "
                    f"{p['bullets']['max_chars_each']} 字符"},
        {"key": "bullets_max_chars_each", "slot": "bullets",
         "value": p["bullets"]["max_chars_each"],
         "summary": f"五点每条不超过 {p['bullets']['max_chars_each']} 字符"},
        {"key": "description_max_chars", "slot": "description",
         "value": p["description"]["max_chars"],
         "summary": f"描述不超过 {p['description']['max_chars']} 字符"},
        {"key": "search_terms_max_bytes", "slot": "search_terms",
         "value": p["search_terms"]["max_bytes"],
         "summary": f"后台关键词不超过 {p['search_terms']['max_bytes']} 字节"},
        {"key": "main_image_white_background", "slot": "main_image",
         "value": mi["background_min_channel"],
         "summary": f"主图纯白背景（边缘像素 RGB ≥ {mi['background_min_channel']}）"},
        {"key": "main_image_min_size", "slot": "main_image", "value": mi["min_long_side_px"],
         "summary": f"主图长边不少于 {mi['min_long_side_px']} px"},
        {"key": "main_image_occupancy", "slot": "main_image", "value": mi["occupancy_min"],
         "summary": f"主体占画面不少于 {int(mi['occupancy_min'] * 100)}%"},
    ]
    for r in rows:
        r["hard"] = True
    return {"pack_id": p["id"], "version": p["version"], "note": p["note"], "items": rows}

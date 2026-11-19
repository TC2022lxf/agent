"""Starter boards for the canvas home (docs/architecture/system.md).

A template is a board that already has some finished pictures, each with the prompt that
would reproduce it, and a `ref` where one picture was made from another. The pictures
themselves are drawn when the template is opened; this module only describes the board.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PictureSpec:
    """One finished picture. Modules absent from this list stay as placeholders."""

    module_id: str
    prompt: str
    swatch: tuple[int, int, int]
    accent: tuple[int, int, int]


@dataclass(frozen=True)
class CanvasTemplate:
    id: str
    title: str
    blurb: str
    goal: str
    board: dict[str, Any]
    pictures: tuple[PictureSpec, ...]


def _image(
    mid: str, slot: str, name: str, prompt: str, rect: dict[str, float], ref: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": mid, "kind": "image", "name": name, "slot": slot, "prompt": prompt,
        "rect": rect, "style": {"fit": "cover", "background": "white"},
    }
    if ref:
        item["ref"] = ref
    return item


_MORNING = _image(
    "m-morning", "canvas_image_1", "晨光静物",
    "深色木桌上一杯拿铁，窗边晨光，方形静物，画面里不要文字",
    {"x": 0.04, "y": 0.06, "w": 0.44, "h": 0.56},
)
_NIGHT = _image(
    "m-night", "canvas_image_2", "夜景",
    "保持同一只杯子和同一张桌子，改成夜晚暖光，背景虚化，画面里不要文字",
    {"x": 0.52, "y": 0.06, "w": 0.44, "h": 0.56},
    ref="m-morning",
)
_TITLE = _image(
    "m-title", "canvas_image_3", "标题",
    "底部一行手写标题：Morning，浅色纸面",
    {"x": 0.04, "y": 0.68, "w": 0.92, "h": 0.26},
)

_CUP = _image(
    "m-cup", "canvas_image_1", "杯子正面",
    "一只白瓷杯的正面特写，浅灰背景，没有文字",
    {"x": 0.03, "y": 0.08, "w": 0.30, "h": 0.84},
)
_TOP = _image(
    "m-top", "canvas_image_2", "俯视",
    "同一只白瓷杯，改成俯视，桌面加一片柠檬，没有文字",
    {"x": 0.35, "y": 0.08, "w": 0.30, "h": 0.84},
    ref="m-cup",
)
_RING = _image(
    "m-ring", "canvas_image_3", "圆环",
    "抽象的青绿渐变底，正中一个细圆环，没有文字",
    {"x": 0.67, "y": 0.08, "w": 0.30, "h": 0.84},
)


def _board(width: int, height: int, name: str, modules: list[dict[str, Any]]) -> dict[str, Any]:
    from app.domain.canvas import DEFAULT_THEME

    return {
        "theme": {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()},
        "screens": [{
            "id": "s1", "name": name, "pos": {"x": 0, "y": 0},
            "frame": {"width": width, "height": height},
            "modules": modules,
        }],
        "edges": [],
    }


TEMPLATES: tuple[CanvasTemplate, ...] = (
    CanvasTemplate(
        id="morning-night",
        title="静物与夜景",
        blurb="晨光静物已经画好。夜景用它做参考，虚线连着两张。底部标题还是待生成。",
        goal="静物与夜景",
        board=_board(1280, 900, "静物与夜景", [_MORNING, _NIGHT, _TITLE]),
        pictures=(
            PictureSpec("m-morning", _MORNING["prompt"], (232, 214, 186), (92, 58, 38)),
            PictureSpec("m-night", _NIGHT["prompt"], (28, 36, 64), (214, 148, 72)),
        ),
    ),
    CanvasTemplate(
        id="three-frames",
        title="三张相关画面",
        blurb="三张都已画好。中间那张以左边的杯子为参考，右边是独立的一张。每张都能看到提示词。",
        goal="三张相关画面",
        board=_board(1600, 720, "三张画面", [_CUP, _TOP, _RING]),
        pictures=(
            PictureSpec("m-cup", _CUP["prompt"], (226, 226, 222), (244, 244, 240)),
            PictureSpec("m-top", _TOP["prompt"], (210, 196, 168), (232, 214, 86)),
            PictureSpec("m-ring", _RING["prompt"], (46, 122, 110), (232, 244, 236)),
        ),
    ),
)

_BY_ID = {t.id: t for t in TEMPLATES}


def list_templates() -> list[dict[str, str]]:
    return [{"id": t.id, "title": t.title, "blurb": t.blurb, "goal": t.goal} for t in TEMPLATES]


def get_template(template_id: str) -> CanvasTemplate:
    try:
        return _BY_ID[template_id]
    except KeyError:
        raise KeyError(template_id) from None

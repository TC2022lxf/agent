"""Canvas board (decisions/0029). Pure functions: no database, no store, no model.

A canvas is a BOARD, modelled on Stitch: several screens laid out on an infinite surface,
each screen a frame with modules, plus edges that describe a clickable flow. One board is one
Version, so keeping this version keeps the whole composition.

    { "theme":  {colors, fonts, radius},
      "screens": [{id, name, pos: {x, y}, frame: {width, height}, modules: [...]}],
      "edges":   [{from, to, label}] }

A module's `rect` is a fraction of ITS screen, so a screen resize never rewrites modules.
Image modules name a slot (`canvas_image_N`) and the Version's manifest maps module id to the
image Version. Text colours and fonts are theme tokens, never raw hex: that is what makes a
theme enforceable instead of decorative.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain import slots as slot_registry

MODULE_KINDS = ("text", "image")
ALIGNS = ("left", "center", "right")
MAX_MODULES = 24
MAX_SCREENS = 12
# A fresh board is a blank sheet: 1280 wide (the size Stitch previews a design at). Nothing
# here knows what the page is for — Amazon, a landing page, a poster — that comes from the
# user's sentence, not from a default (decisions/0031).
DEFAULT_SCREEN_WIDTH = 1280
MIN_SCREEN_HEIGHT = 120
MAX_FRAME_SIDE = 4000
MAX_TEXT_CHARS = 2000
MAX_EDGES = 24
SCREEN_GAP = 96  # world px between two screens placed automatically

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

DEFAULT_THEME: dict[str, Any] = {
    "colors": {
        "bg": "#FFFFFF", "fg": "#0D0D0D", "accent": "#10A37F", "muted": "#6E6E6E",
    },
    "fonts": {
        "display": "Georgia, 'Times New Roman', serif",
        "body": "Inter, system-ui, sans-serif",
    },
    "radius": 12,
}


class CanvasError(ValueError):
    """A board or an op list the canvas cannot accept. The message is shown to the user."""


def empty_board(height: int = 720) -> dict[str, Any]:
    """A fresh board: one blank screen, nothing else.

    Deliberately empty of placeholder copy. It used to ship a "首屏标题" headline and a
    "产品主图" picture slot, which the model then treated as the brief and produced an Amazon
    product card whatever the user asked for. A blank screen forces the content to come from
    the user's sentence (decisions/0031).
    """
    return {
        "theme": {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()},
        "screens": [
            {
                "id": "s1", "name": "画板 1", "pos": {"x": 0, "y": 0},
                "frame": {"width": DEFAULT_SCREEN_WIDTH, "height": height},
                "modules": [],
            },
        ],
        "edges": [],
    }


def board_for_picture(prompt: str, height: int = 720) -> dict[str, Any]:
    """A board holding one picture: the picture request IS the design (decisions/0031).

    This is what a canvas is for. The screen carries one image module whose prompt is the
    user's sentence, so the board can show a placeholder immediately and the picture lands in
    it when the generator returns.
    """
    text = prompt.strip()[:MAX_TEXT_CHARS]
    return {
        "theme": {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()},
        "screens": [
            {
                "id": "s1", "name": text[:40] or "画板 1", "pos": {"x": 0, "y": 0},
                "frame": {"width": DEFAULT_SCREEN_WIDTH, "height": height},
                "modules": [
                    {
                        "id": "m1", "kind": "image", "name": "画面",
                        "slot": "canvas_image_1", "prompt": text,
                        "rect": {"x": 0.04, "y": 0.06, "w": 0.92, "h": 0.88},
                        "style": {"fit": "contain", "background": "white"},
                    },
                ],
            },
        ],
        "edges": [],
    }


def validate_board(content: dict[str, Any]) -> dict[str, Any]:
    """Normalize a board, or raise CanvasError with a sentence for the user."""
    if not isinstance(content, dict):
        raise CanvasError("画布正文必须是对象")
    body = upgrade(content)
    theme = _theme(body.get("theme"))
    raw_screens = body.get("screens")
    if not isinstance(raw_screens, list) or not raw_screens:
        raise CanvasError("画布至少要有一屏")
    if len(raw_screens) > MAX_SCREENS:
        raise CanvasError(f"画布最多 {MAX_SCREENS} 屏")

    screens: list[dict[str, Any]] = []
    screen_ids: set[str] = set()
    module_ids: set[str] = set()
    for raw in raw_screens:
        s = _screen(raw, theme)
        if s["id"] in screen_ids:
            raise CanvasError(f"屏 id 重复：{s['id']}")
        screen_ids.add(s["id"])
        for m in s["modules"]:
            if m["id"] in module_ids:
                raise CanvasError(f"模块 id 在整块画布上必须唯一：{m['id']}")
            module_ids.add(m["id"])
        screens.append(s)
    _check_refs(screens)
    return {"theme": theme, "screens": screens, "edges": _edges(body.get("edges"), screen_ids)}


def upgrade(content: dict[str, Any]) -> dict[str, Any]:
    """Read a single-page board written before the canvas became a board (one screen)."""
    if isinstance(content, dict) and "screens" not in content and "modules" in content:
        return {
            "theme": content.get("theme") or DEFAULT_THEME,
            "screens": [{
                "id": "s1", "name": "首屏", "pos": {"x": 0, "y": 0},
                "frame": content.get("frame") or {"width": DEFAULT_SCREEN_WIDTH, "height": 600},
                "modules": content.get("modules") or [],
            }],
            "edges": [],
        }
    return content


def _theme(raw: Any) -> dict[str, Any]:
    theme: dict[str, Any] = {
        k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THEME.items()
    }
    if raw is None:
        return theme
    if not isinstance(raw, dict):
        raise CanvasError("theme 必须是对象")
    colors = raw.get("colors")
    if colors is not None:
        if not isinstance(colors, dict) or not colors:
            raise CanvasError("theme.colors 必须是非空对象")
        out: dict[str, str] = {}
        for name, value in colors.items():
            if not isinstance(name, str) or not re.match(r"^[a-z][a-z0-9_-]{0,23}$", name):
                raise CanvasError(f"颜色名不合法：{name}")
            if not isinstance(value, str) or not _HEX.match(value):
                raise CanvasError(f"颜色 {name} 必须是 #RRGGBB")
            out[name] = value.upper()
        if "bg" not in out or "fg" not in out:
            raise CanvasError("theme.colors 至少要包含 bg 与 fg")
        theme["colors"] = out
    fonts = raw.get("fonts")
    if fonts is not None:
        if not isinstance(fonts, dict) or not fonts:
            raise CanvasError("theme.fonts 必须是非空对象")
        fout: dict[str, str] = {}
        for name, value in fonts.items():
            if not isinstance(name, str) or not re.match(r"^[a-z][a-z0-9_-]{0,23}$", name):
                raise CanvasError(f"字体名不合法：{name}")
            if not isinstance(value, str) or not value.strip() or len(value) > 120:
                raise CanvasError(f"字体 {name} 必须是字体栈字符串")
            fout[name] = value.strip()
        theme["fonts"] = fout
    radius = raw.get("radius", theme["radius"])
    if not isinstance(radius, int) or isinstance(radius, bool) or not 0 <= radius <= 64:
        raise CanvasError("theme.radius 必须是 0 到 64 的整数")
    theme["radius"] = radius
    return theme


def _screen(raw: Any, theme: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CanvasError("每一屏必须是对象")
    sid = raw.get("id")
    if not isinstance(sid, str) or not sid.strip() or len(sid) > 32:
        raise CanvasError("屏 id 必填，最多 32 个字符")
    frame = raw.get("frame")
    if not isinstance(frame, dict):
        raise CanvasError(f"屏 {sid} 缺少 frame")
    width, height = frame.get("width"), frame.get("height")
    for name, value, lo in (("width", width, 1), ("height", height, MIN_SCREEN_HEIGHT)):
        ok = isinstance(value, int) and not isinstance(value, bool)
        if not ok or not lo <= value <= MAX_FRAME_SIDE:  # type: ignore[operator]
            raise CanvasError(f"屏 {sid} 的 frame.{name} 必须是 {lo} 到 {MAX_FRAME_SIDE} 的整数")
    pos = raw.get("pos")
    px, py = (0, 0)
    if isinstance(pos, dict):
        x, y = pos.get("x", 0), pos.get("y", 0)
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise CanvasError(f"屏 {sid} 的 pos 必须是数字")
        px, py = round(float(x)), round(float(y))

    raw_modules = raw.get("modules")
    # A blank screen is legal: a board may hold empty frames while the user works out what
    # goes on them. `delete_module` still refuses to empty a screen that had content.
    if not isinstance(raw_modules, list):
        raise CanvasError(f"屏 {sid} 的 modules 必须是数组")
    if len(raw_modules) > MAX_MODULES:
        raise CanvasError(f"每屏最多 {MAX_MODULES} 个模块")
    modules = [_module(m, theme, sid) for m in raw_modules]

    out: dict[str, Any] = {
        "id": sid,
        "name": str(raw.get("name") or "")[:60],
        "pos": {"x": px, "y": py},
        "frame": {"width": width, "height": height},
        "modules": modules,
    }
    variant_of = raw.get("variant_of")
    if isinstance(variant_of, str) and variant_of.strip():
        out["variant_of"] = variant_of[:32]
    label = raw.get("variant_label")
    if isinstance(label, str) and label.strip():
        out["variant_label"] = label[:40]
    return out


def _module(raw: Any, theme: dict[str, Any], screen_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CanvasError("模块必须是对象")
    mid = raw.get("id")
    if not isinstance(mid, str) or not mid.strip() or len(mid) > 32:
        raise CanvasError("模块 id 必填，最多 32 个字符")
    kind = raw.get("kind")
    if kind not in MODULE_KINDS:
        raise CanvasError(f"模块 kind 只能是 {', '.join(MODULE_KINDS)}")
    rect = _rect(raw.get("rect"))
    name = str(raw.get("name") or "")[:60]
    style_raw = raw.get("style")
    style: dict[str, Any] = style_raw if isinstance(style_raw, dict) else {}
    if kind == "text":
        text = raw.get("text")
        if not isinstance(text, str):
            raise CanvasError(f"模块 {mid} 是文字模块，缺少 text")
        if len(text) > MAX_TEXT_CHARS:
            raise CanvasError(f"模块 {mid} 的文字超过 {MAX_TEXT_CHARS} 字")
        return {
            "id": mid, "kind": "text", "name": name, "rect": rect,
            "style": _text_style(style, theme, mid), "text": text,
        }
    slot = raw.get("slot")
    if not isinstance(slot, str) or slot_registry.canvas_module_index(slot) is None:
        raise CanvasError(f"模块 {mid} 的图像槽位必须是 canvas_image_N")
    item: dict[str, Any] = {
        "id": mid, "kind": "image", "name": name, "rect": rect,
        "style": _image_style(style), "slot": slot,
    }
    # The prompt that produced the picture belongs to the board, not only to a Tool call:
    # an external agent reading the canvas must be able to see it (decisions/0030).
    prompt = raw.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        if len(prompt) > MAX_TEXT_CHARS:
            raise CanvasError(f"模块 {mid} 的提示词超过 {MAX_TEXT_CHARS} 字")
        item["prompt"] = prompt.strip()
    # `ref` names another image module whose picture was the reference. Screen `edges` stay
    # the clickable flow; this is a different relationship (decisions/0034).
    ref = raw.get("ref")
    if isinstance(ref, str) and ref.strip():
        if len(ref.strip()) > 32:
            raise CanvasError(f"模块 {mid} 的参考图 id 太长")
        item["ref"] = ref.strip()
    return item


def _rect(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise CanvasError("模块缺少 rect")
    vals: dict[str, float] = {}
    for k, lo, hi in (("x", 0.0, 1.0), ("y", 0.0, 1.0), ("w", 0.01, 1.0), ("h", 0.01, 1.0)):
        v = raw.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise CanvasError(f"rect.{k} 必须是数字")
        f = round(float(v), 6)
        if not lo <= f <= hi:
            raise CanvasError(f"rect.{k} 必须在 {lo} 到 {hi} 之间")
        vals[k] = f
    if vals["x"] + vals["w"] > 1.000001 or vals["y"] + vals["h"] > 1.000001:
        raise CanvasError("模块超出这一屏的范围")
    return vals


def _text_style(raw: dict[str, Any], theme: dict[str, Any], mid: str) -> dict[str, Any]:
    size = raw.get("size", 24)
    if not isinstance(size, (int, float)) or isinstance(size, bool) or not 8 <= size <= 200:
        raise CanvasError("字号必须在 8 到 200 之间")
    weight = raw.get("weight", 400)
    if weight not in (400, 500, 600, 700):
        raise CanvasError("字重只能是 400、500、600 或 700")
    align = raw.get("align", "left")
    if align not in ALIGNS:
        raise CanvasError(f"对齐只能是 {', '.join(ALIGNS)}")
    color = raw.get("color", "fg")
    if not isinstance(color, str) or color not in theme["colors"]:
        names = ", ".join(sorted(theme["colors"]))
        raise CanvasError(f"模块 {mid} 的文字颜色必须是主题令牌（{names}），不能是随手写的颜色")
    font = raw.get("font", "body")
    if not isinstance(font, str) or font not in theme["fonts"]:
        names = ", ".join(sorted(theme["fonts"]))
        raise CanvasError(f"模块 {mid} 的字体必须是主题令牌（{names}）")
    return {"size": int(size), "weight": weight, "align": align, "color": color, "font": font}


def _check_refs(screens: list[dict[str, Any]]) -> None:
    """A picture's `ref` must name another picture on this board, never itself."""
    image_ids = {
        m["id"] for s in screens for m in s["modules"] if m.get("kind") == "image"
    }
    for s in screens:
        for m in s["modules"]:
            ref = m.get("ref")
            if not ref:
                continue
            if ref == m["id"] or ref not in image_ids:
                raise CanvasError(f"模块 {m['id']} 的参考图必须是画布上另一张图片")


def _clear_refs(screens: list[dict[str, Any]], gone: set[str]) -> None:
    """Drop reference links that pointed at a module which just left the board."""
    if not gone:
        return
    for s in screens:
        for m in s["modules"]:
            if m.get("ref") in gone:
                m.pop("ref", None)


def reference_of(
    content: dict[str, Any],
    manifest: dict[str, str],
    version_content: Any,
    *,
    reference_object_key: str | None,
    base_version_id: str | None,
    self_id: str,
) -> str | None:
    """Which other picture on this board a new image was made from, if any.

    `version_content(version_id)` returns that Version's content, or None. A base that is
    this module's own previous picture is an edit of itself, not a reference line.
    """
    body = upgrade(content)
    image_ids = {
        m["id"]
        for s in body.get("screens", [])
        for m in s.get("modules", [])
        if m.get("kind") == "image"
    }

    def owner(version_id: str) -> str | None:
        for module_id, pointed in manifest.items():
            if pointed == version_id and module_id != self_id and module_id in image_ids:
                return module_id
        return None

    if isinstance(base_version_id, str) and base_version_id:
        hit = owner(base_version_id)
        if hit:
            return hit
    if isinstance(reference_object_key, str) and reference_object_key:
        for module_id, pointed in manifest.items():
            if module_id == self_id or module_id not in image_ids:
                continue
            content_of = version_content(pointed)
            if isinstance(content_of, dict) and content_of.get("object_key") == reference_object_key:
                return module_id
    return None


def _image_style(raw: dict[str, Any]) -> dict[str, Any]:
    fit = raw.get("fit", "contain")
    if fit not in ("contain", "cover"):
        raise CanvasError("图片填充只能是 contain 或 cover")
    background = raw.get("background", "white")
    if background not in ("white", "transparent"):
        raise CanvasError("图片底色只能是 white 或 transparent")
    return {"fit": fit, "background": background}


def _edges(raw: Any, screen_ids: set[str]) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CanvasError("edges 必须是数组")
    if len(raw) > MAX_EDGES:
        raise CanvasError(f"最多 {MAX_EDGES} 条连线")
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for e in raw:
        if not isinstance(e, dict):
            raise CanvasError("每条连线必须是对象")
        a, b = e.get("from"), e.get("to")
        if not isinstance(a, str) or not isinstance(b, str):
            raise CanvasError("连线缺少 from / to")
        if a not in screen_ids or b not in screen_ids:
            raise CanvasError(f"连线指向不存在的屏：{a} → {b}")
        if a == b:
            raise CanvasError("连线不能连到自己")
        if (a, b) in seen:
            continue
        seen.add((a, b))
        label = e.get("label")
        out.append({
            "from": a, "to": b,
            "label": label[:40] if isinstance(label, str) else "",
        })
    return out


def apply_ops(content: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply a user's gesture batch. Returns a new board; the input is untouched.

    Every op is `{op, ...}`. Module ops name their `screen`; screen ops name `id`.
    Fractions stay fractions, so the same drag means the same thing at any zoom.
    """
    body = validate_board(content)
    theme: dict[str, Any] = {
        k: (dict(v) if isinstance(v, dict) else v) for k, v in body["theme"].items()
    }
    screens = [dict(s) for s in body["screens"]]
    edges = [dict(e) for e in body["edges"]]
    by_id = {s["id"]: s for s in screens}

    for op in ops:
        if not isinstance(op, dict):
            raise CanvasError("每个改动必须是对象")
        name = op.get("op")
        if name == "set_theme":
            patch = op.get("theme")
            merged: dict[str, Any] = {**theme, **(patch if isinstance(patch, dict) else {})}
            theme = _theme(merged)
            for s in screens:
                for m in s["modules"]:
                    if m["kind"] == "text":
                        m["style"] = _text_style(m["style"], theme, m["id"])
            continue
        if name == "move_screen":
            s = _screen_by_id(by_id, op)
            s["pos"] = {
                "x": round(s["pos"]["x"] + _number(op.get("dx")), 0),
                "y": round(s["pos"]["y"] + _number(op.get("dy")), 0),
            }
            continue
        if name == "rename_screen":
            s = _screen_by_id(by_id, op)
            text = op.get("name")
            if not isinstance(text, str) or not text.strip() or len(text) > 60:
                raise CanvasError("屏名不能为空，最多 60 字")
            s["name"] = text.strip()
            continue
        if name == "resize_screen":
            s = _screen_by_id(by_id, op)
            h = op.get("height")
            if not isinstance(h, int) or isinstance(h, bool):
                raise CanvasError(f"屏高必须是 {MIN_SCREEN_HEIGHT} 到 {MAX_FRAME_SIDE} 的整数")
            if not MIN_SCREEN_HEIGHT <= h <= MAX_FRAME_SIDE:
                raise CanvasError(f"屏高必须是 {MIN_SCREEN_HEIGHT} 到 {MAX_FRAME_SIDE} 的整数")
            s["frame"] = {"width": s["frame"]["width"], "height": h}
            continue
        if name == "add_screen":
            if len(screens) >= MAX_SCREENS:
                raise CanvasError(f"画布最多 {MAX_SCREENS} 屏")
            raw = op.get("screen")
            if not isinstance(raw, dict):
                raise CanvasError("新增一屏缺少 screen")
            candidate = dict(raw)
            candidate.setdefault("id", _next_screen_id(by_id))
            if candidate["id"] in by_id:
                raise CanvasError(f"屏 id 已存在：{candidate['id']}")
            if "pos" not in candidate:
                candidate["pos"] = _free_spot(screens)
            s = _screen(candidate, theme)
            screens.append(s)
            by_id[s["id"]] = s
            continue
        if name == "delete_screen":
            s = _screen_by_id(by_id, op)
            if len(screens) == 1:
                raise CanvasError("画布至少要保留一屏")
            gone = {m["id"] for m in s["modules"]}
            screens.remove(s)
            del by_id[s["id"]]
            edges = [e for e in edges if e["from"] != s["id"] and e["to"] != s["id"]]
            _clear_refs(screens, gone)
            continue
        if name == "keep_variant":
            s = _screen_by_id(by_id, op)
            group = s.get("variant_of") or s["id"]
            siblings = [
                x for x in screens
                if x is not s and (x.get("variant_of") or x["id"]) == group
            ]
            if not siblings:
                raise CanvasError("这一屏没有同组的变体")
            # Converge on this one. Its content moves onto the ORIGINAL screen so the screen id
            # stays stable and edges pointing at it keep working; only then the copies go.
            # Reversible like every other change: the previous Version still opens.
            root = next(
                (x for x in screens if x["id"] == group and x is not s),
                None,
            )
            if root is not None:
                root["frame"] = dict(s["frame"])
                root["modules"] = [
                    {k: (dict(v) if isinstance(v, dict) else v) for k, v in m.items()}
                    for m in s["modules"]
                ]
                root["name"] = s.get("name") or root["name"]
                kept = root
            else:
                kept = s
            for x in [s, *siblings]:
                if x is not kept:
                    screens.remove(x)
                    if x["id"] in by_id:
                        del by_id[x["id"]]
                    edges = [e for e in edges if e["from"] != x["id"] and e["to"] != x["id"]]
            kept.pop("variant_of", None)
            kept.pop("variant_label", None)
            continue
        if name in ("link_screens", "unlink_screens"):
            a, b = op.get("from"), op.get("to")
            if not isinstance(a, str) or not isinstance(b, str) or a not in by_id or b not in by_id:
                raise CanvasError("连线必须指向已有的两屏")
            if a == b:
                raise CanvasError("连线不能连到自己")
            if name == "unlink_screens":
                edges = [e for e in edges if not (e["from"] == a and e["to"] == b)]
            elif not any(e["from"] == a and e["to"] == b for e in edges):
                if len(edges) >= MAX_EDGES:
                    raise CanvasError(f"最多 {MAX_EDGES} 条连线")
                label = op.get("label")
                edges.append({
                    "from": a, "to": b,
                    "label": label[:40] if isinstance(label, str) else "",
                })
            continue
        _module_op(name, op, by_id, theme)

    board = {"theme": theme, "screens": screens, "edges": edges}
    return validate_board(board)


def _module_op(
    name: Any, op: dict[str, Any], by_id: dict[str, dict[str, Any]], theme: dict[str, Any],
) -> None:
    if name not in {
        "move_module", "resize_module", "set_text", "set_style", "set_prompt",
        "add_module", "delete_module",
    }:
        raise CanvasError(f"不认识的改动：{name}")
    s = _module_screen(by_id, op)
    if name == "add_module":
        if len(s["modules"]) >= MAX_MODULES:
            raise CanvasError(f"每屏最多 {MAX_MODULES} 个模块")
        raw = op.get("module")
        if not isinstance(raw, dict):
            raise CanvasError("新增模块缺少 module")
        candidate = dict(raw)
        candidate.setdefault("id", _next_module_id(by_id))
        if any(m["id"] == candidate["id"] for x in by_id.values() for m in x["modules"]):
            raise CanvasError(f"模块 id 已存在：{candidate['id']}")
        s["modules"].append(_module(candidate, theme, s["id"]))
        return
    mid = op.get("id")
    target = next((m for m in s["modules"] if m["id"] == mid), None)
    if target is None:
        raise CanvasError(f"这一屏没有模块：{mid}")
    if name == "move_module":
        dx, dy = _number(op.get("dx")), _number(op.get("dy"))
        rect = target["rect"]
        target["rect"] = _clamp(
            {"x": rect["x"] + dx, "y": rect["y"] + dy, "w": rect["w"], "h": rect["h"]}
        )
    elif name == "resize_module":
        target["rect"] = _clamp(_rect(op.get("rect")))
    elif name == "set_text":
        if target["kind"] != "text":
            raise CanvasError(f"模块 {mid} 不是文字模块")
        text = op.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise CanvasError("文字为空或过长")
        target["text"] = text
    elif name == "set_prompt":
        if target["kind"] != "image":
            raise CanvasError(f"模块 {mid} 不是图片模块，没有提示词")
        prompt = op.get("prompt")
        if prompt is not None and not isinstance(prompt, str):
            raise CanvasError("提示词必须是字符串")
        if isinstance(prompt, str) and len(prompt) > MAX_TEXT_CHARS:
            raise CanvasError("提示词过长")
        if isinstance(prompt, str) and prompt.strip():
            target["prompt"] = prompt.strip()
        else:
            target.pop("prompt", None)
    elif name == "set_style":
        style = op.get("style")
        if not isinstance(style, dict):
            raise CanvasError("style 必须是对象")
        if target["kind"] == "text":
            target["style"] = _text_style({**target["style"], **style}, theme, target["id"])
        else:
            # A picture has no colour or font of its own. Silently ignoring those keys made an
            # external agent believe it had changed something, so say it instead (0031).
            wrong = sorted(set(style) - {"fit", "background"})
            if wrong:
                raise CanvasError(
                    f"模块 {mid} 是图片模块，只能改 fit 与 background；"
                    f"颜色和字体属于文字模块（收到 {', '.join(wrong)}）"
                )
            target["style"] = _image_style({**target["style"], **style})
    elif name == "delete_module":
        if len(s["modules"]) == 1:
            raise CanvasError("一屏至少要保留一个模块")
        s["modules"] = [m for m in s["modules"] if m["id"] != mid]
        _clear_refs(list(by_id.values()), {str(mid)})


def _screen_by_id(by_id: dict[str, dict[str, Any]], op: dict[str, Any]) -> dict[str, Any]:
    """Screen ops name the screen in `id`."""
    sid = op.get("id")
    if not isinstance(sid, str) or sid not in by_id:
        raise CanvasError(f"没有这一屏：{sid}")
    return by_id[sid]


def _module_screen(by_id: dict[str, dict[str, Any]], op: dict[str, Any]) -> dict[str, Any]:
    """Module ops name their screen in `screen`, or only the module: ids are unique board-wide."""
    raw = op.get("screen")
    if isinstance(raw, str):
        if raw not in by_id:
            raise CanvasError(f"没有这一屏：{raw}")
        return by_id[raw]
    mid = op.get("id")
    if isinstance(mid, str):
        for s in by_id.values():
            if any(m.get("id") == mid for m in s["modules"]):
                return s
        raise CanvasError(f"没有这个模块：{mid}")
    raise CanvasError("改动缺少 screen")


def _number(value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise CanvasError("位移必须是数字")
    return float(value)


def _clamp(rect: dict[str, float]) -> dict[str, float]:
    """Keep a dragged or resized module inside its screen instead of rejecting the gesture."""
    w = min(rect["w"], 1.0)
    h = min(rect["h"], 1.0)
    x = min(max(rect["x"], 0.0), 1.0 - w)
    y = min(max(rect["y"], 0.0), 1.0 - h)
    return {"x": round(x, 6), "y": round(y, 6), "w": round(w, 6), "h": round(h, 6)}


def _next_screen_id(by_id: dict[str, dict[str, Any]]) -> str:
    n = len(by_id) + 1
    while f"s{n}" in by_id:
        n += 1
    return f"s{n}"


def _next_module_id(by_id: dict[str, dict[str, Any]]) -> str:
    used = {m["id"] for s in by_id.values() for m in s["modules"]}
    n = len(used) + 1
    while f"m{n}" in used:
        n += 1
    return f"m{n}"


def _free_spot(screens: list[dict[str, Any]]) -> dict[str, int]:
    right = max((s["pos"]["x"] + s["frame"]["width"] for s in screens), default=0)
    top = min((s["pos"]["y"] for s in screens), default=0)
    return {"x": int(right + SCREEN_GAP), "y": int(top)}


def variants_of(content: dict[str, Any], screen_id: str, count: int) -> list[dict[str, Any]]:
    """Copy a screen N times, side by side, tagged as variants of it (Stitch's explore).

    Pure scaffolding: the copies are identical until someone edits them. The Agent edits each
    copy with `compose_canvas`; the user keeps one with the `keep_variant` op.
    """
    body = validate_board(content)
    src = next((s for s in body["screens"] if s["id"] == screen_id), None)
    if src is None:
        raise CanvasError(f"没有这一屏：{screen_id}")
    if not 2 <= count <= 4:
        raise CanvasError("变体数量是 2 到 4 个")
    used_screens = {s["id"] for s in body["screens"]}
    used_modules = {m["id"] for s in body["screens"] for m in s["modules"]}
    out: list[dict[str, Any]] = []
    x = src["pos"]["x"] + src["frame"]["width"] + SCREEN_GAP
    for i in range(count):
        sid = f"{screen_id}-v{i + 1}"
        while sid in used_screens:
            sid += "x"
        used_screens.add(sid)
        modules: list[dict[str, Any]] = []
        id_map: dict[str, str] = {}
        for m in src["modules"]:
            copy: dict[str, Any] = {
                k: (dict(v) if isinstance(v, dict) else v) for k, v in m.items()
            }
            new_id = f"{sid}-{m['id']}"
            while new_id in used_modules:
                new_id += "x"
            id_map[m["id"]] = new_id
            copy["id"] = new_id
            used_modules.add(new_id)
            modules.append(copy)
        # A reference that lived on this screen follows its copy. One that lived elsewhere
        # still points at the original picture.
        for copy in modules:
            pointed = copy.get("ref")
            if isinstance(pointed, str) and pointed in id_map:
                copy["ref"] = id_map[pointed]
        out.append({
            "id": sid, "name": f"{src.get('name') or src['id']} · 变体 {i + 1}",
            "pos": {"x": int(x + i * (src["frame"]["width"] + SCREEN_GAP)), "y": src["pos"]["y"]},
            "frame": dict(src["frame"]), "modules": modules,
            "variant_of": src["id"], "variant_label": f"变体 {i + 1}",
        })
    return out


def module_slots(content: dict[str, Any]) -> list[str]:
    """The image slots this board refers to, in order."""
    body = upgrade(content)
    return [
        m["slot"]
        for s in body.get("screens", [])
        for m in s.get("modules", [])
        if m.get("kind") == "image" and isinstance(m.get("slot"), str)
    ]


def manifest_for(content: dict[str, Any], pointers: dict[str, str]) -> dict[str, str]:
    """Only image modules get a pointer; a text module needs no separate Version."""
    body = upgrade(content)
    out: dict[str, str] = {}
    for s in body.get("screens", []):
        for m in s.get("modules", []):
            if m.get("kind") != "image":
                continue
            vid = pointers.get(m["id"]) or pointers.get(m.get("slot") or "")
            if vid:
                out[m["id"]] = vid
    return out


def find_module(content: dict[str, Any], module_id: str) -> dict[str, Any] | None:
    for s in upgrade(content).get("screens", []):
        for m in s.get("modules", []):
            if m.get("id") == module_id:
                found: dict[str, Any] = m
                return found
    return None


def screen_of_module(content: dict[str, Any], module_id: str) -> dict[str, Any] | None:
    for s in upgrade(content).get("screens", []):
        if any(m.get("id") == module_id for m in s.get("modules", [])):
            found: dict[str, Any] = s
            return found
    return None


def board_bounds(content: dict[str, Any]) -> dict[str, int]:
    body = upgrade(content)
    screens = body.get("screens") or []
    if not screens:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    def left(s: dict[str, Any]) -> int:
        return int((s.get("pos") or {}).get("x") or 0)

    def top(s: dict[str, Any]) -> int:
        return int((s.get("pos") or {}).get("y") or 0)

    x0 = min(left(s) for s in screens)
    y0 = min(top(s) for s in screens)
    right = max(left(s) + s["frame"]["width"] for s in screens)
    bottom = max(top(s) + s["frame"]["height"] for s in screens)
    return {"x": x0, "y": y0, "width": int(right - x0), "height": int(bottom - y0)}
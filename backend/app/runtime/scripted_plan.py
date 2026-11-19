"""Deterministic tool choice for the offline gateway.

The production loop asks the model. FakeGateway answers with this function so the
same graph, guards and commits run in tests without a network call.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.domain import canvas as canvas_domain
from app.domain import slots as slot_registry

_VAGUE_WORDS = ("高级一点", "高级感", "太普通", "不够好", "好看一点", "有质感")

# A rule outlives this output. These words say so even next to a production verb, and a
# numeric limit ("不要超过 20 个字符") is a rule when the sentence is not asking for output.
_STANDING_WORDS = ("以后", "每次", "始终", "永远", "不许", "规则", "上限", "不能改")
_LIMIT_WORDS = ("不要超过", "不得超过", "不能超过")
_PRODUCE_WORDS = (
    "做一张", "生成", "画一", "画个", "画张", "出图", "配图", "生图",
    "写一", "写个", "写份", "制作", "帮我做", "来一张", "再来", "改成", "换成",
)
# "Leave X alone" clauses protect another slot from THIS edit; they never state a rule.
_PROTECT_WORDS = (
    "不要动", "不要改", "别动", "别改", "保持不变", "保持不动", "不动", "其他不变",
    "其它不变", "其余不变", "不用动", "不要碰", "别碰", "原样",
)
_PREFERENCE_WORDS = ("我喜欢", "我偏好", "以后都", "i prefer")


def _rule_clause(sentence: str, client_hint: str = "") -> dict[str, Any] | None:
    """The `record_constraint` call this sentence asks for, or None.

    Offline stand-in for the judgement a real model makes: the sentence states something that
    must keep holding, rather than describing the output being asked for.
    """
    if any(w in sentence for w in _PROTECT_WORDS):
        return None
    scope = "user"
    is_preference = client_hint == "preference" or any(
        w in sentence.lower() for w in _PREFERENCE_WORDS
    )
    if not is_preference:
        scope = "task"
        wants_output = any(w in sentence for w in _PRODUCE_WORDS)
        standing = any(w in sentence for w in _STANDING_WORDS)
        limited = any(w in sentence for w in _LIMIT_WORDS)
        if not standing and not (limited and not wants_output):
            return None
    args: dict[str, Any] = {"text": sentence, "scope": scope}
    if scope == "task":
        m = re.search(r"(\d+)\s*(个)?字符", sentence)
        if m:
            slot = _pdp_slot_in(sentence)
            args["rule"] = {"type": "max_chars", "value": int(m.group(1))}
            if slot:
                args["rule"]["slot"] = slot
    return {"name": "record_constraint", "id": "record_constraint", "args": args}



def _ask_question_plan(question: str, options: list[str], path_note: str = "ask") -> dict[str, Any]:
    return {
        "content": "",
        "tool_calls": [{
            "name": "ask_question",
            "id": "ask_question",
            "args": {"question": question, "options": options[:3]},
        }],
        "path_note": path_note,
        "declined": "",
    }


def scripted_plan(item: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    """Route one sentence: clauses that state a rule are recorded, the rest are executed.

    This is the offline stand-in for what a real model does with several tool calls in one
    reply. Splitting at clause boundaries is the piece the old `interpret` call used to own;
    the difference is that it now produces tool calls instead of labels, and a clause that is
    neither a clear rule nor ignorable still becomes work rather than being dropped.
    """
    text = str(item.get("text") or "")
    hint = str(view.get("client_hint") or "")
    clauses = [c.strip() for c in re.split(r"[;；。\n]", text) if c.strip()]
    rules = [r for r in (_rule_clause(c, hint) for c in clauses) if r is not None]
    if not rules:
        return _patch_plan(item, view)
    rest = [c for c in clauses if _rule_clause(c, hint) is None]
    if not rest:
        return {
            "content": "已记下这条规则，你确认后才会对后面的修改生效。",
            "tool_calls": rules,
            "path_note": "constraint",
            "declined": "",
        }
    # A rule AND a request in one sentence: record the rule first, then do the work.
    patch = _patch_plan({**item, "text": "；".join(rest)}, view)
    return {**patch, "tool_calls": [*rules, *patch["tool_calls"]]}


def _is_rule_only(text: str, item: dict[str, Any]) -> bool:
    """Does the sentence ask for a rule and nothing else?

    A rule with a production verb ("以后每次标题都控制在 20 字，顺便把这一版也改短") does
    both. A bare limit ("标题不要超过 20 个字符") only records the rule: it must not silently
    rewrite the title, because an unconfirmed rule is not in force yet.

    The sentence may hold both in separate clauses ("…；标题更突出防水"), so the question is
    asked of each clause rather than of the whole string.
    """
    clauses = [c.strip() for c in re.split(r"[;；。\n]", text) if c.strip()]
    return not any(any(w in c for w in _PRODUCE_WORDS) for c in clauses)


def _patch_plan(item: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text") or "")
    if any(w in text for w in _VAGUE_WORDS):
        return _ask_question_plan(
            "想朝哪个方向改？选一个我就按这个做。",
            ["更突出核心卖点，语气克制", "更有场景感，语气有力"],
            "ask_style",
        )
    current: dict[str, Any] = view.get("current") or {}
    kind = str(view.get("kind") or "")
    if kind == "file":
        return _file_plan(item, view)
    if kind == "canvas":
        return _canvas_plan(item, view)
    if kind == "general":
        return _general_plan(item, view)
    slot = item.get("slot")
    targets: list[str]
    path_note = ""
    text_slots = list(slot_registry.text_slots_for_task_kind("pdp"))
    if slot:
        targets = [str(slot)]
    elif kind == "pdp" and _pdp_slot_in(text):
        # The sentence names its own slot ("把副图都换掉"). With the interpret call gone, the
        # stand-in has to read that here, the way the model reads it before choosing a tool.
        targets = [_pdp_slot_in(text) or ""]
    elif kind == "pdp":
        empty = [s for s in text_slots if s not in current]
        if empty and (len(empty) == len(text_slots) or view.get("resume")):
            targets = empty
            if len(empty) == len(text_slots):
                path_note = "first_draft"
        else:
            targets = [s for s in slot_registry.slots_for_task_kind(kind)][:1]
    else:
        targets = [s for s in slot_registry.slots_for_task_kind(kind)][:1]

    calls: list[dict[str, Any]] = []
    declined = ""
    for target in targets:
        if target in slot_registry.GALLERY_SLOT_KEYS:
            declined = f"{target}: 副图的编辑后期开放，目前只展示导入的内容"
            continue
        calls.append(_call(target, item, view))
    return {"content": declined, "tool_calls": calls, "path_note": path_note, "declined": declined}


def _call(slot: str, item: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    current: dict[str, Any] = view.get("current") or {}
    override = item.get("base_override") if item.get("slot") == slot else None
    base = override or current.get(slot)
    if slot in slot_registry.IMAGE_SLOT_KEYS:
        # "重新生成" is the option offered after a rejection: a fresh draft, not an edit.
        text = str(item.get("text") or "")
        if any(w in text for w in _REGENERATE_WORDS):
            base = None
        if base is None:
            return {
                "name": "generate_product_image",
                "id": f"generate_product_image:{slot}",
                "args": {"slot": slot, "prompt": text or view.get("goal") or ""},
            }
        region = item.get("region")
        args: dict[str, Any] = {
            "slot": slot,
            "base_version_id": base["version_id"],
            "base_object_key": base["content"]["object_key"],
            "patch": {
                "operation": item.get("operation") or "free",
                "instruction": item.get("text") or "",
            },
        }
        if region:
            args["region"] = region
        return {"name": "edit_product_image", "id": f"edit_product_image:{slot}", "args": args}

    rules = view.get("user_rules") or []
    max_chars = next(
        (
            int(r["value"])
            for r in rules
            if r.get("type") == "max_chars" and r.get("slot") == slot
        ),
        None,
    )
    args = {
        "slot": slot,
        "goal": view.get("goal") or "",
        "instruction": (item.get("text") or "") if base else "",
        "facts": view.get("facts") or {},
    }
    if base:
        args["base_version_id"] = base["version_id"]
        args["base"] = base["content"]
    if max_chars is not None:
        args["max_chars"] = max_chars
    return {"name": "edit_listing", "id": f"edit_listing:{slot}", "args": args}


def _canvas_plan(item: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    """Offline stand-in for the canvas: draw the first picture, a variant, or one module changed.

    A canvas exists to make pictures (docs/architecture/data-and-contracts.md). A first sentence is a picture request:
    the board gets one screen with one image module whose prompt is that sentence, and the
    picture is drawn in the same turn, so a placeholder appears and is then filled.
    """
    current: dict[str, Any] = view.get("current") or {}
    text = str(item.get("text") or view.get("goal") or "")
    canvas = current.get("canvas")
    base = canvas["content"] if isinstance(canvas, dict) else None
    base_id = str(canvas.get("version_id") or "") if isinstance(canvas, dict) else ""
    if base is None:
        body = canvas_domain.board_for_picture(text)
        module = body["screens"][0]["modules"][0]
        return {
            "content": "",
            "tool_calls": [
                {
                    "name": "compose_canvas",
                    "id": "compose_canvas:canvas",
                    "args": {"content": body},
                },
                {
                    "name": "generate_product_image",
                    "id": f"generate_product_image:{module['slot']}",
                    "args": {"slot": module["slot"], "prompt": text},
                },
            ],
            "path_note": "canvas_picture",
            "declined": "",
        }
    body = json.loads(json.dumps(base))  # deep copy: the stand-in must not mutate the view
    screens = body.get("screens") or []
    if not screens:
        return _ask_question_plan(
            "画布是空的，要从哪开始？",
            ["画一张海报", "先做一个空白的移动端页面"],
            "canvas_ask",
        )
    if any(w in text for w in _VARIANT_WORDS):
        return {
            "content": "",
            "tool_calls": [{
                "name": "generate_variants",
                "id": "generate_variants:canvas",
                "args": {"screen_id": screens[0]["id"], "count": 3, "base_version_id": base_id},
            }],
            "path_note": "canvas_variants",
            "declined": "",
        }
    screen = screens[0]
    modules = screen.get("modules") or []
    target = _canvas_module_in(text, modules)
    if target is None:
        names = [str(m.get("name")) for m in modules if m.get("name")][:3]
        return _ask_question_plan("要改哪一块模块？", names, "canvas_ask")
    if any(w in text for w in ("删", "去掉", "移除")) and len(modules) > 1:
        screen["modules"] = [m for m in modules if m["id"] != target["id"]]
    elif isinstance(target, dict) and target.get("kind") == "text":
        target["text"] = (target.get("text", "") + " " + text)[:200]
    else:
        return _canvas_image_call(item, view, target, base)
    return {
        "content": "",
        "tool_calls": [{
            "name": "compose_canvas",
            "id": "compose_canvas:canvas",
            "args": {"content": body, "base_version_id": base_id},
        }],
        "path_note": "canvas_edit",
        "declined": "",
    }


def _canvas_image_call(
    item: dict[str, Any], view: dict[str, Any], module: dict[str, Any], base: dict[str, Any],
) -> dict[str, Any]:
    """A picture module wants a new picture: image tool first, the page next time."""
    slot = str(module.get("slot") or "")
    current: dict[str, Any] = view.get("current") or {}
    picture = current.get(slot)
    text = str(item.get("text") or "")
    args: dict[str, Any] = {"slot": slot, "prompt": text or "画布模块配图"}
    name = "generate_product_image"
    if isinstance(picture, dict):
        name = "edit_product_image"
        args = {
            "slot": slot,
            "base_version_id": picture["version_id"],
            "base_object_key": picture["content"]["object_key"],
            "patch": {"operation": "free", "instruction": text},
        }
    return {
        "content": "",
        "tool_calls": [{"name": name, "id": f"{name}:{slot}", "args": args}],
        "path_note": "canvas_image",
        "declined": "",
    }


def _canvas_module_in(text: str, modules: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The module the sentence names, by its own name or by position words."""
    s = text.lower()
    for m in modules:
        name = str(m.get("name") or "")
        if name and name in text:
            return m
    if any(w in s for w in ("图", "照片", "picture", "image")):
        for m in modules:
            if m.get("kind") == "image":
                return m
    if any(w in s for w in ("标题", "headline", "文案", "文字")):
        for m in modules:
            if m.get("kind") == "text":
                return m
    return None


def _file_plan(item: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    current: dict[str, Any] = view.get("current") or {}
    text = str(item.get("text") or view.get("goal") or "")
    asked = item.get("slot")
    guessed = _guess_file(text)
    if isinstance(asked, str) and (asked in current or slot_registry.is_file_slot(asked)):
        name = asked
    elif _names_a_type(text) or guessed in current or len(current) != 1:
        name = guessed
    else:
        name = next(iter(current))
    base = current.get(name)
    body = _draft(name, text, base if isinstance(base, dict) else None)
    return {
        "content": "",
        "tool_calls": [{
            "name": "write_file",
            "id": f"write_file:{name}",
            "args": {"path": name, "content": body},
        }],
        "path_note": "file_draft",
        "declined": "",
    }


_REGENERATE_WORDS = ("重新生成", "重做", "再生成一版", "重新画", "重抽")
_TYPE_WORDS = ("html", "markdown", ".md", "csv", "tsv", "表格", "网页", "页面", "活动")
_IMAGE_WORDS = ("生成图片", "画一张", "出图", "配图", "生图", "架构图", "示意图", "海报")
# "A+", "首屏", "画布", "版式"… the offline stand-in sends these to the canvas planner.
_CANVAS_WORDS = ("a+", "canvas", "首屏", "画布", "版式", "模块排", "banner")
# Ask for options rather than one answer: the board gains side-by-side copies.
_VARIANT_WORDS = (
    "几个方案", "三种", "三个版本", "变体", "不同风格", "备选", "几个方向", "多出几版",
)
_PDP_WORDS = ("pdp", "详情页", "listing", "标题", "五点", "卖点", "描述", "关键词")
_PDP_SLOT_WORDS = {
    "title": ("标题", "title"),
    "bullets": ("五点", "卖点", "bullet"),
    "description": ("描述", "description"),
    "search_terms": ("关键词", "search term"),
    "main_image": ("主图", "main image"),
    # A gallery slot is shown but not editable: the planner must decline it, not write a title.
    "secondary_image": ("副图", "secondary image", "gallery"),
}


_WEB_SEARCH_WORDS = (
    "联网", "查一下", "搜一下", "搜索一下", "网上搜", "网页搜索", "web search", "帮我搜", "搜一搜",
)
_WEB_FETCH_WORDS = ("抓取网页", "打开这个链接", "读取这个网页", "fetch this")
_URL_IN_TEXT = re.compile(r"https?://[^\s)>\"]+")


def _web_plan(text: str) -> dict[str, Any] | None:
    """Offline stand-in for a lookup. A search does not write a file."""
    if any(w in text.lower() for w in _WEB_FETCH_WORDS):
        found = _URL_IN_TEXT.search(text)
        if found:
            return {
                "content": "",
                "tool_calls": [{
                    "name": "web_fetch",
                    "id": "web_fetch",
                    "args": {"url": found.group(0)},
                }],
                "path_note": "web_fetch",
                "declined": "",
            }
    if any(w in text.lower() for w in _WEB_SEARCH_WORDS):
        query = text.strip()[:128]
        return {
            "content": "",
            "tool_calls": [{
                "name": "web_search",
                "id": "web_search",
                "args": {"query": query, "count": 5, "ori_question": query},
            }],
            "path_note": "web_search",
            "declined": "",
        }
    return None


def _general_plan(item: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    """One conversation, several artifact kinds: pick the tool from what was asked.

    `current` holds every slot this Task already has, so a second picture becomes an edit of
    the first and a second revision of a PDP slot updates that slot only.
    """
    current: dict[str, Any] = view.get("current") or {}
    text = str(item.get("text") or view.get("goal") or "")
    looked_up = _web_plan(text)
    if looked_up is not None:
        return looked_up
    pdp_slot = _pdp_slot_in(text)
    asked = item.get("slot")
    # A canvas sentence wins over the file guess: "做一版 A+ 首屏" is not a markdown note.
    if asked == slot_registry.CANVAS_SLOT or (
        not isinstance(asked, str) and any(w in text.lower() for w in _CANVAS_WORDS)
    ):
        return _canvas_plan(item, view)
    # "重新生成" is the option offered after a rejection: a fresh draft, never an edit of the
    # rejected version. Checked before `asked in current` so the base is not supplied.
    regenerate = any(w in text for w in _REGENERATE_WORDS)
    if isinstance(asked, str) and asked in current and not regenerate:
        return _call_for(asked, text, current[asked])
    if isinstance(asked, str) and regenerate and asked in slot_registry.IMAGE_SLOT_KEYS:
        return _image_call(asked, text, None)
    if pdp_slot:
        return _call_for(pdp_slot, text, current.get(pdp_slot))
    if regenerate and "image" in slot_registry.IMAGE_SLOT_KEYS:
        return _image_call("image", text, None)
    if any(w in text for w in _IMAGE_WORDS) or item.get("operation") == "generate_image":
        base = current.get("image")
        return _image_call("image", text, base if isinstance(base, dict) else None)
    if any(w in text.lower() for w in _CANVAS_WORDS):
        return _canvas_plan(item, view)
    name = _guess_file(text)
    base = current.get(name)
    return _write_call(name, text, base if isinstance(base, dict) else None)


def _call_for(slot: str, text: str, base: dict[str, Any] | None) -> dict[str, Any]:
    if slot in slot_registry.PDP_SLOT_KEYS - {"main_image"}:
        return _listing_call(slot, text, base)
    if slot in slot_registry.IMAGE_SLOT_KEYS:
        return _image_call(slot, text, base)
    return _write_call(slot, text, base)


def _pdp_slot_in(text: str) -> str | None:
    s = text.lower()
    for slot, words in _PDP_SLOT_WORDS.items():
        if any(w in s for w in words):
            return slot
    return None


def _listing_call(slot: str, text: str, base: dict[str, Any] | None) -> dict[str, Any]:
    """A PDP text slot on a general Task: one `edit_listing` per slot, like the PDP Agent."""
    args: dict[str, Any] = {
        "slot": slot,
        "goal": text,
        "instruction": text if base else "",
        "facts": {},
    }
    if base is not None:
        args["base_version_id"] = base["version_id"]
        args["base"] = base["content"]
    return {
        "content": "",
        "tool_calls": [{"name": "edit_listing", "id": f"edit_listing:{slot}", "args": args}],
        "path_note": "pdp_slot",
        "declined": "",
    }


def _write_call(name: str, text: str, base: dict[str, Any] | None) -> dict[str, Any]:
    body = _draft(name, text, base)
    return {
        "content": "",
        "tool_calls": [{
            "name": "write_file",
            "id": f"write_file:{name}",
            "args": {"path": name, "content": body},
        }],
        "path_note": "file_draft",
        "declined": "",
    }


_REGENERATE_WORDS = ("重新生成", "重做", "再生成一版", "重新画", "重抽")


_TYPE_WORDS = ("html", "markdown", ".md", "csv", "tsv", "表格", "网页", "页面", "活动")


def _image_call(slot: str, text: str, base: dict[str, Any] | None) -> dict[str, Any]:
    # "重新生成" is the option offered when a Version is rejected: a new first draft, not an
    # edit of the rejected one. Everything else with a base is an edit.
    if base is not None and any(w in text for w in _REGENERATE_WORDS):
        base = None
    if base is None:
        return {
            "content": "",
            "tool_calls": [{
                "name": "generate_product_image",
                "id": f"generate_product_image:{slot}",
                "args": {"slot": slot, "prompt": text or "架构示意图"},
            }],
            "path_note": "image_first_draft",
            "declined": "",
        }
    return {
        "content": "",
        "tool_calls": [{
            "name": "edit_product_image",
            "id": f"edit_product_image:{slot}",
            "args": {
                "slot": slot,
                "base_version_id": base["version_id"],
                "base_object_key": base["content"]["object_key"],
                "patch": {"operation": "free", "instruction": text},
            },
        }],
        "path_note": "image_edit",
        "declined": "",
    }


def _names_a_type(text: str) -> bool:
    s = text.lower()
    return any(w in s for w in _TYPE_WORDS)


def _guess_file(text: str) -> str:
    s = text.lower()
    if "tsv" in s:
        return "table.tsv"
    if any(w in s for w in ("csv", "表格")):
        return "table.csv"
    if "markdown" in s or ".md" in s:
        return "notes.md"
    if any(w in s for w in ("html", "网页", "页面", "活动")):
        return "page.html"
    return "notes.md"


def _draft(name: str, text: str, base: dict[str, Any] | None) -> str:
    note = text.strip() or "草稿"
    prev = ""
    if base:
        content = base.get("content")
        if isinstance(content, dict):
            prev = str(content.get("text") or "")
    if name.endswith((".html", ".htm")):
        if prev and "</body>" in prev:
            return prev.replace("</body>", f"<p>{_esc(note)}</p></body>", 1)
        return (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>活动页</title></head>"
            f"<body><h1>活动页</h1><p>{_esc(note)}</p></body></html>"
        )
    if name.endswith(".csv") or name.endswith(".tsv"):
        delim = "\t" if name.endswith(".tsv") else ","
        cell = note.replace(delim, " ").replace("\n", " ")
        if prev:
            return prev.rstrip() + f"\n2{delim}{cell}\n"
        return f"item{delim}note\n1{delim}{cell}\n"
    if prev:
        return prev.rstrip() + f"\n\n{note}\n"
    return f"# 笔记\n\n{note}\n"


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

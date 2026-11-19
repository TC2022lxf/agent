"""Offline gateway stand-in: deterministic, no network. Used for dev and tests.

It is NOT a quality reference. It exists so the whole loop (interpret -> tool -> version ->
evaluate -> settle) runs without a vendor. The real adapter is gateway_openai.py.
"""

from __future__ import annotations

import colorsys
import io
import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from PIL import Image, ImageDraw

from app.ports import ImageResult, JsonResult
from app.runtime.scripted_plan import scripted_plan

_SLOT_WORDS = {
    "title": ("标题", "title"),
    "bullets": ("五点", "卖点", "bullet"),
    "description": ("描述", "description"),
    "main_image": ("主图", "main image"),
    "search_terms": ("关键词", "search term"),
    "secondary_image": ("副图", "secondary image"),
}
_CONSTRAINT_WORDS = ("不要超过", "不得超过", "不能超过", "必须", "始终", "never", "always", "不要")
_SCALE_WORDS = ("大一点", "放大", "再大", "bigger", "larger")
_STRATEGY_WORDS = ("换个思路", "换一种", "重新来", "start over")
_PREFERENCE_WORDS = ("我喜欢", "我偏好", "以后都", "i prefer")
# A rule outlives this output. These words say so, even next to a production verb.
_STANDING_WORDS = ("以后", "每次", "始终", "永远", "以后都", "不许", "规则", "上限", "不能改")
# Asking for output. Such a sentence is about this result, so its negations describe the
# picture rather than state a standing rule.
_PRODUCE_WORDS = (
    "做一张", "做一张图", "生成", "画一", "画个", "画张", "出图", "配图", "生图",
    "写一", "写个", "写份", "制作", "帮我做", "来一张", "再来", "改成", "换成",
    "draw", "generate", "create", "make",
)
# Adjectives with no field behind them. Asking beats guessing a style parameter.
_VAGUE_WORDS = ("高级一点", "高级感", "太普通", "不够好", "好看一点", "有质感")
# "Leave X alone" clauses protect another slot from THIS edit; they never state a rule.
_PROTECT_WORDS = (
    "不要动", "不要改", "别动", "别改", "保持不变", "保持不动", "不动", "其他不变",
    "其它不变", "其余不变", "不用动", "不要碰", "别碰", "原样",
)


def _is_rule(sentence: str, *, standing: bool, wants_output: bool) -> bool:
    """A rule outlives this output; a patch describes it.

    Standing words (以后 / 每次 / 永远) decide on their own. Otherwise a negation only makes
    a rule when the sentence is not asking for output and names a limit.
    """
    if any(w in sentence for w in _SCALE_WORDS):
        return False
    if any(w in sentence for w in _PROTECT_WORDS):
        return False
    if standing:
        return True
    return any(w in sentence.lower() for w in _CONSTRAINT_WORDS) and not wants_output


def _is_vague(sentence: str, slot: str | None) -> bool:
    """No reliable field maps to this sentence, so the Agent should ask what to change."""
    return slot is None and any(w in sentence for w in _VAGUE_WORDS)


class FakeGateway:
    def chat_json(
        self, alias: str, system: str, user: str, *,
        params: dict[str, Any] | None = None, purpose: str = "", reasoning: bool = False,
        images: Sequence[bytes] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> JsonResult:
        payload = json.loads(user) if user.lstrip().startswith("{") else {"text": user}
        kind = purpose or alias
        if kind == "summary":
            text = str(payload.get("text") or payload.get("summary") or user)[:800]
            data: dict[str, Any] = {"summary": text, "content": text}
        elif kind == "followups":
            data = self._followups(payload)
        elif kind == "plan" or "tool_calls" in system or payload.get("phase") == "plan":
            data = self._plan(payload)
        elif kind == "interpret" or alias == "interpret":
            data = self._interpret(payload)
        elif kind == "listing_edit" or alias == "listing_edit":
            data = self._listing_edit(payload)
        else:
            data = self._plan(payload)
        if on_delta is not None:
            # Stream the JSON the real vendor streams, so the caller's extraction is exercised
            # on the same shape it will meet in production. Chunked mid-key to be honest about
            # fragments arriving split.
            body = json.dumps(data, ensure_ascii=False)
            for i in range(0, len(body), 12):
                on_delta(body[i:i + 12])
        return JsonResult(
            data=data, model="fake-text", purpose=kind, params=params or {}, reasoning=reasoning,
        )

    def _plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("phase") == "after_tools":
            return {"content": "完成", "tool_calls": [], "path_note": "", "declined": ""}
        item = payload.get("item")
        view = payload.get("view")
        if not isinstance(item, dict) or not isinstance(view, dict):
            return {"content": "完成", "tool_calls": [], "path_note": "", "declined": ""}
        return scripted_plan(item, view)

    def _followups(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Offline stand-in for the follow-up call: three short next questions.

        Deterministic so tests can assert the shape without a network call. The real model
        writes these from the turn; the contract (a JSON array of strings, two to four items)
        is what the runtime enforces either way.
        """
        goal = str(payload.get("goal") or "这张图").strip() or "这张图"
        return {"questions": [
            f"{goal}再换一个背景看看？",
            "把商品放大一点，占画面更多",
            "再加一张场景图做副图",
        ]}

    # -- interpret an utterance into Feedback items (one interpretation each) ---------------
    def _interpret(self, p: dict[str, Any]) -> dict[str, Any]:
        text: str = p["text"]
        default_slot: str | None = p.get("target_slot")
        # A reply to an `ask_question` is the fact the Agent was waiting for: pass it straight
        # through as a patch on the work already open, never as a fresh request or a question.
        if p.get("replying_to"):
            return {"items": [{
                "text": text,
                "target_slot": default_slot,
                "interpretation": "parameter_patch",
                "operation": "free",
                "summary": "",
            }]}
        items: list[dict[str, Any]] = []
        for sentence in [s.strip() for s in re.split(r"[;；。\n]", text) if s.strip()]:
            slot = self._slot_in(sentence) or default_slot
            item: dict[str, Any] = {"text": sentence, "target_slot": slot}
            # A sentence that asks for output is a patch on that output, not a standing rule:
            # "不要文字和水印" describes this picture. Only a rule-like sentence becomes a
            # constraint, so the negation words must not win over a production verb.
            wants_output = any(w in sentence for w in _PRODUCE_WORDS)
            # Words that only make sense for a rule that outlives this output beat the
            # production verb: "以后每次都加白边" is a rule even though it says 加.
            standing = any(w in sentence for w in _STANDING_WORDS)
            if any(w in sentence.lower() for w in _PREFERENCE_WORDS) or p.get("client_hint") == (
                "preference"
            ):
                item["interpretation"] = "new_constraint"
                item["preference_proposal"] = sentence
                item["rule"] = {"type": "note", "text": sentence}
            elif sentence.endswith(("?", "？")) or "为什么" in sentence:
                item["interpretation"] = "question"
            elif any(w in sentence for w in _STRATEGY_WORDS):
                item["interpretation"] = "strategy_switch"
            elif _is_rule(sentence, standing=standing, wants_output=wants_output):
                item["interpretation"] = "new_constraint"
                m = re.search(r"(\d+)\s*(个)?字符", sentence)
                item["rule"] = (
                    {"type": "max_chars", "slot": slot, "value": int(m.group(1))}
                    if m and slot
                    else {"type": "note", "text": sentence}
                )
            elif _is_vague(sentence, slot):
                item["interpretation"] = "question"
                item["summary"] = sentence
            else:
                item["interpretation"] = "parameter_patch"
                item["operation"] = (
                    "product_scale" if any(w in sentence for w in _SCALE_WORDS) else "free"
                )
            items.append(item)
        return {"items": items}

    @staticmethod
    def _slot_in(sentence: str) -> str | None:
        s = sentence.lower()
        for slot, words in _SLOT_WORDS.items():
            if any(w in s for w in words):
                return slot
        return None

    # -- listing text -----------------------------------------------------------------------
    def _listing_edit(self, p: dict[str, Any]) -> dict[str, Any]:
        slot, goal = p["slot"], p.get("goal") or "Product"
        instruction: str = p.get("instruction") or ""
        base = p.get("base")
        max_chars: int | None = p.get("max_chars")
        if slot == "bullets":
            items = list(base["items"]) if base else [
                f"{goal} feature {i + 1}: concise benefit statement." for i in range(5)
            ]
            if base and instruction:
                items[0] = f"{items[0].split(' | ')[0]} | {instruction[:30]}"
            if max_chars:
                items = [i[:max_chars] for i in items]
            return {"content": {"items": items}}
        text = (
            base["text"]
            if base
            else (
                f"{goal} - Rechargeable, Waterproof, Wet and Dry Use"
                if slot == "title"
                else f"{goal}: designed for everyday use, easy to clean, long battery life."
            )
        )
        if base and instruction:
            text = f"{text} | {instruction[:30]}"
        if max_chars:
            text = text[:max_chars]
        return {"content": {"text": text}}

    # -- images -----------------------------------------------------------------------------
    def image_generate(
        self, alias: str, prompt: str, size: int, aspect_ratio: str | None = None,
        reference_png: bytes | None = None,
    ) -> ImageResult:
        """With a reference, the stand-in actually uses it: the product comes from the
        reference picture, so tests can prove the subject is not invented."""
        del alias, prompt, aspect_ratio
        img = Image.new("RGB", (size, size), (255, 255, 255))
        if reference_png is not None:
            src = Image.open(io.BytesIO(reference_png)).convert("RGB")
            m = int(size * 0.06)  # same 88% occupancy as the drawn stand-in
            fit = src.copy()
            fit.thumbnail((size - 2 * m, size - 2 * m))
            img.paste(fit, ((size - fit.width) // 2, (size - fit.height) // 2))
            return ImageResult(
                png=_png(img), model="fake-image", params={"reference": True},
            )
        d = ImageDraw.Draw(img)
        m = int(size * 0.06)  # product box covers ~88% of each side
        d.rounded_rectangle((m, m, size - m, size - m), radius=size // 12, fill=(60, 110, 200))
        d.ellipse((size * 0.4, size * 0.4, size * 0.6, size * 0.6), fill=(230, 230, 235))
        return ImageResult(png=_png(img), model="fake-image", params={"reference": False})

    def image_edit(
        self, alias: str, image_png: bytes, mask_png: bytes | None, prompt: str,
        aspect_ratio: str | None = None,
    ) -> ImageResult:
        """Deliberately sloppy: changes the WHOLE image, so tests prove the engine confines it."""
        del alias, aspect_ratio
        img = Image.open(io.BytesIO(image_png)).convert("RGB")
        red = "红" in prompt or "red" in prompt.lower()
        px = img.load()
        assert px is not None
        for y in range(img.height):
            for x in range(img.width):
                r, g, b = px[x, y]  # type: ignore[misc]  # Pillow stubs: RGB pixel is a tuple
                if red:
                    px[x, y] = (255, int(g * 0.3), int(b * 0.3))
                else:
                    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                    r2, g2, b2 = colorsys.hsv_to_rgb((h + 0.08) % 1, min(1, s * 1.1), v * 0.85)
                    px[x, y] = (int(r2 * 255), int(g2 * 255), int(b2 * 255))
        return ImageResult(png=_png(img), model="fake-image-edit")

    def web_search(
        self, query: str, *, count: int = 5, need_content: bool = False,
        ori_question: str | None = None,
    ) -> dict[str, Any]:
        del count, ori_question
        return {
            "results": [{
                "title": f"Result for {query}",
                "url": "https://example.com/dmxapi",
                "site_name": "example.com",
                "date": "2026-03-26",
                "snippet": "DMXAPI is an API platform.",
                "summary": "DMXAPI is an API platform.",
                "content": "Full page about DMXAPI. " + ("x" * 3000) if need_content else "",
            }]
        }

    def web_fetch(self, url: str) -> dict[str, Any]:
        return {"title": "Fetched", "content": f"Markdown for {url}\n\n" + ("y" * 9000)}


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

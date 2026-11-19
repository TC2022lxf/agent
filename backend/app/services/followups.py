"""Suggested follow-ups: what the user probably wants to ask next (docs/architecture/system.md).

This is NOT `ask_question`. `ask_question` is a blocking Tool call inside the plan loop: the
Agent cannot continue without a fact. A follow-up is a rendering hint after the turn is over,
and it never influences what this turn produced. Two surfaces, two different questions:

    ask_question   missing required fact, continuing would be wrong   (Tool call, blocks)
    follow-ups     this turn is done, what would they want next      (UI hint, never blocks)

Why a second model call instead of asking the planner to emit them: the main reply is a
JSON object streamed to the user, and appending "and also three questions" to that contract
makes the planner hedge its answer or repeat the questions in the reply. A separate call
also fails independently — a timeout here means no chips, not a failed Run — and it can be
bound to a cheaper model without touching the planner (docs/architecture/agent-runtime.md).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ports import ModelGatewayPort

log = logging.getLogger(__name__)

MAX_QUESTIONS = 3
MAX_CHARS = 60

SYSTEM = """You write the follow-up questions a user would most likely ask next, after one \
finished turn of an e-commerce image/listing agent.

Rules:
- Write them in the language of the conversation.
- Each one is the user's own words, ready to send as-is. No numbering, no quotes, no prefixes.
- Short and concrete: name the thing to change (背景、构图、颜色、文案、尺寸), not "还可以做什么".
- Offer different directions: do not write three versions of the same request.
- Never repeat a question the user already asked in this conversation.
- Never ask for a fact the assistant said it needs in order to continue; that is a real \
question, not a suggestion.
- Output JSON only: {"questions": ["...", "...", "..."]} with two or three items."""


def _clean(raw: Any, asked: set[str]) -> list[str]:
    """Keep replies a button can actually send.

    The model's list is a suggestion, not trusted input: an item that repeats something the
    user already said, or one that is a paragraph, is dropped rather than rendered.
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip().strip('"\'').lstrip("0123456789.、) ")
        if not text or len(text) > MAX_CHARS or text in asked or text in out:
            continue
        out.append(text)
        if len(out) >= MAX_QUESTIONS:
            break
    return out


def suggest(
    gateway: ModelGatewayPort,
    *,
    profile_key: str,
    user_query: str,
    assistant_answer: str,
    context: list[str] | None = None,
) -> list[str]:
    """Two or three one-click next questions. Returns [] on any failure.

    Never raises: a Run that already delivered its artifact must not become a failure because
    a decorative suggestion call went wrong.
    """
    if not assistant_answer.strip():
        return []
    asked = {user_query.strip()} if user_query.strip() else set()
    body = {
        "turn": {"user": user_query, "assistant": assistant_answer},
        "conversation": (context or [])[-4:],
    }
    try:
        result = gateway.chat_json(
            profile_key, SYSTEM, json.dumps(body, ensure_ascii=False),
            purpose="followups", reasoning=False,
        )
    except Exception:  # noqa: BLE001 - a suggestion is never worth failing a Run over
        log.info("follow-up suggestions failed; the turn keeps its answer only", exc_info=True)
        return []
    return _clean(result.data.get("questions") or result.data.get("follow_ups"), asked)

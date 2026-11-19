"""Pins the ask_question loop bug: the graph keeps asking after a question was recorded."""

from __future__ import annotations

import pytest

from app.infrastructure.gateway_fake import FakeGateway
from tests.conftest import Api


class _AlwaysAsks(FakeGateway):
    """A planner that answers every plan with the same ask_question, like a stuck real model."""

    def chat_json(self, alias, system, user, *, params=None, purpose="", reasoning=False,
                  images=None, on_delta=None):  # type: ignore[no-untyped-def]
        if purpose == "plan":
            from app.ports import JsonResult
            body = {
                "content": "",
                "tool_calls": [{
                    "name": "ask_question",
                    "id": "ask_question",
                    "args": {"question": "是哪个商品？", "options": ["剃须刀"]},
                }],
                "path_note": "ask",
                "declined": "",
            }
            return JsonResult(data=body, model="fake", purpose=purpose,
                              params=params or {}, reasoning=reasoning)
        return super().chat_json(
            alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
            images=images, on_delta=on_delta,
        )


def test_a_question_ends_the_tool_loop_instead_of_exhausting_recursion(api: Api) -> None:
    """Recording the question must stop the graph: it is waiting for a human, not looping."""
    gw = _AlwaysAsks()
    api.c.executor.gateway = gw  # type: ignore[assignment]
    api.c.executor.loop.gateway = gw  # type: ignore[assignment]

    task = api.task("general", kind="general", goal="做点东西")
    run = api.say(task["id"], "帮我做一套素材")
    assert run["status"] != "failed", f"the loop did not stop: {run['error']}"
    assert "Recursion" not in (run["error"] or "")

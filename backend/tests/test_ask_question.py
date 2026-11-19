"""Structured questions via ask_question (decisions/0037)."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from app.agents.builtin import build_registry
from app.tools.ask_tools import AskQuestionInput, AskQuestionTool
from app.tools.base import ToolContext


def test_ask_question_tool_is_free_and_has_no_side_effects() -> None:
    meta = AskQuestionTool.meta
    assert meta.cost_credits == 0
    assert meta.writes_version is False
    assert meta.side_effect == "none"


def test_ask_question_execute_returns_question_and_options() -> None:
    tool = AskQuestionTool()
    ctx = ToolContext(
        run_id="run_x", trace_id="t", user_id="u",
        gateway=None, store=None,  # type: ignore[arg-type]
    )
    out = tool.execute(
        AskQuestionInput(
            question="要画哪个商品？",
            options=["我先上传一张产品照", "用商品库里已保存的图"],
        ),
        ctx,
    )
    assert out.question == "要画哪个商品？"
    assert len(out.options) == 2
    assert out.status == "awaiting_user"


def test_ask_question_requires_at_least_one_option() -> None:
    with pytest.raises(ValidationError):
        AskQuestionInput(question="要画哪个商品？", options=[])


def test_every_agent_may_call_ask_question() -> None:
    reg = build_registry()
    for key in ("amazon_pdp", "image", "canvas", "general"):
        assert "ask_question" in reg.agent(key).tool_names

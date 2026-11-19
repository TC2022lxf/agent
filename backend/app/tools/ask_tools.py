"""Structured user questions (docs/architecture/agent-runtime.md). The planner calls this instead of embedding
questions in free-form JSON. Runtime turns the result into chat `answer` events and optional
reply buttons. No model call, no Version, no credit charge."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.tools.base import Tool, ToolContext, ToolMeta


class AskQuestionInput(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=2000,
        description="What you need from the user, shown verbatim in the chat.",
    )
    options: list[str] = Field(
        min_length=1,
        max_length=3,
        description=(
            "One to three replies the user could send verbatim (best first). "
            "Each must be something you can act on immediately. "
            "For open-ended facts, offer concrete starters (e.g. upload a photo, pick from library, "
            "describe color and material) instead of leaving this empty."
        ),
    )

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("question is blank")
        return text

    @field_validator("options")
    @classmethod
    def clean_options(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if not text or len(text) > 80 or text in out:
                continue
            out.append(text)
            if len(out) >= 3:
                break
        if not out:
            raise ValueError("options must include at least one non-empty reply")
        return out


class AskQuestionOutput(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)
    status: str = "awaiting_user"


class AskQuestionTool(Tool):
    meta = ToolMeta(
        name="ask_question",
        version="1",
        description=(
            "Ask the user one question before continuing. Use when a missing fact would "
            "change what you build (which product, which direction, which module). "
            "Do not invent product names in options."
        ),
        side_effect="none",
        cost_credits=0,
        timeout_s=5.0,
        idempotent=True,
        writes_version=False,
    )
    input_model = AskQuestionInput
    output_model = AskQuestionOutput

    def execute(self, input: AskQuestionInput, ctx: ToolContext) -> AskQuestionOutput:
        del ctx
        return AskQuestionOutput(question=input.question, options=list(input.options))

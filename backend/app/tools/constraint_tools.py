"""Record a standing rule instead of guessing what the user meant (docs/architecture/agent-runtime.md).

There used to be a separate interpret call before the loop whose only unique job was to tell
"this is a rule for every later turn" apart from "change this output". That decision is a
decision the agent can make with the same context it uses to choose any other tool, so it is
a tool: the model either calls `record_constraint` or it does not.

Nothing here is applied. A draft is recorded and the user confirms it (docs/architecture/data-and-contracts.md); an
unconfirmed rule must never change what a later Version is allowed to be.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.tools.base import Tool, ToolContext, ToolMeta


class RecordConstraintInput(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "The rule in one sentence, in the user's own words. For example "
            "「标题不要超过 20 个字符」."
        ),
    )
    scope: Literal["task", "user"] = Field(
        default="task",
        description=(
            "`task` for a rule about this Task's work (a limit, a fixed style, something that "
            "must keep holding here). `user` when the sentence describes the person, their "
            "brand voice, or how they like to collaborate with you; that becomes a proposal "
            "for the preferences document."
        ),
    )
    rule: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional checkable form. Use {\"type\": \"max_chars\", \"slot\": \"title\", "
            "\"value\": 20} only when the user gave a number. Otherwise omit it; the sentence "
            "itself is the rule."
        ),
    )

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("text is blank")
        return text


class RecordConstraintOutput(BaseModel):
    scope: str
    status: str  # pending | proposed
    text: str


class RecordConstraintTool(Tool):
    meta = ToolMeta(
        name="record_constraint",
        version="1",
        description=(
            "Record a rule that must keep holding for later turns in this Task, or propose a "
            "preference about the user. Does not write a Version and does not change the "
            "current one: the user confirms a rule before it takes effect. Call this instead "
            "of only saying in prose that you will follow a rule."
        ),
        side_effect="none",
        cost_credits=0,
        timeout_s=5.0,
        idempotent=True,
        writes_version=False,
    )
    input_model = RecordConstraintInput
    output_model = RecordConstraintOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        del ctx
        i = RecordConstraintInput.model_validate(input)
        return RecordConstraintOutput(
            scope=i.scope,
            status="proposed" if i.scope == "user" else "pending",
            text=i.text,
        )

"""Tool port (docs/07). A Tool does one atomic thing; it never touches the database,
writes Versions, deducts credits or writes logs. Wrapping is ToolRunner's job."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

from app.ports import ModelGatewayPort, ObjectStorePort


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass(frozen=True)
class ToolMeta:
    name: str
    version: str
    description: str
    side_effect: str  # none | write_blob
    cost_credits: int
    timeout_s: float
    idempotent: bool = True
    writes_version: bool = True


@dataclass(frozen=True)
class ToolContext:
    """No database handle, no UI state."""

    run_id: str
    trace_id: str
    user_id: str
    gateway: ModelGatewayPort
    store: ObjectStorePort
    preferences_md: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    meta: ClassVar[ToolMeta]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]

    @abstractmethod
    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel: ...

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return cls.input_model.model_json_schema()

    @classmethod
    def output_schema(cls) -> dict[str, Any]:
        return cls.output_model.model_json_schema()

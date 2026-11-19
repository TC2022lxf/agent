"""Evaluator port. Rule evaluators run automatically after every new Version (Runtime)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.ports import ObjectStorePort


@dataclass(frozen=True)
class EvalSubject:
    slot: str
    content: dict[str, Any]
    task_meta: dict[str, Any]
    user_rules: list[dict[str, Any]]
    store: ObjectStorePort


@dataclass(frozen=True)
class EvalResult:
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


class Evaluator(ABC):
    id: ClassVar[str]
    description: ClassVar[str]
    can_reject: ClassVar[bool]  # a failing rule evaluator with can_reject blocks "current"

    @abstractmethod
    def applies_to(self, subject: EvalSubject) -> bool: ...

    @abstractmethod
    def evaluate(self, subject: EvalSubject) -> EvalResult: ...


class EvaluatorRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Evaluator] = {}

    def register(self, ev: Evaluator) -> None:
        if not getattr(ev, "description", ""):
            raise ValueError(f"evaluator {ev.id}: description is required")
        self._items[ev.id] = ev

    def all(self) -> list[Evaluator]:
        return list(self._items.values())

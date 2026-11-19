"""Composition root: the only place concrete adapters are chosen."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.builtin import build_evaluators, build_registry
from app.agents.registry import Registry
from app.config import Settings
from app.evaluators.base import EvaluatorRegistry
from app.infrastructure.gateway_fake import FakeGateway
from app.infrastructure.gateway_logging import LoggingGateway, current_planner_profile
from app.infrastructure.gateway_openai import OpenAIGateway
from app.infrastructure.storage import LocalObjectStore
from app.ports import ModelGatewayPort, ObjectStorePort
from app.runtime.executor import RunExecutor
from app.runtime.langgraph_loop import LangGraphLoop
from app.runtime.tool_runner import ToolRunner
from app.runtime.worker import Worker
from app.services.profiles import IMAGE_KEY, PLANNER_KEY
from app.services.uow import UowFactory, make_uow_factory


@dataclass
class Container:
    settings: Settings
    uow_factory: UowFactory
    registry: Registry
    evaluators: EvaluatorRegistry
    gateway: ModelGatewayPort
    store: ObjectStorePort
    executor: RunExecutor
    worker: Worker


def build_container(
    settings: Settings,
    *,
    store: ObjectStorePort | None = None,
    inner_gateway: ModelGatewayPort | None = None,
) -> Container:
    uow_factory = make_uow_factory(settings.database_url)
    with uow_factory() as uow:
        uow.profiles.ensure_seed(
            planner_model=settings.planner_model,
            image_model=settings.image_model,
        )
        uow.commit()

    def sink(row: dict[str, object]) -> None:
        with uow_factory() as uow:
            uow.collab.add_llm_call(**row)
            uow.commit()

    def resolve_model(alias: str) -> str:
        with uow_factory() as uow:
            if alias in {"image_generate", "image_edit"}:
                image = uow.profiles.image_profile()
                if image is not None:
                    return image.upstream_model
                fallback = uow.profiles.get(IMAGE_KEY)
                return fallback.upstream_model if fallback is not None else alias
            key = current_planner_profile.get() or alias
            row = uow.profiles.get(key) or uow.profiles.get(PLANNER_KEY)
            return row.upstream_model if row is not None else alias

    def image_capabilities() -> set[str]:
        """Whether the bound image model answers in chat or via `/images/*` (decision 0022)."""
        with uow_factory() as uow:
            image = uow.profiles.image_profile()
        return set(image.capabilities or []) if image is not None else set()

    store = store or LocalObjectStore(settings.storage_dir)
    inner = inner_gateway or (
        OpenAIGateway(
            settings.openai_base_url,
            settings.openai_api_key,
            resolve_model=resolve_model,
            image_capabilities=image_capabilities,
        )
        if settings.gateway == "openai"
        else FakeGateway()
    )
    gateway = LoggingGateway(inner, sink, store)
    registry = build_registry()
    with uow_factory() as uow:
        _apply_skill_edits(registry, uow)
        uow.commit()
    evaluators = build_evaluators()
    runner = ToolRunner(registry, gateway, store)
    loop = LangGraphLoop(
        uow_factory, registry, evaluators, gateway, store, runner,
        database_url=settings.database_url,
    )
    executor = RunExecutor(
        uow_factory, registry, evaluators, gateway, store, loop, runner,
    )
    return Container(
        settings, uow_factory, registry, evaluators, gateway, store, executor,
        Worker(uow_factory, executor),
    )


def _apply_skill_edits(registry: Registry, uow: object) -> None:
    """Saved revisions win over the file text. Bad text is skipped, not fatal at boot."""
    service = uow.skill_edits  # type: ignore[attr-defined]
    for skill_id in [s.id for s in registry.skills()]:
        row = service.latest(skill_id)
        if row is None:
            continue
        try:
            registry.load_skill_text(
                skill_id, row.body, revision=row.revision, source=row.source,
            )
        except ValueError:
            continue

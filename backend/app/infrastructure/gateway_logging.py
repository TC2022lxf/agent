"""Gateway decorator: records every model call as llm_calls (docs/architecture/data-and-contracts.md). Tools never log."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from typing import Any

from app.ports import ImageResult, JsonResult, ModelGatewayPort, ObjectStorePort

current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)
current_planner_profile: ContextVar[str] = ContextVar("current_planner_profile", default="")
current_image_profile: ContextVar[str] = ContextVar("current_image_profile", default="")
LlmSink = Callable[[dict[str, object]], None]


class LoggingGateway:
    def __init__(self, inner: ModelGatewayPort, sink: LlmSink, store: ObjectStorePort) -> None:
        self._inner, self._sink, self._store = inner, sink, store

    def _keep(self, body: dict[str, object]) -> str:
        from uuid import uuid4

        key = f"llm/{uuid4().hex}.json"
        self._store.put(key, json.dumps(body, ensure_ascii=False).encode())
        return key

    def _log(
        self, alias: str, kind: str, t0: float, model: str, status: str, *,
        purpose: str = "", params: dict[str, Any] | None = None, reasoning: bool = False,
        tokens_in: int = 0, tokens_out: int = 0, object_key: str | None = None,
        profile_key: str = "",
    ) -> None:
        image = kind.startswith("image")
        self._sink(
            {
                "run_id": current_run_id.get(),
                "alias": alias,
                "kind": kind,
                "model": model,
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "status": status,
                "profile_key": profile_key or (
                    current_image_profile.get() if image else current_planner_profile.get()
                ),
                "purpose": "image" if image else (purpose or alias),
                "params": params or {},
                "reasoning": reasoning,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "error": None if status == "ok" else status,
                "object_key": object_key,
            }
        )

    def chat_json(
        self, alias: str, system: str, user: str, *,
        params: dict[str, Any] | None = None, purpose: str = "", reasoning: bool = False,
        images: Sequence[bytes] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> JsonResult:
        t0 = time.monotonic()
        key = self._keep({
            "system": system, "user": user, "params": params or {},
            "images": len(images or ()),
        })
        try:
            r = self._inner.chat_json(
                alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
                images=images, on_delta=on_delta,
            )
        except Exception:
            self._log(alias, "chat", t0, "", "error", purpose=purpose, params=params,
                      reasoning=reasoning, object_key=key)
            raise
        self._store.put(
            key,
            json.dumps(
                {
                    "system": system, "user": user, "params": params or {},
                    "images": len(images or ()), "response": r.data,
                },
                ensure_ascii=False,
            ).encode(),
        )
        self._log(
            alias, "chat", t0, r.model, "ok",
            purpose=r.purpose or purpose, params=r.params or params,
            reasoning=r.reasoning or reasoning, tokens_in=r.tokens_in, tokens_out=r.tokens_out,
            object_key=key, profile_key=r.profile_key,
        )
        return r

    def image_generate(
        self, alias: str, prompt: str, size: int, aspect_ratio: str | None = None,
        reference_png: bytes | None = None,
    ) -> ImageResult:
        t0 = time.monotonic()
        key = self._keep({
            "prompt": prompt, "size": size, "aspect_ratio": aspect_ratio,
            "has_reference": reference_png is not None,
        })
        params = {"size": size, "has_reference": reference_png is not None}
        try:
            r = self._inner.image_generate(alias, prompt, size, aspect_ratio, reference_png)
        except Exception:
            self._log(alias, "image_generate", t0, "", "error", params=params, object_key=key)
            raise
        self._log(
            alias, "image_generate", t0, r.model, "ok", params=r.params or params,
            object_key=key, profile_key=r.profile_key,
        )
        return r

    def image_edit(
        self, alias: str, image_png: bytes, mask_png: bytes | None, prompt: str,
        aspect_ratio: str | None = None,
    ) -> ImageResult:
        t0 = time.monotonic()
        key = self._keep({
            "prompt": prompt, "has_mask": mask_png is not None, "aspect_ratio": aspect_ratio,
        })
        params = {"has_mask": mask_png is not None}
        try:
            r = self._inner.image_edit(alias, image_png, mask_png, prompt, aspect_ratio)
        except Exception:
            self._log(alias, "image_edit", t0, "", "error", params=params, object_key=key)
            raise
        self._log(
            alias, "image_edit", t0, r.model, "ok", params=r.params or params,
            object_key=key, profile_key=r.profile_key,
        )
        return r

    def web_search(
        self, query: str, *, count: int = 5, need_content: bool = False,
        ori_question: str | None = None,
    ) -> dict[str, Any]:
        # A tool call, not a model call: ToolRunner already records it on tool_calls.
        return self._inner.web_search(
            query, count=count, need_content=need_content, ori_question=ori_question,
        )

    def web_fetch(self, url: str) -> dict[str, Any]:
        return self._inner.web_fetch(url)

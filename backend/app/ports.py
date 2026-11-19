"""Ports (docs/architecture/agent-runtime.md). Tools, engines and runtime depend on these, never on vendors."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class JsonResult:
    data: dict[str, Any]
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    profile_key: str = ""
    purpose: str = ""
    params: dict[str, Any] | None = None
    reasoning: bool = False


@dataclass(frozen=True)
class ImageResult:
    png: bytes
    model: str = ""
    profile_key: str = ""
    params: dict[str, Any] | None = None


class ModelGatewayPort(Protocol):
    """All model calls go through here (docs/architecture/data-and-contracts.md). Aliases, not vendor model names."""

    def chat_json(
        self, alias: str, system: str, user: str, *,
        params: dict[str, Any] | None = None, purpose: str = "", reasoning: bool = False,
        images: Sequence[bytes] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> JsonResult:
        """One JSON-answering call.

        `images` are pictures the model may look at (only when its profile declares `vision`).
        `on_delta` receives the raw content as it streams; the return value is the same parsed
        object either way, so a caller may ignore streaming and still be correct.
        """
        ...

    def image_generate(
        self, alias: str, prompt: str, size: int, aspect_ratio: str | None = None,
        reference_png: bytes | None = None,
    ) -> ImageResult:
        """`reference_png` is the picture the result must stay faithful to (the product)."""
        ...

    def image_edit(
        self, alias: str, image_png: bytes, mask_png: bytes | None, prompt: str,
        aspect_ratio: str | None = None,
    ) -> ImageResult: ...

    def web_search(
        self, query: str, *, count: int = 5, need_content: bool = False,
        ori_question: str | None = None,
    ) -> dict[str, Any]:
        """Vendor web search. Not a model call; same credentials as the gateway."""
        ...

    def web_fetch(self, url: str) -> dict[str, Any]:
        """Vendor page fetch. Returns title and markdown. Not a model call."""
        ...


class ObjectStorePort(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

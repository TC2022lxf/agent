from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.container import Container, build_container
from app.infrastructure.storage import MemoryObjectStore
from app.main import create_app


class Api:
    """Thin test helper: post an utterance, drain the worker, return the run."""

    def __init__(self, client: TestClient, container: Container) -> None:
        self.http, self.c = client, container
        self._n = 0

    def task(self, agent: str = "amazon_pdp", **kw: Any) -> dict[str, Any]:
        r = self.http.post("/api/tasks", json={"agent_id": agent, "goal": "Electric razor", **kw})
        assert r.status_code == 201, r.text
        data: dict[str, Any] = r.json()
        return data

    def say(self, task_id: str, text: str, **kw: Any) -> dict[str, Any]:
        self._n += 1
        r = self.http.post(
            f"/api/tasks/{task_id}/utterances",
            json={"text": text, **kw},
            headers={"Idempotency-Key": f"k{self._n}"},
        )
        assert r.status_code == 202, r.text
        self.c.worker.drain()
        run: dict[str, Any] = self.http.get(f"/api/runs/{r.json()['id']}").json()
        return run

    def task_state(self, task_id: str) -> dict[str, Any]:
        data: dict[str, Any] = self.http.get(f"/api/tasks/{task_id}").json()
        return data

    def slot_versions(self, task_id: str, slot: str) -> list[dict[str, Any]]:
        arts = self.http.get(f"/api/tasks/{task_id}/artifacts").json()
        return next(a["versions"] for a in arts if a["slot"] == slot)

    def upload_png(self, color: tuple[int, int, int] = (255, 255, 255)) -> str:
        img = Image.new("RGB", (1000, 1000), color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        r = self.http.post("/api/uploads", files={"file": ("a.png", buf.getvalue(), "image/png")})
        assert r.status_code == 201, r.text
        return str(r.json()["upload_id"])


@pytest.fixture()
def container() -> Container:
    settings = Settings(database_url="sqlite://", run_worker="off")
    return build_container(settings, store=MemoryObjectStore())


@pytest.fixture()
def api(container: Container) -> Iterator[Api]:
    with TestClient(create_app(container)) as client:
        yield Api(client, container)


def blob_pixels(api: Api, version: dict[str, Any]) -> Image.Image:
    data = api.c.store.get(version["content"]["object_key"])
    return Image.open(io.BytesIO(data)).convert("RGB")

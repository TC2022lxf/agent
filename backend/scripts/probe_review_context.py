"""Live probe: does a real planner see the picture, and does the turn end with words?

Runs against whatever `.env` binds, through the real HTTP surface. Costs real credits and one
image. Not a test: it is the experiment behind decisions/0041, and it prints what actually
came back so a mismatch is visible rather than guessed at.

    cd backend
    .venv/Scripts/python scripts/probe_review_context.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings, load_dotenv  # noqa: E402
from app.container import build_container  # noqa: E402
from app.infrastructure.storage import MemoryObjectStore  # noqa: E402
from app.main import create_app  # noqa: E402


def turn(client: TestClient, task_id: str, text: str, **extra: object) -> dict[str, object]:
    r = client.post(
        f"/api/tasks/{task_id}/utterances",
        json={"text": text, **extra},
        headers={"Idempotency-Key": f"probe-{abs(hash(text))}"},
    )
    assert r.status_code == 202, r.text
    client.container.worker.drain()  # type: ignore[attr-defined]
    run_id = r.json()["id"]
    run = client.get(f"/api/runs/{run_id}").json()
    turns = client.get(f"/api/tasks/{task_id}/timeline").json()
    last = turns[-1] if turns else {}
    return {
        "status": run["status"],
        "error": run["error"],
        "versions": run["version_ids"],
        "answers": last.get("answers"),
        "asked": [q.get("question") for q in last.get("human_input_requests") or []],
        "follow_ups": last.get("follow_ups"),
        "steps": [s["tool"] for s in last.get("steps") or []],
    }


def main() -> int:
    load_dotenv()
    if os.environ.get("GATEWAY") != "openai":
        print("GATEWAY is not openai; nothing to probe")
        return 1
    settings = Settings.from_env()
    isolated = Settings(
        database_url="sqlite://",
        storage_dir=settings.storage_dir,
        gateway=settings.gateway,
        openai_base_url=settings.openai_base_url,
        openai_api_key=settings.openai_api_key,
        run_worker="off",
        initial_credits=1000,
    )
    container = build_container(isolated, store=MemoryObjectStore())
    with container.uow_factory() as uow:
        planner = uow.profiles.planner_for_agent("image")
        image = uow.profiles.image_profile()
        print(f"planner profile = {planner.key}")
        print(f"  upstream      = {planner.upstream_model}")
        print(f"  capabilities  = {list(planner.capabilities or [])}")
        print(f"image profile   = {image.key if image else None}")
        print(f"  capabilities  = {list(image.capabilities or []) if image else []}")
        print("  vision on planner:", "vision" in (planner.capabilities or []))

    with TestClient(create_app(container)) as client:
        client.container = container  # type: ignore[attr-defined]
        task = client.post(
            "/api/tasks", json={"agent_id": "image", "kind": "image", "goal": "剃须刀主图"},
        ).json()
        print(f"\ntask = {task['id']}")

        print("\n--- turn 1: draw it")
        print(json.dumps(turn(client, task["id"], "做一张纯白背景的电商主图，商品居中，不要文字和水印",
                              target_slot="image"), ensure_ascii=False, indent=2))

        print("\n--- turn 2: what colour is it (needs the picture, not its file name)")
        print(json.dumps(turn(client, task["id"], "这是一个什么剃须刀，你描述一下外观",
                              target_slot="image"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

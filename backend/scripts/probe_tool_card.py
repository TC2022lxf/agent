"""Live probe: does a Tool card exist while the Tool is still running?

The card's whole point is to be on screen during the wait, not only after it. This records the
SSE stream with timestamps and checks the order: `tool_started` must arrive BEFORE the Tool
takes its time (and long before `version_created`), so the card is present during the wait.

Costs real credits and one image. Not a test.

    cd backend
    .venv/Scripts/python scripts/probe_tool_card.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings, load_dotenv  # noqa: E402
from app.container import build_container  # noqa: E402
from app.infrastructure.storage import MemoryObjectStore  # noqa: E402
from app.main import create_app  # noqa: E402


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

    with TestClient(create_app(container)) as client:
        client.container = container  # type: ignore[attr-defined]
        task = client.post(
            "/api/tasks", json={"agent_id": "image", "kind": "image", "goal": "剃须刀主图"},
        ).json()

        r = client.post(
            f"/api/tasks/{task['id']}/utterances",
            json={"text": "做一张纯白背景的电商主图，商品居中，不要文字和水印",
                  "target_slot": "image"},
            headers={"Idempotency-Key": "probe-card-1"},
        )
        assert r.status_code == 202, r.text
        run_id = r.json()["id"]
        t0 = time.monotonic()
        seen: list[tuple[float, str, object]] = []
        stop = threading.Event()

        def watch() -> None:
            after = 0
            while not stop.is_set():
                for e in container.uow_factory().collab.events_after(run_id, after):
                    after = e.id
                    seen.append((round(time.monotonic() - t0, 2), e.type, e.data))
                time.sleep(0.05)

        th = threading.Thread(target=watch, daemon=True)
        th.start()
        container.worker.drain()
        time.sleep(0.3)
        stop.set()
        th.join(timeout=2)

        print(f"task = {task['id']}  run = {run_id}")
        print("\n--- SSE/event order with timestamps (s):")
        for at, kind, data in seen:
            brief = ""
            if kind == "tool_started":
                brief = (f"  {data.get('tool')} slot={data.get('slot')} "
                         f"cost={data.get('cost')} args={list((data.get('args') or {}))}")
            elif kind in {"answer", "answer_delta"}:
                brief = "  " + str(data.get("text"))[:60]
            print(f"  {at:>6.2f}  {kind}{brief}")

        starts = [s for s in seen if s[1] == "tool_started"]
        versions = [s for s in seen if s[1] == "version_created" and s[2].get("slot")]
        print("\n--- checks:")
        ok = True
        if not starts:
            print("  FAIL: no tool_started event")
            ok = False
        else:
            s_at = starts[0][0]
            print(f"  card announced at {s_at}s: {starts[0][2].get('tool')}")
            if versions:
                gap = versions[0][0] - s_at
                print(f"  version_created at {versions[0][0]}s (+{gap:.2f}s after the card)")
                if gap <= 0:
                    print("  FAIL: the card did not predate the result")
                    ok = False
            else:
                print("  FAIL: the run produced no version")
                ok = False
            if starts[0][2].get("tool_call_id") != (
                versions[0][2].get("version_id") and starts[0][2].get("tool_call_id")
            ):
                pass
        steps = client.get(f"/api/tasks/{task['id']}/timeline").json()[0]["steps"]
        print(f"  timeline steps: {[(s['tool'], s.get('tool_call_id', '')[-14:]) for s in steps]}")
        for s in steps:
            print(f"    input keys = {sorted((s.get('input') or {}))}")
            print(f"    output     = {json.dumps(s.get('output') or {}, ensure_ascii=False)[:120]}")
        started_ids = [s[2].get("tool_call_id") for s in starts]
        step_ids = [s.get("tool_call_id") for s in steps]
        if started_ids and step_ids and started_ids != step_ids:
            print(f"  FAIL: ids do not match\n    announced={started_ids}\n    recorded ={step_ids}")
            ok = False
        elif started_ids:
            print("  card id == record id: one card, not two rows")

        print("\n--- result:", "OK" if ok else "PROBLEM")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

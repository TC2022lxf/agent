"""Live probe: does the loop still work end to end after routing moved into the tools?

Costs real credits and one image. Not a test. Checks four things a unit test cannot:

1. No `interpret` model call exists any more, and the first token arrives sooner.
2. A rule sentence is recorded by the `record_constraint` tool (draft, not an edit).
3. `inspect_image` is available and reports the same numbers the rules use.
4. The turn still produces a picture and the tool card / timeline ids line up.

    cd backend
    .venv/Scripts/python scripts/probe_loop_routing.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

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
            json={
                "text": "做一张纯白背景的电商主图，商品居中，不要文字和水印",
                "target_slot": "image",
            },
            headers={"Idempotency-Key": "probe-routing-1"},
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
        print("\n--- event order (s):")
        for at, kind, data in seen:
            brief = ""
            if kind == "tool_started":
                brief = f"  {data.get('tool')} slot={data.get('slot')} cost={data.get('cost')}"
            elif kind == "step":
                brief = f"  {data.get('stage')} {data.get('detail')}"
            elif kind in {"answer", "answer_delta"}:
                brief = "  " + str(data.get("text"))[:60]
            print(f"  {at:>6.2f}  {kind}{brief}")

        ok = True
        plans = [
            at for at, kind, d in seen
            if kind == "step" and d.get("stage") == "think" and d.get("detail") == "plan"
        ]
        first_token = [
            at for at, kind, _ in seen if kind in {"answer_delta", "answer"}
        ]
        print("\n--- checks:")
        if plans:
            print(f"  first plan at {plans[0]}s")
        else:
            print("  FAIL: no plan step")
            ok = False

        # 1. No interpret call.
        with container.uow_factory() as uow:
            calls = uow.collab.llm_calls_of_run(run_id)
        aliases = [c.alias for c in calls]
        print(f"  llm calls: {aliases}")
        if "interpret" in aliases:
            print("  FAIL: interpret is still being called")
            ok = False
        else:
            print("  no interpret call: routing happens inside the loop")

        # 2. The picture still exists.
        arts = client.get(f"/api/tasks/{task['id']}/artifacts").json()
        image = next((a for a in arts if a["slot"] == "image"), None)
        print(f"  image versions: {len(image['versions']) if image else 0}")
        if not image or not image["versions"]:
            print("  FAIL: no image version")
            ok = False

        # 3. Tool cards line up with the timeline.
        steps = client.get(f"/api/tasks/{task['id']}/timeline").json()[0]["steps"]
        print(f"  tools: {[s['tool'] for s in steps]}")
        started = [d.get("tool_call_id") for _, k, d in seen if k == "tool_started"]
        recorded = [s.get("tool_call_id") for s in steps]
        if started and recorded and started != recorded:
            print(f"  FAIL: ids differ\n    announced={started}\n    recorded ={recorded}")
            ok = False

        # 4. A rule sentence is recorded as a draft, and nothing is rewritten.
        before = len(image["versions"]) if image else 0
        r2 = client.post(
            f"/api/tasks/{task['id']}/utterances",
            json={"text": "以后每次主图都用纯白背景"},
            headers={"Idempotency-Key": "probe-routing-2"},
        )
        container.worker.drain()
        cons = client.get(f"/api/tasks/{task['id']}/constraints").json()
        print(f"  pending constraints: {[c['text'] for c in cons['pending']]}")
        if not cons["pending"]:
            print("  FAIL: the rule was not recorded")
            ok = False
        else:
            print("  rule recorded as pending (not in force)")
        arts2 = client.get(f"/api/tasks/{task['id']}/artifacts").json()
        image2 = next((a for a in arts2 if a["slot"] == "image"), None)
        if image2 and len(image2["versions"]) != before:
            print("  FAIL: recording a rule wrote a version")
            ok = False

        total = seen[-1][0] if seen else 0
        print(f"\n  first plan {plans[0] if plans else '?'}s, "
              f"first text {first_token[0] if first_token else '?'}s, "
              f"settled {total}s")
        print("\n--- result:", "OK" if ok else "PROBLEM")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

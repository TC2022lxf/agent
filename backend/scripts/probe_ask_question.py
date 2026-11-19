"""Probe: is `ask_question` a real suspension, or does the Run just end?

Prints the lifecycle so the answer is observed rather than argued from code reading.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_container
from app.infrastructure.storage import MemoryObjectStore
from app.main import create_app


def main() -> int:
    c = build_container(Settings(database_url="sqlite://", run_worker="off"),
                        store=MemoryObjectStore())
    with TestClient(create_app(c)) as http:
        http.container = c  # type: ignore[attr-defined]
        task = http.post(
            "/api/tasks", json={"agent_id": "image", "kind": "image", "goal": "主图"},
        ).json()
        r = http.post(
            f"/api/tasks/{task['id']}/utterances",
            json={"text": "太普通了，高级一点"},
            headers={"Idempotency-Key": "probe-k1"},
        )
        c.worker.drain()
        rid = r.json()["id"]
        run = http.get(f"/api/runs/{rid}").json()
        print(f"task kind         : image")
        print(f"RUN id            : {rid}")
        print(f"RUN status        : {run['status']}")
        print(f"RUN path          : {run['path']}")
        print(f"RUN error         : {run['error']}")
        print(f"RUN cost / held   : {run['cost']} / {run['held']}")
        print(f"TASK status       : {http.get('/api/tasks/' + task['id']).json()['status']}")
        with c.uow_factory() as uow:
            print("\nevents:")
            for e in uow.collab.events_after(rid, 0):
                print(f"  {e.type:24} {str(e.data)[:110]}")
            print("\ntool_calls:")
            for tc in uow.collab.tool_calls(rid):
                print(f"  {tc.tool_name:22} status={tc.status} id={tc.tool_call_id}")

        # Now answer it, the way the UI does: a NEW utterance, not a tool_result.
        print("\n--- the user answers with a new utterance")
        r2 = http.post(
            f"/api/tasks/{task['id']}/utterances",
            json={"text": "更突出核心卖点，语气克制", "target_slot": "image"},
            headers={"Idempotency-Key": "probe-k2"},
        )
        c.worker.drain()
        rid2 = r2.json()["id"]
        run2 = http.get(f"/api/runs/{rid2}").json()
        print(f"RUN2 status       : {run2['status']}")
        print(f"RUN2 path         : {run2['path']}")
        print(f"RUN2 version_ids  : {run2['version_ids']}")
        with c.uow_factory() as uow:
            print("RUN2 tool_calls:")
            for tc in uow.collab.tool_calls(rid2):
                print(f"  {tc.tool_name:22} status={tc.status} input={str(tc.input)[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

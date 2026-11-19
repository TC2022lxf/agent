"""Probe: after an ask_question, does the NEXT Run see the question?

Turn 1 must actually ask, so the sentence under test is a vague request.
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
from app.runtime.context import build_turn_lines, prior_messages


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
            headers={"Idempotency-Key": "q1"},
        )
        c.worker.drain()
        rid1 = r.json()["id"]

        with c.uow_factory() as uow:
            print("=== turn 1 events ===")
            for e in uow.collab.events_after(rid1, 0):
                if e.type in {"answer", "human_input_request"}:
                    print(f"  {e.type}: {str(e.data)[:200]}")
            print("\n=== turn 1 as the history builder sees it ===")
            for line in build_turn_lines(uow, uow.collab.get_task(task["id"])):
                print(f"  user    : {line.user}")
                print(f"  agent   : {line.agent_said!r}")
                print(f"  produced: {line.versions}")

        with c.uow_factory() as uow:
            msgs, _ = prior_messages(uow, uow.collab.get_task(task["id"]), "next")
            print("\n=== prior_texts handed to the NEXT run ===")
            for m in msgs:
                print(f"  | {m}")
            print("\n  >>> is the QUESTION in that history?",
                  any("想朝哪个方向改" in m or "方向" in m for m in msgs))

        print("\n--- user answers")
        r2 = http.post(
            f"/api/tasks/{task['id']}/utterances",
            json={
                "text": "更突出核心卖点，语气克制",
                "target_slot": "image",
                "answers_request_id": rid1 + ":ask_question:ask_question",
            },
            headers={"Idempotency-Key": "q2"},
        )
        c.worker.drain()
        run2 = http.get(f"/api/runs/{r2.json()['id']}").json()
        print(f"  RUN2 status={run2['status']} path={run2['path']}")

        with c.uow_factory() as uow:
            print("\n=== turn 2 as the history builder sees it ===")
            for line in build_turn_lines(uow, uow.collab.get_task(task["id"])):
                print(f"  user     : {line.user}")
                print(f"  asked    : {line.asked!r}")
                print(f"  answer_to: {line.answer_to!r}")
                print(f"  rendered : {line.render()!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

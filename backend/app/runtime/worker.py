"""Worker loop. API process only enqueues; a worker executes (decisions/0003)."""

from __future__ import annotations

import threading
import time

from app.runtime.executor import RunExecutor
from app.services.uow import UowFactory


class Worker:
    def __init__(self, uow_factory: UowFactory, executor: RunExecutor) -> None:
        self.uow_factory, self.executor = uow_factory, executor
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def process_one(self) -> bool:
        with self.uow_factory() as uow:
            run_id = uow.collab.claim_next_run()
            uow.commit()
        if run_id is None:
            return False
        self.executor.execute(run_id)
        return True

    def drain(self) -> int:
        n = 0
        while self.process_one():
            n += 1
        return n

    def start(self, poll_s: float = 0.2) -> None:
        def loop() -> None:
            while not self._stop.is_set():
                if not self.process_one():
                    time.sleep(poll_s)

        self._thread = threading.Thread(target=loop, name="run-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

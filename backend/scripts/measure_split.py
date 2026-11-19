"""Measure the Image Agent split: chat column vs canvas column, in real layout pixels.

    python scripts/measure_split.py [base_url]

Drives the real UI (no router to deep-link into): creates an image Task with a picture
through the API in a page context, then clicks 图片 Agent and picks that Task from the
source dropdown, exactly as a user would.

Proves the 50/50 request with numbers instead of eyeballing a screenshot, and checks that the
image node actually fits inside the half-width column.
"""
from __future__ import annotations

import sys
import uuid

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"
# The app has no auth yet: without an X-User-Id header the backend uses "dev-user" (docs/architecture/agent-runtime.md).
# Seeding as anything else creates a Task the page can never list.
USER = "dev-user"


def seed(page, goal: str) -> str:
    """One image Task that already has a version, so the canvas column renders at all."""
    task_id = page.evaluate(
        """async ([base, user, goal]) => {
          const H = { 'Content-Type': 'application/json', 'X-User-Id': user };
          const t = await (await fetch(base + '/api/tasks', {
            method: 'POST', headers: H,
            body: JSON.stringify({ agent_id: 'image', kind: 'image', goal: goal }),
          })).json();
          return t.id;
        }""",
        [BASE, USER, goal],
    )
    page.evaluate(
        """async ([base, user, id]) => {
          // A plain white 1000x1000 PNG, built inline so the script needs no fixture file.
          const c = document.createElement('canvas');
          c.width = c.height = 1000;
          const g = c.getContext('2d');
          g.fillStyle = '#fff'; g.fillRect(0, 0, 1000, 1000);
          g.fillStyle = '#3c6ec8'; g.fillRect(60, 60, 880, 880);
          const blob = await new Promise((ok) => c.toBlob(ok, 'image/png'));
          const fd = new FormData();
          fd.append('file', new Blob([blob], { type: 'image/png' }), 'ref.png');
          const up = await (await fetch(base + '/api/uploads', {
            method: 'POST', headers: { 'X-User-Id': user }, body: fd,
          })).json();
          await fetch(base + '/api/tasks/' + id + '/utterances', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-User-Id': user,
                       'Idempotency-Key': 'measure-' + id },
            body: JSON.stringify({ text: '这里是第一版', target_slot: 'image',
                                  upload_id: up.upload_id }),
          });
        }""",
        [BASE, USER, task_id],
    )
    return task_id


def main() -> int:
    goal = f"measure-split-{uuid.uuid4().hex[:6]}"
    widths = [1280, 1440, 1600, 1920]
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.add_init_script("localStorage.clear()")
        page.goto(BASE)
        page.wait_for_load_state("networkidle")

        task_id = seed(page, goal)
        page.reload()
        page.wait_for_load_state("networkidle")

        # Sidebar "最近" lists the Task by its goal. Match that unique goal rather than a
        # position: anything else using the app may have created a newer Task in between.
        row = page.locator('.session-row', has_text=goal).first
        row.wait_for(state="visible", timeout=15000)
        row.click()
        page.wait_for_selector('[data-testid="node-current"]', timeout=20000)
        page.wait_for_timeout(700)

        print(f"task {task_id}")
        print(f"{'viewport':>10}  {'chat':>6} {'canvas':>7}  {'share':>6}  node fits")
        for width in widths:
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_timeout(450)
            box = page.evaluate(
                """() => {
                  const w = (s) => {
                    const e = document.querySelector(s);
                    return e ? Math.round(e.getBoundingClientRect().width) : null;
                  };
                  const rect = (s) => {
                    const e = document.querySelector(s);
                    if (!e) return null;
                    const b = e.getBoundingClientRect();
                    return { w: Math.round(b.width), h: Math.round(b.height) };
                  };
                  return {
                    chat: w('.imgpage .agent-column'),
                    canvas: w('.imgpage .design-column'),
                    node: rect('[data-testid="node-current"]'),
                    viewport: rect('[data-testid="canvas-viewport"]'),
                  };
                }"""
            )
            if not box["canvas"] or not box["chat"]:
                failures.append(f"{width}: no canvas column")
                print(f"{width:>10}  {box['chat']}  {box['canvas']}  —")
                continue
            share = box["chat"] / (box["chat"] + box["canvas"])
            fits = (box["node"] is not None and box["viewport"] is not None
                    and box["node"]["w"] <= box["viewport"]["w"]
                    and box["node"]["h"] <= box["viewport"]["h"])
            ok = 0.45 <= share <= 0.55 and fits
            if not ok:
                failures.append(f"{width}: share {share:.0%} fits {fits}")
            print(f"{width:>10}  {box['chat']:>6} {box['canvas']:>7}  {share:>6.0%}  {fits}  "
                  f"{'PASS' if ok else 'FAIL'}")
        browser.close()

    if failures:
        print("\nFAILURES")
        for f in failures:
            print(" ", f)
        return 1
    print("\nPASS — 50/50 at every width, node fits the column")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

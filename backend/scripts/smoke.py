"""End-to-end smoke against a RUNNING server (default http://127.0.0.1:8000).

Start the server first:  uvicorn app.main:create_app --factory --port 8000
Then:                     python scripts/smoke.py
Covers: PDP first draft over SSE, a title edit, a standalone image edit from a circled region.
"""

from __future__ import annotations

import io
import sys
import uuid

import httpx
from PIL import Image

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
c = httpx.Client(base_url=BASE, timeout=30, headers={"X-User-Id": f"smoke-{uuid.uuid4().hex[:6]}"})


def say(task_id: str, text: str, **kw: object) -> dict:  # type: ignore[type-arg]
    r = c.post(f"/api/tasks/{task_id}/utterances", json={"text": text, **kw},
               headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    with c.stream("GET", f"/api/runs/{run_id}/events") as s:
        events = [ln[7:] for ln in s.iter_lines() if ln.startswith("event: ")]
    run = c.get(f"/api/runs/{run_id}").json()
    print(f"  run {run['status']:<9} path={run['path']} events={events}")
    assert run["status"] == "succeeded", run
    return run  # type: ignore[no-any-return]


print("PDP:")
t = c.post("/api/tasks", json={"agent_id": "amazon_pdp", "goal": "Electric razor"}).json()
say(t["id"], "帮我做第一版")
say(t["id"], "标题更突出防水")
arts = {a["slot"]: a for a in c.get(f"/api/tasks/{t['id']}/artifacts").json() if a["slot"]}
assert [v["seq"] for v in arts["title"]["versions"]] == [1, 2]
assert len(arts["bullets"]["versions"]) == 1

print("Image:")
buf = io.BytesIO()
Image.new("RGB", (1000, 1000), (255, 255, 255)).save(buf, format="PNG")
up = c.post("/api/uploads", files={"file": ("a.png", buf.getvalue(), "image/png")}).json()["upload_id"]
it = c.post("/api/tasks", json={"agent_id": "image", "kind": "image", "upload_id": up}).json()
say(it["id"], "这里改成蓝色", target_slot="image", target_region={"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2})
vs = next(a for a in c.get(f"/api/tasks/{it['id']}/artifacts").json() if a["slot"] == "image")["versions"]
assert [v["origin"] for v in vs] == ["imported", "edited"]
assert c.get(vs[1]["content"]["url"]).headers["content-type"] == "image/png"
print("credits left:", c.get("/api/me").json()["credits"])
print("OK")

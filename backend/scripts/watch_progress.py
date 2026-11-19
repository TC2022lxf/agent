"""What does the user see while waiting? Follow the SSE stream like the UI does.

    python watch_progress.py [base_url]

Prints each step event with the sentence the interface shows, plus the wall time since the
utterance was accepted. This is the check for "does the wait look alive".
"""
from __future__ import annotations

import json
import sys
import time
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
API = f"{BASE}/api"

# Mirrors frontend/src/lib/progress.ts. Kept here so the check needs no frontend build.
STAGE_TEXT = {
    "context": "正在读取偏好与约束",
    "compact": "正在整理对话",
    "interpret": "正在分析意图",
    "resume": "正在恢复上次的进度",
    "dispatch": "正在决定下一步",
    "think": "正在思考",
    "running": "正在执行",
    "tool": "正在调用工具",
    "work": "正在处理",
}
TOOL_TEXT = {
    "generate_product_image": "正在生成图片",
    "edit_product_image": "正在修改图片",
    "edit_listing": "正在写文案",
    "write_file": "正在写文件",
    "read_file": "正在读取文件",
    "compose_canvas": "正在编辑画布",
    "generate_variants": "正在生成几个版本",
}


def sentence(stage: str, detail: str) -> str:
    if stage == "running":
        name = detail.split(":", 1)[0]
        return TOOL_TEXT.get(name, STAGE_TEXT["running"])
    if stage == "tool":
        return STAGE_TEXT["tool"]
    return STAGE_TEXT.get(stage, "正在处理")


def watch(text: str, **body: object) -> None:
    user = f"watch-{uuid.uuid4().hex[:6]}"
    c = httpx.Client(timeout=300.0, headers={"X-User-Id": user})
    task = c.post(f"{API}/tasks", json={
        "agent_id": "image", "kind": "image", "goal": "主图",
    }).json()
    r = c.post(
        f"{API}/tasks/{task['id']}/utterances",
        json={"text": text, **body},
        headers={"Idempotency-Key": f"{user}-1"},
    )
    if r.status_code != 202:
        print(f"HTTP {r.status_code} {r.text[:200]}")
        return
    run_id = r.json()["id"]
    started = time.monotonic()
    print(f"\n用户说：{text}")
    print(f"{'秒':>6}  界面显示")
    print("-" * 46)

    last = ""
    with c.stream("GET", f"{API}/runs/{run_id}/events", timeout=300.0) as stream:
        for line in stream.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            stage = data.get("stage")
            if stage:
                shown = sentence(str(stage), str(data.get("detail") or ""))
                if shown != last:
                    print(f"{time.monotonic() - started:6.1f}  {shown}")
                    last = shown
            if any(k in line for k in ('"run_succeeded"',)):
                break
            # The stream is typed by an `event:` line we do not parse; a terminal status
            # shows up as the run reaching a state, so check it periodically.
            run = c.get(f"{API}/runs/{run_id}").json()
            if run["status"] in {"succeeded", "failed", "cancelled"}:
                print(f"{time.monotonic() - started:6.1f}  结束：{run['status']} "
                      f"(版本 {len(run['version_ids'])}，{run['cost']} 积分)")
                break


watch("做一张纯白背景的电商主图：一把金属电动剃须刀，商品居中，不要文字", target_slot="image")

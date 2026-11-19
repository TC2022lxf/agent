"""Simulate a real user going through every entry, over real HTTP.

Run against a live server:  python sim_user_journey.py [base_url] [user_id]
Prints one line per step: PASS / FAIL plus the reason. Exit code 1 if anything failed.
"""
from __future__ import annotations

import sys
import time
import uuid
from typing import Any

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
USER = sys.argv[2] if len(sys.argv) > 2 else f"sim-{uuid.uuid4().hex[:6]}"
API = f"{BASE}/api"

ok = 0
bad: list[str] = []


def check(label: str, cond: bool, detail: Any = "") -> None:
    global ok
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        bad.append(f"{label} :: {detail}")
        print(f"  FAIL  {label}   {str(detail)[:300]}")


c = httpx.Client(timeout=180.0, headers={"X-User-Id": USER})


def wait_run(run: dict[str, Any]) -> dict[str, Any]:
    """Utterances are async: poll until the Run reaches a terminal state."""
    deadline = time.monotonic() + 170
    while time.monotonic() < deadline:
        r = c.get(f"{API}/runs/{run['id']}")
        data = r.json()
        if data["status"] in {"succeeded", "failed", "cancelled"}:
            return data
        time.sleep(0.6)
    return {"status": "TIMEOUT", "error": "run never finished", "version_ids": []}


def say(task_id: str, text: str, **kw: Any) -> dict[str, Any]:
    r = c.post(
        f"{API}/tasks/{task_id}/utterances",
        json={"text": text, **kw},
        headers={"Idempotency-Key": f"{USER}-{uuid.uuid4().hex[:8]}"},
    )
    if r.status_code != 202:
        return {"status": f"HTTP {r.status_code}", "error": r.text, "version_ids": []}
    return wait_run(r.json())


def blob(path: str) -> httpx.Response:
    """Version content carries a relative url like /api/blobs/...; the client needs a host."""
    return c.get(path if path.startswith("http") else f"{BASE}{path}")


def task(task_id: str) -> dict[str, Any]:
    return c.get(f"{API}/tasks/{task_id}").json()


def arts(task_id: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for a in c.get(f"{API}/tasks/{task_id}/artifacts").json():
        out[str(a["slot"])] = a["versions"]
    return out


def timeline(task_id: str) -> list[dict[str, Any]]:
    return c.get(f"{API}/tasks/{task_id}/timeline").json()


print(f"\n=== 用户 {USER} · {BASE} ===")

print("\n[1] 打开应用：我是谁、有哪些 Agent、有哪些 Skill")
me = c.get(f"{API}/me").json()
check("GET /me 返回身份与积分", "credits" in me, me)
agents = {a["key"]: a for a in c.get(f"{API}/agents").json()}
check("三个入口都在", {"general", "amazon_pdp", "image"} <= set(agents), list(agents))
check("通用 Agent 聚合了 PDP 和图片的 Tool",
      {"edit_listing", "generate_product_image"} <= set(agents["general"]["tool_names"]),
      agents["general"]["tool_names"])
skills = c.get(f"{API}/skills").json()
check("Skill 登记页有内容", len(skills) >= 5, len(skills))
check("PDP 专用 Skill 只给 PDP 和通用",
      all("amazon_pdp" in s["agents"] or s["audience"] == "canvas"
          for s in skills if s["audience"] == "pdp"),
      [s["id"] for s in skills if s["audience"] == "pdp"])

print("\n[2] 加载样例商品，进入 PDP Agent 做导入优化")
samples = c.post(f"{API}/products/samples").json()
check("样例商品可用", len(samples) == 2, len(samples))
opt = next(p for p in samples if p["mode"] == "optimize")
gen_product = next(p for p in samples if p["mode"] == "generate")
pdp_task = c.post(f"{API}/tasks", json={
    "agent_id": "amazon_pdp", "goal": "优化已有 Listing",
    "product_id": opt["id"], "import_product": True,
}).json()
check("商品页路径建的是 pdp 任务", pdp_task["kind"] == "pdp", pdp_task["kind"])
check("任务状态是等你说话", pdp_task["status"] == "awaiting_user", pdp_task["status"])
imported = arts(pdp_task["id"])
check("标题已导入为第一版",
      imported.get("title") and imported["title"][0]["origin"] == "imported",
      {k: [v["origin"] for v in vs] for k, vs in imported.items()})
check("主图已导入", bool(imported.get("main_image")), list(imported))
check("副图只导入不编辑（存在即够）", bool(imported.get("secondary_image")), list(imported))
check("第一版就有基线评估",
      any(v["evaluations"] for vs in imported.values() for v in vs),
      "no evaluations")
before = task(pdp_task["id"])["current"]

print("\n[3] 只改标题，其他槽位不许动")
run = say(pdp_task["id"], "标题改短一点，更突出防水，五点不要动", target_slot="title")
check("Run 成功", run["status"] == "succeeded", run.get("error"))
after = task(pdp_task["id"])["current"]
check("标题是新版本", after["title"] != before["title"], after["title"])
check("五点没被连带覆盖", after["bullets"] == before["bullets"],
      f"{before['bullets']} -> {after['bullets']}")
check("PDP manifest 换了新版本",
      task(pdp_task["id"])["pdp_version_id"] != pdp_task["pdp_version_id"],
      task(pdp_task["id"])["pdp_version_id"])

print("\n[4] 记一条长期约束，确认前不生效")
r = c.post(f"{API}/tasks/{pdp_task['id']}/utterances", json={
    "text": "标题不要超过 60 个字符", "client_hint": "constraint",
}, headers={"Idempotency-Key": f"{USER}-cons"})
if r.status_code == 202:
    wait_run(r.json())
cons = c.get(f"{API}/tasks/{pdp_task['id']}/constraints").json()
check("约束进了待确认", len(cons["pending"]) >= 1, cons)
if cons["pending"]:
    cid = cons["pending"][0]["id"]
    check("确认前不在生效列表", all(x["id"] != cid for x in cons["effective"]), cons["effective"])
    r = c.post(f"{API}/constraints/{cid}/confirm")
    check("确认接口成功", r.status_code == 200, r.text)
    cons2 = c.get(f"{API}/tasks/{pdp_task['id']}/constraints").json()
    check("确认后生效", any(x["id"] == cid for x in cons2["effective"]), cons2["effective"])

print("\n[5] 版本树：回退到旧版继续")
titles = arts(pdp_task["id"])["title"]
if len(titles) >= 2:
    old = titles[0]
    r = c.post(f"{API}/versions/{old['id']}/make-current")
    check("从旧版继续成功", r.status_code == 200, r.text)
    check("当前指针回到旧版", task(pdp_task["id"])["current"]["title"] == old["id"],
          task(pdp_task["id"])["current"]["title"])
    check("旧版成为新版 PDP 的指针",
          c.get(f"{API}/versions/{task(pdp_task['id'])['pdp_version_id']}").json()["created_by"] == "user",
          "created_by")

print("\n[6] 通用 Agent：同一段对话里写文件、出图、写 PDP")
gen = c.post(f"{API}/tasks", json={
    "agent_id": "general", "kind": "general", "goal": "做一套推广素材",
    "product_id": gen_product["id"],
}).json()
check("通用任务已建", gen["kind"] == "general", gen["kind"])
run = say(gen["id"], "写一个活动倒计时页面，保存为 page.html")
check("写文件成功", run["status"] == "succeeded" and run["version_ids"], run.get("error"))
ga = arts(gen["id"])
check("出现 page.html 版本", bool(ga.get("page.html")), list(ga))
html = ga["page.html"][0]["content"]
check("HTML 可预览（带 url 或 text）", bool(html.get("text")), list(html))

run = say(gen["id"], "再画一张白底主图，不要文字", target_slot="image")
check("同一会话出图成功", run["status"] == "succeeded" and run["version_ids"], run.get("error"))
ga = arts(gen["id"])
check("出现 image 版本（「生成图片」按钮走的就是这条）", bool(ga.get("image")), list(ga))
check("文件没被图片覆盖", bool(ga.get("page.html")), list(ga))

run = say(gen["id"], "把标题写出来", target_slot="title")
check("同一会话写 PDP 标题成功", run["status"] == "succeeded", run.get("error"))
ga = arts(gen["id"])
check("出现 title 版本", bool(ga.get("title")), list(ga))
check("通用任务里懒创建了 PDP 产物", bool(task(gen["id"])["pdp_version_id"]),
      task(gen["id"])["pdp_version_id"])
check("三类产物并存", {"page.html", "image", "title"} <= set(ga), list(ga))

print("\n[7] 图片 Agent：独立用，圈选局部改")
img = c.post(f"{API}/tasks", json={
    "agent_id": "image", "kind": "image", "goal": "主图",
}).json()
check("图片任务没有 PDP 产物", task(img["id"])["pdp_version_id"] is None, "has pdp")
# The home template only fills the composer; the user adds what the product is before sending.
run = say(img["id"], "做一张纯白背景的电商主图：一把金属电动剃须刀，商品居中，不要文字",
          target_slot="image")
check("首版图生成", run["status"] == "succeeded", run.get("error"))
vs = arts(img["id"]).get("image", [])
check("有一版图", len(vs) == 1, len(vs))
if vs:
    v1 = vs[0]
    run = say(img["id"], "这里改成蓝色", target_slot="image",
              target_version_id=v1["id"],
              target_region={"x": 0.3, "y": 0.3, "w": 0.3, "h": 0.3})
    vs2 = arts(img["id"]).get("image", [])
    check("圈选后产生第二版", len(vs2) == 2, len(vs2))
    if len(vs2) == 2:
        check("第二版基于第一版", vs2[1]["parent_version_id"] == v1["id"], vs2[1]["parent_version_id"])
        check("走的是局部编辑工具", "edit_product_image" in [s["tool"] for s in timeline(img["id"])[-1]["steps"]],
              [s["tool"] for s in timeline(img["id"])[-1]["steps"]])
        check("图能下载", blob(vs2[1]["content"]["url"]).status_code == 200, vs2[1]["content"]["url"])

print("\n[8] 越界请求被挡，且不花冤枉钱")
pdp2 = c.post(f"{API}/tasks", json={"agent_id": "amazon_pdp", "goal": "剃须刀"}).json()
r = c.post(f"{API}/tasks/{pdp2['id']}/utterances", json={
    "text": "画一张图", "target_slot": "image",
}, headers={"Idempotency-Key": f"{USER}-bad-1"})
check("pdp 任务不接受 image 槽位", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
r = c.post(f"{API}/tasks/{pdp2['id']}/utterances", json={"text": "再说一句"})
check("缺 Idempotency-Key 被拒", r.status_code == 400, r.status_code)

print("\n[9] 接受任务后不能再改")
run = say(pdp_task["id"], "再优化一下五点")
acc = c.post(f"{API}/tasks/{pdp_task['id']}/accept")
check("接受成功", acc.status_code == 200, acc.text[:120])
check("接受后状态是 accepted", task(pdp_task["id"])["status"] == "accepted",
      task(pdp_task["id"])["status"])
r = c.post(f"{API}/tasks/{pdp_task['id']}/utterances", json={"text": "还能改吗"},
           headers={"Idempotency-Key": f"{USER}-late"})
check("接受后再发言被拒", r.status_code == 409, r.status_code)

print("\n[10] 积分与可追溯")
ledger = c.get(f"{API}/me").json()
check("余额是数字且已扣费", isinstance(ledger["credits"], int), ledger)
tl = timeline(gen["id"])
check("时间线能重建对话", len(tl) >= 3, len(tl))
check("每轮都有步骤记录", all("steps" in t for t in tl), "missing steps")
check("步骤带耗时与费用",
      any(s["duration_ms"] >= 0 and "cost" in s for t in tl for s in t["steps"]),
      "no step detail")
logs = c.get(f"{API}/admin/logs").json()
check("模型调用有日志", len(logs["llm_calls"]) > 0, len(logs["llm_calls"]))
check("工具调用有日志", len(logs["tool_calls"]) > 0, len(logs["tool_calls"]))

print("\n[11] Artifact 页与任务列表")
tasks = c.get(f"{API}/tasks").json()
check("任务列表能看到这次创建的任务", len(tasks) >= 4, len(tasks))
check("任务列表带当前版本指针", all("current" in t for t in tasks), "missing current")
prods = c.get(f"{API}/products").json()
check("商品列表可用", len(prods) >= 2, len(prods))
detail = c.get(f"{API}/products/{opt['id']}").json()
check("商品详情能列出它的任务", any(t["id"] == pdp_task["id"] for t in detail["tasks"]),
      len(detail["tasks"]))

print(f"\n=== {ok} 通过 / {len(bad)} 失败 ===")
for b in bad:
    print("  ✗", b)
sys.exit(1 if bad else 0)

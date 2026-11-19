"""Dump the conversation records of the local database as analysable JSON.

Everything the product records about a conversation already lives in tables, not in log
files: a Task, its Runs, the Feedback of each Run, the Run events, the Tool calls, the LLM
calls, the Versions and the Evaluations. This script only reads them and writes one file per
scope, so a session can be analysed without opening SQLite by hand.

    python scripts/dump_logs.py                 # every task
    python scripts/dump_logs.py --task task_x   # one task
    python scripts/dump_logs.py --db data/app.db --out data/verify/logs
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _rows(db: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = db.execute(sql, args)
    names = [d[0] for d in cur.description or []]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _json(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"{", "["}:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _json(v) for k, v in row.items()}


def dump_task(db: sqlite3.Connection, task_id: str) -> dict[str, Any]:
    task = _rows(db, "select * from tasks where id = ?", (task_id,))
    if not task:
        raise SystemExit(f"no such task: {task_id}")
    runs = _rows(db, "select * from runs where task_id = ? order by created_at", (task_id,))
    run_ids = [r["id"] for r in runs]
    marks = ",".join("?" * len(run_ids)) or "''"

    feedback = (
        _rows(db, f"select * from feedback where run_id in ({marks}) order by rowid", tuple(run_ids))
        if run_ids else []
    )
    events = (
        _rows(db, f"select * from run_events where run_id in ({marks}) order by id", tuple(run_ids))
        if run_ids else []
    )
    tools = (
        _rows(db, f"select * from tool_calls where run_id in ({marks}) order by id", tuple(run_ids))
        if run_ids else []
    )
    llms = (
        _rows(db, f"select * from llm_calls where run_id in ({marks}) order by id", tuple(run_ids))
        if run_ids else []
    )
    artifacts = _rows(db, "select * from artifacts where task_id = ?", (task_id,))
    art_ids = [a["id"] for a in artifacts]
    amarks = ",".join("?" * len(art_ids)) or "''"
    versions = (
        _rows(db, f"select * from versions where artifact_id in ({amarks}) order by seq", tuple(art_ids))
        if art_ids else []
    )
    vids = [v["id"] for v in versions]
    vmarks = ",".join("?" * len(vids)) or "''"
    evaluations = (
        _rows(db, f"select * from evaluations where version_id in ({vmarks}) order by id", tuple(vids))
        if vids else []
    )
    constraints = _rows(db, "select * from constraints where task_id = ?", (task_id,))

    return {
        "task": _clean(task[0]),
        "runs": [_clean(r) for r in runs],
        "feedback": [_clean(f) for f in feedback],
        "events": [{"type": e["type"], "data": _json(e["data"]), "run_id": e["run_id"]} for e in events],
        "tool_calls": [_clean(t) for t in tools],
        "llm_calls": [_clean(c) for c in llms],
        "artifacts": [_clean(a) for a in artifacts],
        "versions": [{"id": v["id"], "seq": v["seq"], "artifact_id": v["artifact_id"],
                      "status": v["status"], "params": _json(v["params"]),
                      "content": _json(v["content"])} for v in versions],
        "evaluations": [_clean(e) for e in evaluations],
        "constraints": [_clean(c) for c in constraints],
    }


TRANSCRIPT_OF = {
    "answer": "助手说话",
    "human_input_request": "等你确认",
    "tool_declined": "工具被拒",
    "scope_rejected": "越界拒绝",
    "constraint_pending": "约束待确认",
    "preference_proposed": "偏好提议",
}


def transcript(data: dict[str, Any]) -> list[str]:
    """The conversation as a reader would see it, Run by Run."""
    by_run: dict[str, list[dict[str, Any]]] = {}
    for f in data["feedback"]:
        by_run.setdefault(f["run_id"], []).append(f)
    events: dict[str, list[dict[str, Any]]] = {}
    for e in data["events"]:
        events.setdefault(e["run_id"], []).append(e)
    tools: dict[str, list[dict[str, Any]]] = {}
    for t in data["tool_calls"]:
        tools.setdefault(t["run_id"], []).append(t)

    out: list[str] = []
    for run in data["runs"]:
        rid = run["id"]
        out.append(f"=== Run {rid} · {run['status']} · agent={run['agent_key']} "
                   f"· cost={run['cost']} · {run.get('created_at', '')}")
        if run.get("error"):
            out.append(f"    error: {run['error']}")
        path = _json(run.get("path")) or []
        if path:
            out.append(f"    path: {' → '.join(str(p) for p in path)}")
        for f in by_run.get(rid, []):
            out.append(f"  用户: {f['text']}  [{f['interpretation']}, {f['status']}]"
                       + (f"  note={f['note']}" if f.get("note") else ""))
        for e in events.get(rid, []):
            label = TRANSCRIPT_OF.get(e["type"])
            if not label:
                continue
            payload = e["data"] or {}
            text = payload.get("text") or payload.get("reason") or json.dumps(payload, ensure_ascii=False)
            if e["type"] == "human_input_request":
                text = payload.get("question") or text
            out.append(f"  {label}: {text}")
            for o in payload.get("options") or []:
                if isinstance(o, dict):
                    out.append(f"      · 可选回复: {o.get('label') or o.get('value')}")
                else:
                    out.append(f"      · 可选回复: {o}")
        for t in tools.get(rid, []):
            cost = f" · {t['cost']} 积分" if t.get("cost") else ""
            out.append(f"  Tool {t['tool_name']} [{t['status']}]{cost} {t.get('duration_ms') or 0}ms")
            if t.get("error"):
                out.append(f"       error: {t['error']}")
        out.append("")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/app.db")
    ap.add_argument("--out", default="data/verify/logs")
    ap.add_argument("--task", default="", help="one task id; default is every task")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.is_file():
        raise SystemExit(f"database not found: {db_path.resolve()}")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(db_path))
    tasks = [args.task] if args.task else [
        r["id"] for r in _rows(db, "select id from tasks order by created_at")
    ]
    index: list[dict[str, Any]] = []
    for task_id in tasks:
        data = dump_task(db, task_id)
        (out_dir / f"{task_id}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
        )
        lines = transcript(data)
        (out_dir / f"{task_id}.txt").write_text("\n".join(lines), encoding="utf-8")
        index.append({
            "task_id": task_id,
            "kind": data["task"]["kind"],
            "status": data["task"]["status"],
            "goal": data["task"]["goal"],
            "runs": len(data["runs"]),
            "answers": sum(1 for e in data["events"] if e["type"] == "answer"),
            "versions": len(data["versions"]),
            "file": f"{task_id}.json",
        })
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"{len(index)} task(s) -> {out_dir.resolve()}")
    for row in index:
        print(f"  {row['task_id']}  {row['kind']:8} {row['status']:12} "
              f"runs={row['runs']:<3} answers={row['answers']:<3} versions={row['versions']}")


if __name__ == "__main__":
    main()

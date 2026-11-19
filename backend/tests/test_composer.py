"""Composer extras: file uploads, `/skill` narrowing, and switching the entry mid-Task."""

from __future__ import annotations

import io

import pytest

from tests.conftest import Api


def test_text_file_upload_is_readable_and_writes_no_version(api: Api) -> None:
    task = api.task("general", kind="file", goal="读一下")
    r = api.http.post(
        "/api/files",
        files={"file": ("brief.md", "# 简报\n\n卖点是防水\n", "text/markdown")},
    )
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["name"] == "brief.md" and up["readable"] is True and up["kind"] == "file"

    run = api.say(task["id"], "按这份简报写一页", attachment_ids=[up["upload_id"]])
    assert run["status"] == "succeeded"
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    # Only the file the Agent wrote; the upload itself is context, not an artifact.
    assert [a["slot"] for a in arts if a["kind"] == "file"] == ["notes.md"]


def test_binary_file_is_kept_but_not_read(api: Api) -> None:
    r = api.http.post(
        "/api/files", files={"file": ("spec.pdf", b"%PDF-1.4 binary", "application/pdf")},
    )
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["readable"] is False and up["kind"] == "file"
    blob = api.http.get(f"/api/blobs/{up['upload_id']}")
    assert blob.status_code == 200 and blob.content == b"%PDF-1.4 binary"


def test_unknown_attachment_is_rejected(api: Api) -> None:
    task = api.task("general", kind="file")
    r = api.http.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "看看这个", "attachment_ids": ["files/nope/missing.md"]},
        headers={"Idempotency-Key": "att-1"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_ATTACHMENT"


def test_image_upload_through_the_same_endpoint(api: Api) -> None:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, format="PNG")
    r = api.http.post("/api/files", files={"file": ("shot.png", buf.getvalue(), "image/png")})
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["kind"] == "image" and up["upload_id"].startswith("uploads/")


def test_slash_skill_must_belong_to_the_agent(api: Api) -> None:
    task = api.task("image", upload_id=api.upload_png())
    ok = api.http.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "圈选处换成白底", "skill_id": "image-local-edit", "agent_id": "image"},
        headers={"Idempotency-Key": "sk-1"},
    )
    assert ok.status_code == 202, ok.text
    api.c.worker.drain()

    bad = api.http.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "补关键词", "skill_id": "pdp-search-terms", "agent_id": "image"},
        headers={"Idempotency-Key": "sk-2"},
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "SKILL_NOT_FOR_AGENT"


def test_general_can_use_a_general_skill_on_a_file_task(api: Api) -> None:
    task = api.task("general", kind="file")
    run = api.say(task["id"], "帮我理一下要做什么", skill_id="brainstorming")
    assert run["status"] == "succeeded"
    assert run["agent_key"] == "general"


def test_switching_entry_keeps_one_task_and_records_the_agent(api: Api) -> None:
    task = api.task("general", kind="pdp", goal="剃须刀")
    first = api.say(task["id"], "写第一版")
    assert first["agent_key"] == "general"
    second = api.say(task["id"], "只改标题", agent_id="amazon_pdp")
    assert second["agent_key"] == "amazon_pdp"
    assert second["task_id"] == task["id"]
    runs = api.http.get(f"/api/tasks/{task['id']}/timeline").json()
    assert [r["agent_key"] for r in runs] == ["general", "amazon_pdp"]


def test_agent_that_cannot_handle_the_task_is_refused(api: Api) -> None:
    task = api.task("general", kind="file")
    r = api.http.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "写标题", "agent_id": "amazon_pdp"},
        headers={"Idempotency-Key": "sw-1"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "AGENT_CANNOT_HANDLE"


@pytest.mark.parametrize("name", [".hidden.md", ""])
def test_bad_file_names_are_refused(api: Api, name: str) -> None:
    r = api.http.post("/api/files", files={"file": (name, b"x", "text/plain")})
    assert r.status_code in {400, 422}


def test_directory_part_is_stripped_not_kept(api: Api) -> None:
    r = api.http.post("/api/files", files={"file": ("../evil.md", b"x", "text/markdown")})
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["name"] == "evil.md"
    assert ".." not in up["upload_id"]


def test_extensionless_file_is_download_only(api: Api) -> None:
    r = api.http.post("/api/files", files={"file": ("Makefile", b"all:\n", "text/plain")})
    assert r.status_code == 201, r.text
    assert r.json()["readable"] is False

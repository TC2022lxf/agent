"""Acceptance themes from docs/architecture/agent-runtime.md: feedback -> new Version, slots not overwritten,
hard constraints block, constraint confirm flow, imported baseline."""

from __future__ import annotations

import json

from app.infrastructure.gateway_fake import FakeGateway
from app.ports import JsonResult
from tests.conftest import Api


def test_first_run_creates_text_slot_versions_and_a_pdp_version(api: Api) -> None:
    t = api.task()
    run = api.say(t["id"], "帮我做第一版")
    assert run["status"] == "succeeded"
    assert "first_draft" in run["path"]
    state = api.task_state(t["id"])
    assert state["status"] == "awaiting_user"
    for slot in ("title", "bullets", "description"):
        assert len(api.slot_versions(t["id"], slot)) == 1
    assert state["current"]["main_image"] is None
    assert state["pdp_version_id"]


def test_feedback_creates_new_version_and_does_not_touch_other_slots(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    before = api.task_state(t["id"])
    run = api.say(t["id"], "标题更突出防水")
    assert run["status"] == "succeeded"
    titles = api.slot_versions(t["id"], "title")
    assert [v["seq"] for v in titles] == [1, 2]
    assert titles[1]["parent_version_id"] == titles[0]["id"]
    assert titles[0]["content"] != titles[1]["content"]  # old version kept, not overwritten
    after = api.task_state(t["id"])
    assert after["current"]["title"] == titles[1]["id"]
    assert after["current"]["bullets"] == before["current"]["bullets"]
    assert after["current"]["description"] == before["current"]["description"]
    pdp = api.http.get(f"/api/versions/{after['pdp_version_id']}").json()
    assert pdp["manifest"]["bullets"] == before["current"]["bullets"]
    assert pdp["manifest"]["title"] == titles[1]["id"]
    assert pdp["parent_version_id"] == before["pdp_version_id"]


def test_one_utterance_is_one_feedback_and_a_question_is_a_tool(api: Api) -> None:
    """One sentence, one Feedback; a question inside it is `ask_question`, not a label.

    The old route split a sentence into several Feedback rows and typed each one. Splitting
    now happens inside the loop as several tool calls, so there is nothing to split here.
    """
    t = api.task()
    api.say(t["id"], "第一版")
    before = len(api.http.get(f"/api/tasks/{t['id']}/feedback").json())
    api.say(t["id"], "标题更突出防水；为什么描述这么短？")
    fb = api.http.get(f"/api/tasks/{t['id']}/feedback").json()
    assert len(fb) - before == 1
    assert fb[-1]["interpretation"] == "parameter_patch"


def test_constraint_is_pending_until_confirmed_then_enforced(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    api.say(t["id"], "标题不要超过 20 个字符")
    cons = api.http.get(f"/api/tasks/{t['id']}/constraints").json()
    assert len(cons["pending"]) == 1 and cons["effective"] == []
    assert len(api.slot_versions(t["id"], "title")) == 1  # a constraint is not an edit
    # not confirmed -> a later title edit is NOT limited to 20
    api.say(t["id"], "标题加上充电信息")
    assert len(api.slot_versions(t["id"], "title")[-1]["content"]["text"]) > 20
    cid = cons["pending"][0]["id"]
    assert api.http.post(f"/api/constraints/{cid}/confirm").status_code == 200
    api.say(t["id"], "标题再改一下")
    assert len(api.slot_versions(t["id"], "title")[-1]["content"]["text"]) <= 20
    fb = api.http.get(f"/api/tasks/{t['id']}/feedback").json()
    assert next(f for f in fb if f["text"].startswith("标题不要超过"))["status"] == "applied"


def test_revoking_pending_constraint_dismisses_feedback(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    api.say(t["id"], "标题不要超过 20 个字符")
    cid = api.http.get(f"/api/tasks/{t['id']}/constraints").json()["pending"][0]["id"]
    api.http.post(f"/api/constraints/{cid}/revoke")
    cons = api.http.get(f"/api/tasks/{t['id']}/constraints").json()
    assert cons["pending"] == [] and cons["effective"] == []


def test_hard_rule_failure_does_not_become_current(api: Api) -> None:
    """An over-limit imported baseline is accepted as the first version, but an agent edit
    that still violates the platform rule is rejected and never becomes current."""
    t = api.task(import_listing={"title": "x" * 300, "bullets": ["b"] * 5})
    v1 = api.slot_versions(t["id"], "title")
    assert v1[0]["origin"] == "imported"  # non-compliant baseline is accepted as first version
    run = api.say(t["id"], "标题改短一点")
    assert run["status"] == "succeeded"
    titles = api.slot_versions(t["id"], "title")
    assert titles[-1]["parent_version_id"] == titles[0]["id"]
    # the fake model keeps the 300-char base -> platform rule (200) fails -> rejected
    assert titles[-1]["status"] == "rejected"
    assert api.task_state(t["id"])["current"]["title"] == titles[0]["id"]
    assert any(not e["passed"] for e in titles[-1]["evaluations"])


def test_imported_listing_is_origin_imported_and_edits_follow_edit_listing(api: Api) -> None:
    t = api.task(import_listing={"title": "Old title", "bullets": ["a"] * 5, "description": "d"})
    assert api.task_state(t["id"])["status"] == "awaiting_user"
    api.say(t["id"], "标题更突出防水")
    assert [v["origin"] for v in api.slot_versions(t["id"], "title")] == ["imported", "edited"]
    with api.c.uow_factory() as uow:
        run_id = api.http.get(f"/api/tasks/{t['id']}/feedback").json()[0]["run_id"]
        assert [c.tool_name for c in uow.collab.tool_calls(run_id)] == ["edit_listing"]


def test_make_current_on_slot_version_creates_pdp_version_for_that_slot_only(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    api.say(t["id"], "标题更突出防水")
    titles = api.slot_versions(t["id"], "title")
    r = api.http.post(f"/api/versions/{titles[0]['id']}/make-current")
    assert r.status_code == 200
    state = api.task_state(t["id"])
    assert state["current"]["title"] == titles[0]["id"]
    pdp = api.http.get(f"/api/versions/{state['pdp_version_id']}").json()
    assert pdp["created_by"] == "user" and pdp["manifest"]["title"] == titles[0]["id"]


def test_accept_requires_awaiting_user(api: Api) -> None:
    t = api.task()
    assert api.http.post(f"/api/tasks/{t['id']}/accept").status_code == 409
    api.say(t["id"], "第一版")
    assert api.http.post(f"/api/tasks/{t['id']}/accept").status_code == 200
    r = api.http.post(
        f"/api/tasks/{t['id']}/utterances",
        json={"text": "再改"},
        headers={"Idempotency-Key": "late"},
    )
    assert r.status_code == 409


class _SlotOnlyListingGateway(FakeGateway):
    """Mimic a real planner that names the slot but omits task context."""

    def __init__(self) -> None:
        self.listing_requests: list[dict[str, object]] = []

    def chat_json(self, alias, system, user, *, params=None, purpose="", reasoning=False,
                  images=None, on_delta=None):  # type: ignore[no-untyped-def]
        if purpose == "plan" and str(user).lstrip().startswith("{"):
            payload = json.loads(user)
            if payload.get("phase") == "plan":
                slots = ("title", "bullets", "description", "search_terms")
                return JsonResult(data={
                    "content": "",
                    "tool_calls": [
                        {
                            "name": "edit_listing",
                            "id": f"edit_listing:{slot}",
                            "args": {"slot": slot},
                        }
                        for slot in slots
                    ],
                    "path_note": "first_draft",
                    "declined": "",
                }, model="fake-text")
        if alias == "listing_edit" or purpose == "listing_edit":
            self.listing_requests.append(json.loads(user))
        return super().chat_json(
            alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
            images=images, on_delta=on_delta,
        )


def test_edit_listing_restores_goal_and_facts_when_planner_sends_only_a_slot(api: Api) -> None:
    product = next(
        p for p in api.http.post("/api/products/samples").json()
        if p["mode"] == "generate"
    )
    gateway = _SlotOnlyListingGateway()
    api.c.executor.gateway = gateway  # type: ignore[assignment]
    api.c.executor.loop.gateway = gateway  # type: ignore[assignment]
    api.c.executor.tools.gateway = gateway  # type: ignore[assignment]
    task = api.task("amazon_pdp", product_id=product["id"], goal="EchoByte 剃须刀")

    run = api.say(task["id"], "帮我做第一版")

    assert run["status"] == "succeeded"
    with api.c.uow_factory() as uow:
        tools = [c.tool_name for c in uow.collab.tool_calls(run["id"])]
    assert gateway.listing_requests, tools
    for request in gateway.listing_requests:
        assert request["goal"] == "EchoByte 剃须刀"
        assert request["facts"]["Brand"] == "EchoByte"
    state = api.task_state(task["id"])
    title = api.http.get(f"/api/versions/{state['current']['title']}").json()
    assert title["content"]["text"].startswith("EchoByte 剃须刀")



class _SlotOnlyRevisionGateway(_SlotOnlyListingGateway):
    """A real planner can omit both context and the user's revision instruction."""

    def __init__(self) -> None:
        super().__init__()
        self.requested_title = "Logitech M185 Wireless Mouse with USB Receiver"

    def chat_json(self, alias, system, user, *, params=None, purpose="", reasoning=False,
                  images=None, on_delta=None):  # type: ignore[no-untyped-def]
        if purpose == "plan" and str(user).lstrip().startswith("{"):
            payload = json.loads(user)
            current = payload.get("view", {}).get("current", {})
            if payload.get("phase") == "plan" and isinstance(current, dict) and current.get("title"):
                return JsonResult(data={
                    "content": "",
                    "tool_calls": [{
                        "name": "edit_listing",
                        "id": "edit_listing:title",
                        "args": {"slot": "title"},
                    }],
                    "path_note": "revision",
                    "declined": "",
                }, model="fake-text")
        if alias == "listing_edit" or purpose == "listing_edit":
            request = json.loads(user)
            self.listing_requests.append(request)
            if request.get("slot") == "title":
                instruction = str(request.get("instruction") or "")
                base = request.get("base") or {}
                text = self.requested_title if instruction else str(base.get("text") or "Untitled")
                return JsonResult(data={"content": {"text": text}}, model="fake-text")
        return super().chat_json(
            alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
            images=images, on_delta=on_delta,
        )


def test_listing_revision_passes_the_user_instruction_when_the_planner_sends_only_a_slot(
    api: Api,
) -> None:
    product = next(
        p for p in api.http.post("/api/products/samples").json()
        if p["mode"] == "generate"
    )
    gateway = _SlotOnlyRevisionGateway()
    api.c.executor.gateway = gateway  # type: ignore[assignment]
    api.c.executor.loop.gateway = gateway  # type: ignore[assignment]
    api.c.executor.tools.gateway = gateway  # type: ignore[assignment]
    task = api.task("amazon_pdp", product_id=product["id"], goal="Logitech M185")

    first = api.say(task["id"], "write the first draft")
    assert first["status"] == "succeeded", first
    before = api.task_state(task["id"])
    old_title_id = before["current"]["title"]
    old_title = api.http.get(f"/api/versions/{old_title_id}").json()["content"]["text"]
    assert all(not str(request.get("instruction") or "").strip() for request in gateway.listing_requests)

    instruction = (
        "Replace the title exactly with Logitech M185 Wireless Mouse with USB Receiver. "
        "Do not change any other slot."
    )
    revision = api.say(task["id"], instruction)

    assert revision["status"] == "succeeded", revision
    request = gateway.listing_requests[-1]
    assert request["slot"] == "title"
    assert request["base_version_id"] == old_title_id
    assert request["base"]["text"] == old_title
    assert request["instruction"] == instruction
    after = api.task_state(task["id"])
    new_title_id = after["current"]["title"]
    assert new_title_id != old_title_id
    assert api.http.get(f"/api/versions/{new_title_id}").json()["content"]["text"] == gateway.requested_title
    assert api.http.get(f"/api/versions/{old_title_id}").status_code == 200


class _EmptyListingGateway(_SlotOnlyListingGateway):
    """Return syntactically valid but empty listing copy for every slot."""

    def chat_json(self, alias, system, user, *, params=None, purpose="", reasoning=False,
                  images=None, on_delta=None):  # type: ignore[no-untyped-def]
        if alias == "listing_edit":
            request = json.loads(user)
            self.listing_requests.append(request)
            slot = request.get("slot")
            content = {"items": []} if slot in {"bullets", "search_terms"} else {"text": ""}
            return JsonResult(data={"content": content}, model="fake-text")
        return super().chat_json(
            alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
            images=images, on_delta=on_delta,
        )


def test_edit_listing_rejects_empty_model_output_before_commit(api: Api) -> None:
    product = next(
        p for p in api.http.post("/api/products/samples").json()
        if p["mode"] == "generate"
    )
    gateway = _EmptyListingGateway()
    api.c.executor.gateway = gateway  # type: ignore[assignment]
    api.c.executor.loop.gateway = gateway  # type: ignore[assignment]
    api.c.executor.tools.gateway = gateway  # type: ignore[assignment]
    task = api.task("amazon_pdp", product_id=product["id"], goal="EchoByte Razor")

    run = api.say(task["id"], "write the first draft")

    assert run["version_ids"] == []
    for slot in ("title", "bullets", "description", "search_terms"):
        assert api.slot_versions(task["id"], slot) == []
    feedback = api.http.get(f"/api/tasks/{task['id']}/feedback").json()
    assert feedback[-1]["status"] == "declined"
    with api.c.uow_factory() as uow:
        calls = uow.collab.tool_calls(run["id"])
    assert len(calls) == 4
    assert all(c.status == "error" and "bad_model_output" in (c.error or "") for c in calls)


class _BareSlotListingGateway(_SlotOnlyListingGateway):
    """Mimic a model that returns the slot body without the requested content wrapper."""

    def chat_json(self, alias, system, user, *, params=None, purpose="", reasoning=False,
                  images=None, on_delta=None):  # type: ignore[no-untyped-def]
        if alias == "listing_edit" or purpose == "listing_edit":
            request = json.loads(user)
            self.listing_requests.append(request)
            slot = request.get("slot")
            if slot == "bullets":
                data = {"items": [f"Bare bullet {i}" for i in range(1, 6)]}
            else:
                data = {"text": f"Bare {slot} text"}
            return JsonResult(data=data, model="fake-text")
        return super().chat_json(
            alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
            images=images, on_delta=on_delta,
        )


def test_edit_listing_accepts_a_bare_slot_body_from_the_model(api: Api) -> None:
    product = next(
        p for p in api.http.post("/api/products/samples").json()
        if p["mode"] == "generate"
    )
    gateway = _BareSlotListingGateway()
    api.c.executor.gateway = gateway  # type: ignore[assignment]
    api.c.executor.loop.gateway = gateway  # type: ignore[assignment]
    api.c.executor.tools.gateway = gateway  # type: ignore[assignment]
    task = api.task("amazon_pdp", product_id=product["id"], goal="EchoByte Razor")

    run = api.say(task["id"], "write the first draft")

    assert run["status"] == "succeeded", run
    bullets = api.slot_versions(task["id"], "bullets")
    assert bullets and bullets[-1]["content"]["items"] == [
        "Bare bullet 1",
        "Bare bullet 2",
        "Bare bullet 3",
        "Bare bullet 4",
        "Bare bullet 5",
    ]


class _ShortBulletsListingGateway(_SlotOnlyListingGateway):
    """Return four bullets first, as the live model did, then repair to five."""

    def __init__(self) -> None:
        super().__init__()
        self.bullet_attempts = 0

    def chat_json(self, alias, system, user, *, params=None, purpose="", reasoning=False,
                  images=None, on_delta=None):  # type: ignore[no-untyped-def]
        if alias == "listing_edit" or purpose == "listing_edit":
            request = json.loads(user)
            self.listing_requests.append(request)
            if request.get("slot") == "bullets":
                self.bullet_attempts += 1
                count = 4 if self.bullet_attempts == 1 else 5
                return JsonResult(
                    data={"items": [f"Factual bullet {i}" for i in range(1, count + 1)]},
                    model="fake-text",
                )
        return super().chat_json(
            alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
            images=images, on_delta=on_delta,
        )


def test_edit_listing_repairs_a_bullet_count_before_it_can_be_rejected(api: Api) -> None:
    product = next(
        p for p in api.http.post("/api/products/samples").json()
        if p["mode"] == "generate"
    )
    gateway = _ShortBulletsListingGateway()
    api.c.executor.gateway = gateway  # type: ignore[assignment]
    api.c.executor.loop.gateway = gateway  # type: ignore[assignment]
    api.c.executor.tools.gateway = gateway  # type: ignore[assignment]
    task = api.task("amazon_pdp", product_id=product["id"], goal="EchoByte Razor")

    run = api.say(task["id"], "write the first draft")

    assert run["status"] == "succeeded", run
    assert gateway.bullet_attempts == 2
    bullets = api.slot_versions(task["id"], "bullets")
    assert len(bullets) == 1
    assert bullets[0]["status"] == "ok"
    assert bullets[0]["content"]["items"] == [
        "Factual bullet 1",
        "Factual bullet 2",
        "Factual bullet 3",
        "Factual bullet 4",
        "Factual bullet 5",
    ]


class _SearchTermsItemsGateway(_SlotOnlyListingGateway):
    """Mimic a wrapped list-shaped search_terms response from a real model."""

    def chat_json(self, alias, system, user, *, params=None, purpose="", reasoning=False,
                  images=None, on_delta=None):  # type: ignore[no-untyped-def]
        if alias == "listing_edit" or purpose == "listing_edit":
            request = json.loads(user)
            self.listing_requests.append(request)
            slot = request.get("slot")
            if slot == "search_terms":
                return JsonResult(
                    data={"content": {"items": ["logitech m185", "wireless mouse"]}},
                    model="fake-text",
                )
            if slot == "bullets":
                data = {"items": [f"Wrapped bullet {i}" for i in range(1, 6)]}
            else:
                data = {"text": f"Wrapped {slot} text"}
            return JsonResult(data={"content": data}, model="fake-text")
        return super().chat_json(
            alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
            images=images, on_delta=on_delta,
        )


def test_edit_listing_accepts_list_shaped_search_terms(api: Api) -> None:
    product = next(
        p for p in api.http.post("/api/products/samples").json()
        if p["mode"] == "generate"
    )
    gateway = _SearchTermsItemsGateway()
    api.c.executor.gateway = gateway  # type: ignore[assignment]
    api.c.executor.loop.gateway = gateway  # type: ignore[assignment]
    api.c.executor.tools.gateway = gateway  # type: ignore[assignment]
    task = api.task("amazon_pdp", product_id=product["id"], goal="EchoByte Razor")

    run = api.say(task["id"], "write the first draft")

    assert run["status"] == "succeeded", run
    terms = api.slot_versions(task["id"], "search_terms")
    assert terms and terms[-1]["content"]["text"] == "logitech m185 wireless mouse"


class _ForeignBaseGateway(_SlotOnlyRevisionGateway):
    """A planner that tries to use another Task's title Version as the base."""

    def __init__(self, foreign_version_id: str, slot: str = "title") -> None:
        super().__init__()
        self.foreign_version_id = foreign_version_id
        self.slot = slot

    def chat_json(self, alias, system, user, *, params=None, purpose="", reasoning=False,
                  images=None, on_delta=None):  # type: ignore[no-untyped-def]
        if purpose == "plan" and str(user).lstrip().startswith("{"):
            payload = json.loads(user)
            if payload.get("phase") == "plan":
                current = payload.get("view", {}).get("current", {})
                if isinstance(current, dict) and current.get("title"):
                    return JsonResult(data={
                        "content": "",
                        "tool_calls": [{
                            "name": "edit_listing",
                            "id": "edit_listing:foreign-base",
                            "args": {
                                "slot": self.slot,
                                "base_version_id": self.foreign_version_id,
                            },
                        }],
                        "path_note": "revision",
                        "declined": "",
                    }, model="fake-text")
            if payload.get("phase") == "after_tools":
                return JsonResult(
                    data={"content": "foreign base was refused"},
                    model="fake-text",
                )
        return super().chat_json(
            alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
            images=images, on_delta=on_delta,
        )


def test_edit_listing_refuses_a_foreign_task_version_before_calling_the_model(api: Api) -> None:
    other = api.task()
    assert api.say(other["id"], "first draft")["status"] == "succeeded"
    foreign_title = api.task_state(other["id"])["current"]["title"]

    task = api.task()
    assert api.say(task["id"], "first draft")["status"] == "succeeded"
    target_title = api.task_state(task["id"])["current"]["title"]
    gateway = _ForeignBaseGateway(foreign_title)
    api.c.executor.gateway = gateway  # type: ignore[assignment]
    api.c.executor.loop.gateway = gateway  # type: ignore[assignment]
    api.c.executor.tools.gateway = gateway  # type: ignore[assignment]

    run = api.say(task["id"], "revise the title")

    assert run["status"] == "succeeded", run
    assert gateway.listing_requests == []
    assert api.task_state(task["id"])["current"]["title"] == target_title
    with api.c.uow_factory() as uow:
        tools = uow.collab.tool_calls(run["id"])
    assert tools[-1].status == "error"
    assert "base_version_id" in (tools[-1].error or "")


def test_edit_listing_refuses_an_unknown_base_version_before_calling_the_model(api: Api) -> None:
    task = api.task()
    assert api.say(task["id"], "first draft")["status"] == "succeeded"
    target_title = api.task_state(task["id"])["current"]["title"]
    gateway = _ForeignBaseGateway("ver_missing_for_this_task")
    api.c.executor.gateway = gateway  # type: ignore[assignment]
    api.c.executor.loop.gateway = gateway  # type: ignore[assignment]
    api.c.executor.tools.gateway = gateway  # type: ignore[assignment]

    run = api.say(task["id"], "revise the title")

    assert run["status"] == "succeeded", run
    assert gateway.listing_requests == []
    assert api.task_state(task["id"])["current"]["title"] == target_title
    with api.c.uow_factory() as uow:
        tools = uow.collab.tool_calls(run["id"])
    assert tools[-1].status == "error"
    assert "base_version_id" in (tools[-1].error or "")

def test_edit_listing_refuses_a_base_version_from_the_wrong_slot(api: Api) -> None:
    task = api.task()
    assert api.say(task["id"], "first draft")["status"] == "succeeded"
    current = api.task_state(task["id"])["current"]
    title_version = current["title"]
    description_version = current["description"]
    gateway = _ForeignBaseGateway(title_version, slot="description")
    api.c.executor.gateway = gateway  # type: ignore[assignment]
    api.c.executor.loop.gateway = gateway  # type: ignore[assignment]
    api.c.executor.tools.gateway = gateway  # type: ignore[assignment]

    run = api.say(task["id"], "revise the description")

    assert run["status"] == "succeeded", run
    assert gateway.listing_requests == []
    assert api.task_state(task["id"])["current"]["description"] == description_version
    with api.c.uow_factory() as uow:
        tools = uow.collab.tool_calls(run["id"])
    assert tools[-1].status == "error"
    assert "base_version_id" in (tools[-1].error or "")

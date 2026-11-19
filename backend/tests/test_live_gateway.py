"""Live smoke test against the real gateway. Skipped unless GATEWAY=openai and a key is set.

    cd backend
    $env:GATEWAY="openai"; .\\.venv\\Scripts\\python -m pytest tests/test_live_gateway.py -q

These call a paid vendor. They are marked `live`, but a plain pytest run is NOT
guaranteed to exclude them. Explicitly use `pytest -m "not live"` for offline runs
and in CI. Each test names what it proves so a failure is
actionable: a red one means the vendor shape changed, not that the product logic broke.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_dotenv
from app.container import build_container
from app.infrastructure.storage import MemoryObjectStore
from app.main import create_app

pytestmark = [pytest.mark.live, pytest.mark.serial]


def _live_settings() -> Settings:
    """Each live test costs money and time; the vendor throttles bursts.

    They must run one at a time (`-p no:randomly`, no xdist) and a failure here usually means
    "vendor was slow or throttled", not "product broke". Re-run a single test to confirm.
    """
    load_dotenv()
    if os.environ.get("GATEWAY") != "openai":
        pytest.skip("GATEWAY is not openai")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is missing")
    return Settings.from_env()


@pytest.fixture()
def live() -> TestClient:
    """One container per test, on an in-memory database.

    A shared file database would carry artifacts whose bytes live in an earlier
    MemoryObjectStore, so the preview URL would 404. In-memory keeps the vendor call real
    while everything else stays isolated.
    """
    settings = _live_settings()
    isolated = Settings(
        database_url="sqlite://",
        storage_dir=settings.storage_dir,
        gateway=settings.gateway,
        openai_base_url=settings.openai_base_url,
        openai_api_key=settings.openai_api_key,
        run_worker="off",
        initial_credits=1000,
    )
    container = build_container(isolated, store=MemoryObjectStore())
    with TestClient(create_app(container)) as client:
        client.container = container  # type: ignore[attr-defined]
        yield client


def test_web_search_and_fetch_hit_the_vendor(live: TestClient) -> None:
    """DMXAPI /v1/tools/search and /v1/tools/fetch return the documented shape."""
    c = live.container  # type: ignore[attr-defined]
    found = c.gateway.web_search("DMXAPI 介绍", count=2, need_content=False)
    results = found["results"]
    assert 1 <= len(results) <= 2
    assert results[0]["url"].startswith("http")
    assert results[0]["title"]
    page = c.gateway.web_fetch(results[0]["url"])
    assert isinstance(page["content"], str) and page["content"].strip()


def test_planner_replies_with_a_json_object(live: TestClient) -> None:
    """The planner contract: JSON object, model name echoed, tokens reported."""
    c = live.container  # type: ignore[attr-defined]
    res = c.gateway.chat_json(
        "gpt-6.1-sol",
        'Return JSON {"ok": true}.',
        '{"ping": 1}',
        purpose="plan",
    )
    assert res.data.get("ok") is True
    assert res.model
    assert res.tokens_in > 0


def test_image_generate_returns_a_png(live: TestClient) -> None:
    """The image shape on this vendor: a PNG we can open, from whichever endpoint it uses.

    The prompt is deliberately concrete. Vague prompts can come back as IMAGE_RECITATION --
    a legitimate refusal, not a shape bug, and the Tool maps it to a readable message.
    """
    import io

    from PIL import Image

    c = live.container  # type: ignore[attr-defined]
    out = c.gateway.image_generate(
        "image_generate",
        "A single matte black electric shaver standing upright, centered on a plain white "
        "background, soft studio lighting, product photography",
        512,
        "1:1",
    )
    img = Image.open(io.BytesIO(out.png))
    assert img.format == "PNG"
    assert img.size[0] > 0


def test_full_run_produces_an_image_or_explains_the_rejection(live: TestClient) -> None:
    """End to end with a real model and a real picture.

    A main-image rule failure is a correct outcome: the Version exists but is not current.
    What must never happen is silence, so the assertion is "a Version, and either it became
    current or the user was told why not".
    """
    c = live.container  # type: ignore[attr-defined]
    task = live.post(
        "/api/tasks", json={"agent_id": "image", "kind": "image", "goal": "主图"},
    ).json()
    r = live.post(
        f"/api/tasks/{task['id']}/utterances",
        json={
            "text": "做一张纯白背景的电商主图：一把金属电动剃须刀，正面直立，商品居中，不要文字",
            "target_slot": "image",
        },
        headers={"Idempotency-Key": "live-1"},
    )
    assert r.status_code == 202, r.text
    c.worker.drain()
    run = live.get(f"/api/runs/{r.json()['id']}").json()
    assert run["status"] == "succeeded", run

    arts = live.get(f"/api/tasks/{task['id']}/artifacts").json()
    image = next(a for a in arts if a["slot"] == "image")
    turns = live.get(f"/api/tasks/{task['id']}/timeline").json()
    said = [a for t in turns for a in t["answers"]]
    if not run["version_ids"]:
        # The planner may spend the turn asking instead of drawing. Silence is the bug.
        assert said, "no version and nothing said"
        return
    assert image["versions"][0]["content"]["url"].startswith("/api/blobs/")
    if image["current_version_id"]:
        assert image["current_version_id"] == run["version_ids"][0]
    else:
        assert said, "rejected without telling the user why"


def test_negated_request_still_produces_a_picture(live: TestClient) -> None:
    """The reported bug, against the real model: 不要 must not turn this into a constraint."""
    c = live.container  # type: ignore[attr-defined]
    task = live.post(
        "/api/tasks", json={"agent_id": "image", "kind": "image", "goal": "主图"},
    ).json()
    r = live.post(
        f"/api/tasks/{task['id']}/utterances",
        json={
            "text": "做一张纯白背景的电商主图：一把金属电动剃须刀，商品居中，不要文字和水印。",
            "target_slot": "image",
        },
        headers={"Idempotency-Key": "live-2"},
    )
    c.worker.drain()
    run = live.get(f"/api/runs/{r.json()['id']}").json()
    assert run["status"] == "succeeded", run
    turns = live.get(f"/api/tasks/{task['id']}/timeline").json()
    # The bug was the interpretation, not the picture: the sentence is a request for output.
    kinds = {i["kind"] for t in turns for i in t["interpretations"]}
    assert "new_constraint" not in kinds, kinds
    assert "parameter_patch" in kinds, kinds


def test_when_the_model_asks_for_more_the_user_sees_it(live: TestClient) -> None:
    """No product facts given: the model may decline to draw. Its words must reach the user.

    Previously the run was `succeeded` with no version and no message, so the screen looked
    broken. The contract is: no version => something was said.
    """
    c = live.container  # type: ignore[attr-defined]
    task = live.post(
        "/api/tasks", json={"agent_id": "image", "kind": "image", "goal": "主图"},
    ).json()
    r = live.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "做一张主图", "target_slot": "image"},
        headers={"Idempotency-Key": "live-3"},
    )
    c.worker.drain()
    run = live.get(f"/api/runs/{r.json()['id']}").json()
    assert run["status"] == "succeeded", run
    turns = live.get(f"/api/tasks/{task['id']}/timeline").json()
    said = [a for t in turns for a in t["answers"]]
    if run["version_ids"]:
        return  # the model chose to draw anyway; that is allowed
    assert said, "the model declined but the user was shown nothing"


def test_pdp_first_draft_shows_the_saved_product(live: TestClient) -> None:
    """The reported gap, against the real vendor: the picture must come from the商品图.

    Likeness cannot be judged by pixels, so the assertions are the decidable ones: the
    reference really reached the vendor, and the result is a square usable main image.

    A rule rejection is a correct outcome and is *expected* today: the vendor paints a
    near-white but not pure-white backdrop (`border white fraction 0.80–0.84`), which is the
    open problem in STATUS "下一步" item 3. So we assert on the Version's params, not on it
    becoming current.
    """
    import io

    from PIL import Image

    c = live.container  # type: ignore[attr-defined]
    samples = live.post("/api/products/samples").json()
    sample = next(p for p in samples if p["mode"] == "generate")
    task = live.post(
        "/api/tasks",
        json={"agent_id": "amazon_pdp", "goal": "做一个 PDP", "product_id": sample["id"]},
    ).json()
    assert task["meta"]["product"]["reference_key"]
    r = live.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "生成主图，纯白背景，商品居中，不要文字", "target_slot": "main_image"},
        headers={"Idempotency-Key": "live-4"},
    )
    assert r.status_code == 202, r.text
    c.worker.drain()
    run = live.get(f"/api/runs/{r.json()['id']}").json()
    assert run["status"] == "succeeded", run

    arts = live.get(f"/api/tasks/{task['id']}/artifacts").json()
    main = next(a for a in arts if a["slot"] == "main_image")
    if not main["versions"]:
        # The model may ask instead of drawing; then the user must have been told something.
        said = [a for t in live.get(f"/api/tasks/{task['id']}/timeline").json()
                for a in t["answers"]]
        assert said, "no version and nothing said"
        return

    version = main["versions"][0]
    assert version["params"]["reference"] is True
    assert version["params"]["reference_object_key"]
    assert "reference image" in version["params"]["prompt_sent"]
    png = live.get(version["content"]["url"]).content
    img = Image.open(io.BytesIO(png))
    assert img.size[0] == img.size[1], f"main image must be square, got {img.size}"
    assert img.size[0] >= 1000
    # Writes stayed inside the boundary: only the main image, plus the PDP pointer to it.
    others = [a for a in arts if a["slot"] not in {None, "main_image"}]
    assert all(not a["versions"] for a in others)

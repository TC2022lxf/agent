"""Local edit: pixel `<bbox>` in the vendor prompt and UI region on the tool call."""

from __future__ import annotations

import io

from PIL import Image

from app.image.engines import edit_prompt
from tests.conftest import Api
from tests.test_image_flow import REGION, _image_task

REGION = REGION  # re-export for clarity


def test_edit_prompt_appends_pixel_bbox() -> None:
    img = Image.new("RGB", (1000, 1000), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    text = edit_prompt("add a blue patch", buf.getvalue(), (0.4, 0.4, 0.2, 0.2))
    assert "<bbox>400 400 600 600</bbox>" in text
    assert "add a blue patch" in text


def test_edit_prompt_without_region_is_unchanged() -> None:
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert edit_prompt("  brighten  ", buf.getvalue(), None) == "brighten"


def test_circled_edit_records_region_and_bbox_prompt(api: Api) -> None:
    task = _image_task(api)
    run = api.say(task["id"], "把这里改成蓝色", target_slot="image", target_region=REGION)
    assert run["status"] == "succeeded"
    with api.c.uow_factory() as uow:
        tc = uow.collab.tool_calls(run["id"])[-1]
    assert tc.tool_name == "edit_product_image"
    assert tc.input.get("region") == REGION
    version = api.slot_versions(task["id"], "image")[-1]
    assert "<bbox>" in version["params"]["prompt_sent"]
    assert version["params"]["region"] == REGION

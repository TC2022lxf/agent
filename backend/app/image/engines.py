"""Image edit: vendor output is stored as-is. Optional `<bbox>` text guides the model when
the user circled a region; there is no programmatic crop-and-paste back onto the base."""

from __future__ import annotations

import io
from typing import Protocol

from PIL import Image

from app.ports import ModelGatewayPort

Region = tuple[float, float, float, float]  # x, y, w, h normalised 0..1


class ImageEditEngine(Protocol):
    name: str

    def edit(
        self, gateway: ModelGatewayPort, image_png: bytes, instruction: str, region: Region | None
    ) -> bytes: ...


def _box(img: Image.Image, r: Region) -> tuple[int, int, int, int]:
    x, y, w, h = r
    return (
        round(x * img.width),
        round(y * img.height),
        round((x + w) * img.width),
        round((y + h) * img.height),
    )


def edit_prompt(instruction: str, image_png: bytes, region: Region | None) -> str:
    """Append a pixel `<bbox>` tag for vendors without mask inpainting (e.g. Gemini chat)."""
    text = instruction.strip()
    if region is None:
        return text
    img = Image.open(io.BytesIO(image_png))
    x0, y0, x1, y1 = _box(img, region)
    return (
        f"{text}\n\n"
        f"Apply the change ONLY inside this axis-aligned box on the provided image "
        f"({img.width}x{img.height}px, origin top-left): "
        f"<bbox>{x0} {y0} {x1} {y1}</bbox>. "
        f"Do not add, remove or move content outside this box."
    )


class ModelEditEngine:
    """Return the vendor image unchanged. With a region, the prompt carries a pixel `<bbox>`."""

    name = "model"

    def edit(
        self, gateway: ModelGatewayPort, image_png: bytes, instruction: str, region: Region | None
    ) -> bytes:
        prompt = edit_prompt(instruction, image_png, region)
        mask = _mask_png(image_png, region) if region else None
        return gateway.image_edit("image_edit", image_png, mask, prompt).png


class CompositeEditEngine:
    """Ask the model, then paste back ONLY the region: outside pixels are unchanged by
    construction, whatever the model did."""

    name = "composite"

    def edit(
        self, gateway: ModelGatewayPort, image_png: bytes, instruction: str, region: Region | None
    ) -> bytes:
        prompt = edit_prompt(instruction, image_png, region)
        if region is None:
            return gateway.image_edit("image_edit", image_png, None, prompt).png
        original = Image.open(io.BytesIO(image_png)).convert("RGB")
        mask = _mask_png(image_png, region)
        edited = Image.open(
            io.BytesIO(gateway.image_edit("image_edit", image_png, mask, prompt).png)
        ).convert("RGB")
        if edited.size != original.size:
            edited = edited.resize(original.size)
        box = _box(original, region)
        out = original.copy()
        out.paste(edited.crop(box), box[:2])
        return _png(out)


def _mask_png(image_png: bytes, region: Region) -> bytes:
    img = Image.open(io.BytesIO(image_png))
    mask = Image.new("RGBA", img.size, (0, 0, 0, 255))  # opaque = keep
    x0, y0, x1, y1 = _box(img, region)
    mask.paste((0, 0, 0, 0), (x0, y0, x1, y1))  # transparent = editable (OpenAI convention)
    return _png(mask)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


DEFAULT_ENGINE: ImageEditEngine = ModelEditEngine()

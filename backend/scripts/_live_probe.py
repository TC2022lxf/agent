"""Prove the real vendor works, without the app in the way.

Reads the same .env the server reads and calls the gateway directly, so a failure here is the
vendor or the key, not our runtime.
"""
from __future__ import annotations

import io
import sys

from PIL import Image

from app.config import Settings, load_dotenv
from app.infrastructure.gateway_openai import OpenAIGateway

load_dotenv()
s = Settings.from_env()
print("base_url:", s.openai_base_url)
print("key set :", bool(s.openai_api_key), f"({len(s.openai_api_key)} chars)")
print("GATEWAY :", s.gateway)
if not s.openai_api_key:
    print("no key: cannot test")
    raise SystemExit(1)

gw = OpenAIGateway(s.openai_base_url, s.openai_api_key, image_capabilities=lambda: set())

print("\n-- text model gpt-6.1-sol")
try:
    r = gw.chat_json("gpt-6.1-sol", 'Return JSON {"ok": true}.', '{"ping": 1}', purpose="plan")
    print("  model:", r.model, "data:", r.data, "tokens:", r.tokens_in, r.tokens_out)
except Exception as e:  # noqa: BLE001
    print("  TEXT FAILED:", type(e).__name__, str(e)[:400])

print("\n-- image model gemini-3.1-flash-image (native Gemini shape)")
try:
    out = gw.image_generate("image_generate", "a plain light grey square", 512, "1:1")
    img = Image.open(io.BytesIO(out.png))
    print("  model:", out.model, "size:", img.size, "format:", img.format, "bytes:", len(out.png))
    print("  params:", out.params)
except Exception as e:  # noqa: BLE001
    print("  IMAGE FAILED:", type(e).__name__, str(e)[:400])

print("\n-- same, with a reference picture (what the PDP main image does)")
try:
    ref = Image.new("RGB", (600, 600), (255, 255, 255))
    # a crude "product": dark rounded block so the model has something to keep
    for x in range(180, 420):
        for y in range(120, 480):
            ref.putpixel((x, y), (40, 40, 45))
    buf = io.BytesIO()
    ref.save(buf, format="PNG")
    out = gw.image_generate(
        "image_generate",
        "Use the product in the reference image. Put it on a pure white background.",
        1024, "1:1", buf.getvalue(),
    )
    img = Image.open(io.BytesIO(out.png))
    print("  model:", out.model, "size:", img.size, "bytes:", len(out.png))
    print("  params:", out.params)
    if len(sys.argv) > 1:
        img.save(sys.argv[1])
        print("  saved to", sys.argv[1])
except Exception as e:  # noqa: BLE001
    print("  REFERENCE FAILED:", type(e).__name__, str(e)[:400])

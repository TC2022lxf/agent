"""Does the bound planner model actually accept an image? One paid call, tiny image.

A profile that does not declare `vision` gets no pictures attached (docs/architecture/agent-runtime.md), so a
model that CAN see would be needlessly blind. This asks the vendor directly instead of
guessing from the model name.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image, ImageDraw  # noqa: E402

from app.config import Settings, load_dotenv  # noqa: E402
from app.infrastructure.gateway_openai import OpenAIGateway, VendorError  # noqa: E402


def sample() -> bytes:
    """A red circle on white: an answer the model can only give if it saw the bytes."""
    img = Image.new("RGB", (256, 256), (255, 255, 255))
    ImageDraw.Draw(img).ellipse((64, 64, 192, 192), fill=(220, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    load_dotenv()
    s = Settings.from_env()
    gw = OpenAIGateway(s.openai_base_url, s.openai_api_key)
    model = s.planner_model or "gpt-6.1-sol"
    print(f"probing vision on {model}")
    try:
        res = gw.chat_json(
            model,
            'Answer in JSON {"shape": "...", "color": "..."}.',
            'What shape and colour is the figure in this image?',
            images=[sample()],
            purpose="probe-vision",
        )
    except VendorError as exc:
        print(f"VISION UNSUPPORTED: {exc.code}: {str(exc)[:300]}")
        return 2
    print(f"data: {res.data}")
    ok = "red" in str(res.data).lower() or "红" in str(res.data)
    print("VISION OK" if ok else "VISION DOUBTFUL: the answer did not mention red")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())

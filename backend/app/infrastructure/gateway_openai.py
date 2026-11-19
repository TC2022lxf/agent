"""OpenAI-protocol adapter (decisions/0008, 0022). Never imported by Tool or Runtime code.

Text models use `POST /chat/completions` with a JSON object response format.

Images are different per vendor, so this adapter probes two shapes:

1. `POST /images/generations` returning `b64_json` — the plain OpenAI image models.
2. `POST /chat/completions` with `modalities: ["text","image"]`, where the picture comes back
   as a markdown data URL inside the message content — Gemini image models on aggregator
   gateways, and the only shape they accept.

The shape is decided by the model profile's `capabilities`, not by guessing at runtime:
`image.chat` marks the chat-shaped image models. See decisions/0022.
"""

from __future__ import annotations

import base64
import io
import json
import re
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image

from app.ports import ImageResult, JsonResult

# Fallbacks when no model profile resolves the alias. Aggregators differ, so profiles win.
_ALIASES = {
    "interpret": "gpt-4o-mini",
    "listing_edit": "gpt-4o-mini",
    "image_generate": "gpt-image-1",
    "image_edit": "gpt-image-1",
}

_DATA_URL = re.compile(r"data:image/(?P<fmt>[a-zA-Z0-9]+);base64,(?P<data>[A-Za-z0-9+/=]+)")


class VendorError(Exception):
    """A vendor replied with something we cannot use. Message is safe to log, not to show."""

    def __init__(self, code: str, detail: str) -> None:
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


class OpenAIGateway:
    # Text calls answer in seconds; an image call can take minutes. One shared timeout made
    # the HTTP client give up at 120s while `generate_product_image` declares 180s, so a slow
    # picture failed *before* the Tool's own deadline — the user paid for a version that
    # never existed. Image requests therefore get their own, longer read timeout.
    TEXT_TIMEOUT_S = 120.0
    IMAGE_TIMEOUT_S = 300.0

    def __init__(
        self, base_url: str, api_key: str, timeout: float | None = None,
        resolve_model: Any = None, image_capabilities: Any = None,
    ) -> None:
        self._text_timeout = timeout if timeout is not None else self.TEXT_TIMEOUT_S
        self._image_timeout = max(self._text_timeout, self.IMAGE_TIMEOUT_S)
        self._c = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=self._text_timeout,
        )
        self._resolve = resolve_model
        # () -> set[str] for the bound image profile. `image.chat` selects the chat shape.
        self._caps = image_capabilities

    def _model(self, alias: str) -> str:
        if self._resolve is not None:
            resolved = self._resolve(alias)
            if resolved:
                return str(resolved)
        return _ALIASES.get(alias, alias)

    def _image_caps(self) -> set[str]:
        try:
            return set(self._caps() or ()) if self._caps is not None else set()
        except Exception:
            return set()

    # -- text -------------------------------------------------------------------------------
    def chat_json(
        self, alias: str, system: str, user: str, *,
        params: dict[str, Any] | None = None, purpose: str = "", reasoning: bool = False,
        images: Sequence[bytes] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> JsonResult:
        body: dict[str, Any] = {
            "model": self._model(alias),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": _user_content(user, images)},
            ],
        }
        if params:
            body.update(params)
        if on_delta is not None:
            return self._chat_stream(body, alias, purpose, reasoning, on_delta)
        r = self._c.post("/chat/completions", json=body)
        if r.status_code >= 400:
            raise VendorError("chat_failed", f"{r.status_code} {_snippet(r)}")
        payload = r.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise VendorError("chat_shape", _snippet(r)) from exc
        if not isinstance(content, str):
            raise VendorError("chat_shape", "content is not a string")
        usage = payload.get("usage") or {}
        return JsonResult(
            data=_json_object(content),
            model=payload.get("model", ""),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            purpose=purpose,
            params=params or {},
            reasoning=reasoning,
        )

    def _chat_stream(
        self, body: dict[str, Any], alias: str, purpose: str, reasoning: bool,
        on_delta: Callable[[str], None],
    ) -> JsonResult:
        """Same request with `stream: true`; the caller sees text as it arrives.

        The JSON contract is unchanged: the object is parsed after the stream ends. A caller
        that wants progressive text reads the deltas; one that only wants the result calls
        `chat_json` without `on_delta`. Some relays ignore `stream` and answer in one piece,
        so a non-event body is accepted and parsed as a normal completion.
        """
        stream_body = {**body, "stream": True, "stream_options": {"include_usage": True}}
        chunks: list[str] = []
        model, tokens_in, tokens_out = "", 0, 0
        with self._c.stream("POST", "/chat/completions", json=stream_body) as r:
            if r.status_code >= 400:
                r.read()
                raise VendorError("chat_failed", f"{r.status_code} {_snippet(r)}")
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                model = event.get("model") or model
                usage = event.get("usage") or {}
                tokens_in = usage.get("prompt_tokens") or tokens_in
                tokens_out = usage.get("completion_tokens") or tokens_out
                for choice in event.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if isinstance(piece, str) and piece:
                        chunks.append(piece)
                        on_delta(piece)
        text = "".join(chunks)
        if not text.strip():
            raise VendorError("chat_shape", "the stream carried no content")
        return JsonResult(
            data=_json_object(text), model=model, tokens_in=tokens_in, tokens_out=tokens_out,
            purpose=purpose, params={k: v for k, v in body.items() if k != "messages"},
            reasoning=reasoning,
        )

    # -- web tools (same host and key; not model calls) ------------------------------------
    def web_search(
        self, query: str, *, count: int = 5, need_content: bool = False,
        ori_question: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": query,
            "count": count,
            "need_content": need_content,
            "localization": "",
        }
        if ori_question:
            body["ori_question"] = ori_question
        r = self._c.post("/tools/search", json=body, timeout=60.0)
        if r.status_code >= 400:
            raise VendorError("web_search_failed", f"{r.status_code} {_snippet(r)}")
        data = r.json()
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise VendorError("web_search_shape", _snippet(r))
        return data

    def web_fetch(self, url: str) -> dict[str, Any]:
        r = self._c.post("/tools/fetch", json={"url": url}, timeout=60.0)
        if r.status_code >= 400:
            raise VendorError("web_fetch_failed", f"{r.status_code} {_snippet(r)}")
        data = r.json()
        if not isinstance(data, dict) or not isinstance(data.get("content"), str):
            raise VendorError("web_fetch_shape", _snippet(r))
        return data

    # -- images -----------------------------------------------------------------------------
    def image_generate(
        self, alias: str, prompt: str, size: int, aspect_ratio: str | None = None,
        reference_png: bytes | None = None,
    ) -> ImageResult:
        model = self._model("image_generate")
        if "image.chat" in self._image_caps():
            # Native Gemini endpoint: `imageConfig.aspectRatio` is honoured here, unlike the
            # OpenAI-compatible chat route (decision 0023).
            png, actual = self._gemini_image(model, prompt, reference_png, aspect_ratio)
            return ImageResult(
                png=png, model=model,
                params={
                    "size": size, "shape": "gemini", "aspect_ratio": actual,
                    "reference": reference_png is not None,
                },
            )
        if reference_png is not None:
            # `/images/generations` has no input image; a first draft that must keep the
            # product is an edit of the reference, which is what `/images/edits` does.
            return self.image_edit(
                alias, reference_png, None, prompt, aspect_ratio,
            )
        r = self._c.post(
            "/images/generations",
            json={"model": model, "prompt": prompt, "size": f"{size}x{size}"},
            timeout=self._image_timeout,
        )
        if r.status_code >= 400:
            raise VendorError("image_generate_failed", f"{r.status_code} {_snippet(r)}")
        return ImageResult(
            png=_png_from_images_response(r), model=model,
            params={"size": size, "shape": "images", "reference": False},
        )

    def image_edit(
        self, alias: str, image_png: bytes, mask_png: bytes | None, prompt: str,
        aspect_ratio: str | None = None,
    ) -> ImageResult:
        model = self._model("image_edit")
        if "image.chat" in self._image_caps():
            png, actual = self._gemini_image(model, prompt, image_png, aspect_ratio)
            return ImageResult(
                png=png, model=model,
                params={"has_mask": False, "shape": "gemini", "aspect_ratio": actual},
            )
        files = {"image": ("image.png", image_png, "image/png")}
        if mask_png:
            files["mask"] = ("mask.png", mask_png, "image/png")
        r = self._c.post(
            "/images/edits",
            data={"model": model, "prompt": prompt},
            files=files,
            timeout=self._image_timeout,
        )
        if r.status_code >= 400:
            raise VendorError("image_edit_failed", f"{r.status_code} {_snippet(r)}")
        return ImageResult(
            png=_png_from_images_response(r),
            model=model,
            params={"has_mask": mask_png is not None, "shape": "images"},
        )

    def _gemini_image(
        self, model: str, prompt: str, base_png: bytes | None, aspect_ratio: str | None,
    ) -> tuple[bytes, str]:
        """Native Gemini `generateContent`. The only route where aspect ratio is obeyed.

        The OpenAI-compatible chat route on the same gateway ignores `imageConfig` and always
        returns 1408x768 (decision 0023).
        """
        parts: list[dict[str, Any]] = [{"text": prompt}]
        if base_png is not None:
            parts.append({
                "inlineData": {
                    "mimeType": "image/png",
                    "data": base64.b64encode(base_png).decode(),
                },
            })
        cfg: dict[str, Any] = {"aspectRatio": aspect_ratio} if aspect_ratio else {}
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": cfg},
        }
        url = f"{self._gemini_base()}/models/{model}:generateContent"
        r = self._c.post(url, json=body, timeout=self._image_timeout)
        if r.status_code >= 400:
            raise VendorError("gemini_image_failed", f"{r.status_code} {_snippet(r)}")
        return _png_from_gemini(r), aspect_ratio or "auto"

    def _gemini_base(self) -> str:
        """Absolute base for Gemini. httpx would otherwise merge `/v1` + `/v1beta`."""
        parts = urlsplit(str(self._c.base_url))
        return f"{parts.scheme}://{parts.netloc}/v1beta"

    def _chat_image(self, model: str, prompt: str, base_png: bytes | None) -> bytes:
        """Fallback for gateways that only expose the OpenAI-compatible chat shape."""
        content: Any = prompt
        if base_png is not None:
            encoded = base64.b64encode(base_png).decode()
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ]
        r = self._c.post(
            "/chat/completions",
            json={
                "model": model,
                "modalities": ["text", "image"],
                "messages": [{"role": "user", "content": content}],
            },
            timeout=self._image_timeout,
        )
        if r.status_code >= 400:
            raise VendorError("image_chat_failed", f"{r.status_code} {_snippet(r)}")
        payload = r.json()
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise VendorError("image_chat_shape", _snippet(r)) from exc
        return _png_from_message(message)


def _user_content(user: str, images: Sequence[bytes] | None) -> Any:
    """Plain text unless the caller supplied pictures.

    Without pictures the request stays a plain string, which every relay accepts. With them
    the content becomes the multipart shape: the model has to see the actual picture, not a
    description of it, or it answers "I cannot see the image" about an image it just made.
    """
    if not images:
        return user
    parts: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for png in images:
        encoded = base64.b64encode(png).decode()
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{encoded}"},
        })
    return parts


def _square_hint(prompt: str) -> str:
    """Nudge a chat-shape model to a square canvas; the size field is not honoured by all."""
    if "1:1" in prompt or "square" in prompt.lower():
        return prompt
    return f"{prompt}\n\nOutput a 1:1 square image."


def _png_from_gemini(r: httpx.Response) -> bytes:
    """Native responses carry `inlineData` parts; a refusal carries a finishReason instead."""
    try:
        candidate = r.json()["candidates"][0]
    except (KeyError, IndexError) as exc:
        raise VendorError("gemini_shape", _snippet(r)) from exc
    parts = (candidate.get("content") or {}).get("parts") or []
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return _to_png(base64.b64decode(inline["data"]))
    # The model answered, but declined to draw. Surface the vendor's own reason: it is
    # actionable ("rephrase the prompt"), unlike a parse failure.
    reason = str(candidate.get("finishReason") or "")
    if reason and reason != "STOP":
        raise VendorError(
            "image_refused",
            f"{reason}: {candidate.get('finishMessage') or 'the model returned no image'}",
        )
    raise VendorError("gemini_no_image", _snippet(r))


def _png_from_message(message: dict[str, Any]) -> bytes:
    """Pull the picture out of a chat message: markdown data URL, or an `images` array."""
    texts: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    for raw in texts:
        m = _DATA_URL.search(raw)
        if m:
            return _to_png(base64.b64decode(m.group("data")))
    for image in message.get("images") or []:
        url = ""
        if isinstance(image, dict):
            url = str((image.get("image_url") or {}).get("url") or image.get("url") or "")
        elif isinstance(image, str):
            url = image
        m = _DATA_URL.search(url)
        if m:
            return _to_png(base64.b64decode(m.group("data")))
    raise VendorError("image_chat_no_image", "the reply carried no image")


def _png_from_images_response(r: httpx.Response) -> bytes:
    """`/images/*` returns `b64_json`; re-encode because the vendor format may be JPEG/WebP."""
    payload = r.json()
    try:
        item = payload["data"][0]
    except (KeyError, IndexError) as exc:
        raise VendorError("image_shape", _snippet(r)) from exc
    if item.get("b64_json"):
        return _to_png(base64.b64decode(item["b64_json"]))
    if item.get("url"):
        got = httpx.get(item["url"], timeout=60.0)
        got.raise_for_status()
        return _to_png(got.content)
    raise VendorError("image_shape", "no b64_json or url")


def _to_png(raw: bytes) -> bytes:
    """Everything downstream stores PNG: one format, no per-vendor surprises in Tools."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same problem here
        raise VendorError("image_decode", "vendor bytes are not an image") from exc
    if img.format == "PNG":
        return raw
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _json_object(content: str) -> dict[str, Any]:
    """Some models wrap JSON in a fence even when asked for json_object."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VendorError("chat_not_json", text[:200]) from exc
    if not isinstance(data, dict):
        raise VendorError("chat_not_object", text[:200])
    return data


def _snippet(r: httpx.Response) -> str:
    return (r.text or "")[:300].replace("\n", " ")

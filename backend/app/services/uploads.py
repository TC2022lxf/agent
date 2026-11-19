"""Uploaded files that are not images (docs/07). The composer's `+` sends them here.

Text-ish files are decoded so a Skill or Tool can read them; everything else is kept as
bytes and only offered as a download. Neither path creates a Version: an upload is context
for a Run, not an artifact.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import uuid4

from app.domain import slots as slot_registry

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 60_000

# Extensions the model may read as text. Anything else is bytes-only.
_READABLE = frozenset({
    "txt", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "html", "htm",
    "css", "js", "ts", "tsx", "jsx", "py", "sql", "log", "xml", "toml", "ini",
})
_IMAGE = frozenset({"png", "jpg", "jpeg", "webp"})


@dataclass(frozen=True)
class Uploaded:
    key: str
    name: str
    mime: str
    size: int
    text: str | None  # decoded body for readable files

    def to_json(self) -> dict[str, object]:
        return {
            "upload_id": self.key, "name": self.name, "mime": self.mime,
            "size": self.size, "readable": self.text is not None,
        }


class UploadRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


def safe_name(raw: str) -> str:
    name = PurePosixPath(raw.replace("\\", "/")).name.strip()
    if not name or name.startswith(".") or len(name) > 120:
        raise UploadRejected("BAD_NAME", "文件名不可用")
    return name


def is_image(name: str) -> bool:
    return slot_registry.file_extension(name) in _IMAGE


def guess_mime(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def read_upload(name: str, data: bytes) -> Uploaded:
    """Decode only what we are sure is text. A wrong guess would send binary to the model."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected("TOO_LARGE", "max 10 MB")
    ext = slot_registry.file_extension(name)
    text: str | None = None
    if ext in _READABLE:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("gb18030")
            except UnicodeDecodeError as exc:
                raise UploadRejected("BAD_ENCODING", "文本文件需要 UTF-8 或 GB18030") from exc
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + "\n…（已截断）"
    return Uploaded(
        key=f"files/{uuid4().hex}/{name}", name=name, mime=guess_mime(name),
        size=len(data), text=text,
    )


def attachment_payload(uploaded: Uploaded) -> dict[str, object]:
    """What the planner sees. Text is inlined; bytes-only files are named, not guessed."""
    out: dict[str, object] = {
        "name": uploaded.name, "upload_id": uploaded.key, "mime": uploaded.mime,
    }
    if uploaded.text is not None:
        out["text"] = uploaded.text
    return out

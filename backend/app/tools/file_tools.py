"""File artifacts for the general agent.

DeerFlow writes a sandbox path and the UI previews it. Here the same names write a
Version: the model supplies the full text, and Runtime commits it. PDF, images and
media are not written as text; those previews use a blob URL when a version has one.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain import slots as slot_registry
from app.tools.base import Tool, ToolContext, ToolError, ToolMeta


class WriteFileInput(BaseModel):
    path: str = Field(description="Single file name, such as page.html, notes.md or table.csv")
    content: str = Field(description="Full file text. Replaces the current version.")


class ReadFileInput(BaseModel):
    path: str


class FileOutput(BaseModel):
    slot: str
    content: dict[str, Any]
    params: dict[str, Any]


class WriteFileTool(Tool):
    meta = ToolMeta(
        name="write_file",
        version="1",
        description=(
            "Write one text file as a new Version. HTML, Markdown and CSV/TSV are previewed; "
            "other text is download-only. Does not write PDF, images or audio/video."
        ),
        side_effect="none",
        cost_credits=0,
        timeout_s=10,
    )
    input_model = WriteFileInput
    output_model = FileOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        del ctx
        i = WriteFileInput.model_validate(input)
        try:
            name = slot_registry.normalize_file_name(i.path)
        except ValueError:
            raise ToolError("bad_path", "path 必须是单个文件名，例如 page.html") from None
        if slot_registry.is_binary_file(name):
            raise ToolError(
                "binary_file",
                "PDF、图片和音视频不通过 write_file 写正文；有地址的版本用浏览器预览",
            )
        text = i.content
        if not text.strip():
            raise ToolError("empty_file", "content 为空，文件没有写入")
        if len(text) > slot_registry.MAX_FILE_CHARS:
            raise ToolError("file_too_large", "content 超过长度上限，文件没有写入")
        mime, media = slot_registry.file_type(name)
        return FileOutput(
            slot=name,
            content={"text": text, "filename": name, "mime": mime, "media": media},
            params={"path": name},
        )


class ReadFileTool(Tool):
    meta = ToolMeta(
        name="read_file",
        version="1",
        description="Read the current text of one file Version. Does not write a new Version.",
        side_effect="none",
        cost_credits=0,
        timeout_s=10,
        writes_version=False,
    )
    input_model = ReadFileInput
    output_model = FileOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = ReadFileInput.model_validate(input)
        try:
            name = slot_registry.normalize_file_name(i.path)
        except ValueError:
            raise ToolError("bad_path", "path 必须是单个文件名") from None
        text = ctx.extras.get("text")
        if not isinstance(text, str):
            raise ToolError("not_found", "没有这个文件的当前版本")
        mime, media = slot_registry.file_type(name)
        return FileOutput(
            slot=name,
            content={"text": text, "filename": name, "mime": mime, "media": media},
            params={"path": name},
        )

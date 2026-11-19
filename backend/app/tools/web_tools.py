"""Public web search and page fetch for the general agent (decisions/0035).

Both calls go through the gateway, which holds the vendor key. Neither writes a Version:
the model reads the result and then answers, or writes an artifact with another tool.
Page text is truncated before it re-enters the conversation.
"""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.tools.base import Tool, ToolContext, ToolError, ToolMeta

# A fetched page can be tens of thousands of characters. The model only needs enough
# to answer or to decide it must fetch a different page.
_FETCH_CHARS = 8000
_RESULT_CONTENT_CHARS = 2000
_SNIPPET_CHARS = 500


class WebSearchInput(BaseModel):
    query: str = Field(
        min_length=1, max_length=128,
        description=(
            "Search query, 1-128 characters. Operators such as site:, lang:, after: "
            "are passed through."
        ),
    )
    count: int = Field(
        default=5, ge=1, le=10,
        description="How many results to return. Default 5. Does not change the price.",
    )
    need_content: bool = Field(
        default=False,
        description=(
            "When false (default), each result is a title, url and snippet. "
            "Set true only when snippets are not enough; otherwise call web_fetch "
            "on the one or two urls you will cite."
        ),
    )
    ori_question: str | None = Field(
        default=None, max_length=128,
        description="The user's original question, when it differs from query.",
    )

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("query is blank")
        return text

    @field_validator("ori_question")
    @classmethod
    def question_or_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class WebFetchInput(BaseModel):
    url: str = Field(
        max_length=8192,
        description="One public http or https URL. No username, password, or internal host.",
    )


class WebOutput(BaseModel):
    content: dict[str, Any]


class WebSearchTool(Tool):
    meta = ToolMeta(
        name="web_search",
        version="1",
        description=(
            "Search the public web and return titles, urls and snippets. "
            "Does not write a Version. Page text is included only when need_content is true, "
            "and is truncated. Not a login-gated or internal crawl."
        ),
        side_effect="none",
        cost_credits=1,
        timeout_s=70,
        writes_version=False,
    )
    input_model = WebSearchInput
    output_model = WebOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = WebSearchInput.model_validate(input)
        try:
            raw = ctx.gateway.web_search(
                i.query, count=i.count, need_content=i.need_content,
                ori_question=i.ori_question,
            )
        except Exception as exc:  # noqa: BLE001 - vendor failures are not a type we own
            raise ToolError("web_search_failed", str(exc)[:300]) from exc
        results = []
        for item in raw.get("results") or []:
            if not isinstance(item, dict):
                continue
            row: dict[str, Any] = {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "site_name": str(item.get("site_name") or ""),
                "date": item.get("date"),
                "snippet": _trim(str(item.get("snippet") or item.get("summary") or ""), _SNIPPET_CHARS),
            }
            if i.need_content:
                row["content"] = _trim(str(item.get("content") or ""), _RESULT_CONTENT_CHARS)
            results.append(row)
        return WebOutput(content={"query": i.query, "results": results})


class WebFetchTool(Tool):
    meta = ToolMeta(
        name="web_fetch",
        version="1",
        description=(
            "Fetch one public web page and return its title and markdown body. "
            "Does not write a Version. Refuses internal hosts, credentials in the URL, "
            "and non-http schemes. Body is truncated."
        ),
        side_effect="none",
        cost_credits=1,
        timeout_s=70,
        writes_version=False,
    )
    input_model = WebFetchInput
    output_model = WebOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = WebFetchInput.model_validate(input)
        url = public_http_url(i.url)
        try:
            raw = ctx.gateway.web_fetch(url)
        except Exception as exc:  # noqa: BLE001 - vendor failures are not a type we own
            raise ToolError("web_fetch_failed", str(exc)[:300]) from exc
        body = str(raw.get("content") or "")
        if not body.strip():
            raise ToolError("empty_page", "这个地址没有返回正文")
        text = _trim(body, _FETCH_CHARS)
        return WebOutput(content={
            "title": str(raw.get("title") or ""),
            "url": url,
            "content": text,
            "truncated": len(body) > _FETCH_CHARS,
        })


def public_http_url(raw: str) -> str:
    """A URL the vendor may fetch: public http(s), no credentials, no internal host.

    The vendor fetches from its own network, so this does not protect that network.
    It stops the model from sending file:, credentialed, or loopback URLs at all.
    """
    text = raw.strip()
    if not text or len(text) > 8192:
        raise ToolError("bad_url", "url 必须是不超过 8192 字符的 http 或 https 地址")
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ToolError("bad_url", "url 必须是带主机名的 http 或 https 地址")
    if parts.username or parts.password:
        raise ToolError("bad_url", "url 不能携带用户名或密码")
    host = parts.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(
        (".local", ".internal", ".localhost")
    ):
        raise ToolError("internal_url", "不能抓取内网或本机地址")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and _blocked_ip(ip):
        raise ToolError("internal_url", "不能抓取内网或本机地址")
    return text


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（已截断）"

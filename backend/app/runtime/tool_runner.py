"""Tool call wrapper (docs/architecture/agent-runtime.md, 07): allow-list, validate, budget, timeout, validate output,
and produce the record the executor persists. Tools themselves stay free of all this."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextvars import copy_context
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.registry import Registry
from app.ports import ModelGatewayPort, ObjectStorePort
from app.tools.base import ToolContext, ToolError


@dataclass
class ToolResult:
    output: BaseModel | None
    error: ToolError | None
    cost: int
    record: dict[str, Any]


class ToolRunner:
    def __init__(self, registry: Registry, gateway: ModelGatewayPort, store: ObjectStorePort):
        self.registry, self.gateway, self.store = registry, gateway, store
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")

    def call(
        self,
        *,
        agent_key: str,
        tool_name: str,
        raw_input: dict[str, Any],
        run_id: str,
        trace_id: str,
        user_id: str,
        tool_call_id: str,
        budget_left: int,
        preferences_md: str = "",
        extras: dict[str, Any] | None = None,
    ) -> ToolResult:
        spec = self.registry.agent(agent_key)
        t0 = time.monotonic()
        tool = None
        error: ToolError | None = None
        output: BaseModel | None = None
        try:
            if tool_name not in spec.tool_names:
                raise ToolError("tool_not_allowed", f"{agent_key} may not call {tool_name}")
            tool = self.registry.tool(tool_name)
            try:
                parsed = tool.input_model.model_validate(raw_input)
            except ValidationError as e:
                raise ToolError("invalid_input", str(e)) from e
            if tool.meta.cost_credits > budget_left:
                raise ToolError("budget_exceeded", "not enough held credits for this call")
            ctx = ToolContext(
                run_id=run_id,
                trace_id=trace_id,
                user_id=user_id,
                gateway=self.gateway,
                store=self.store,
                preferences_md=preferences_md,
                extras=extras or {},
            )
            fut = self._pool.submit(copy_context().run, tool.execute, parsed, ctx)
            try:
                output = fut.result(timeout=tool.meta.timeout_s)
            except FutureTimeout as e:
                raise ToolError("timeout", f"exceeded {tool.meta.timeout_s}s") from e
            try:
                tool.output_model.model_validate(output.model_dump())
            except ValidationError as e:
                raise ToolError("invalid_output", str(e)) from e
        except ToolError as e:
            error = e
        cost = tool.meta.cost_credits if (tool and error is None) else 0
        record = {
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "agent_key": agent_key,
            "tool_name": tool_name,
            "tool_version": tool.meta.version if tool else "",
            "status": "ok" if error is None else "error",
            "input": raw_input,
            "output": output.model_dump() if output else {},
            "error": str(error) if error else None,
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "cost": cost,
        }
        return ToolResult(output=output, error=error, cost=cost, record=record)

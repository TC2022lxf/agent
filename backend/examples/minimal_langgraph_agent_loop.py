"""Minimal mirror of Ecommerce AI's production agent loop (read-only demo).

Stack:
  - LangGraph (via LangChain `create_agent`) — state machine: model ↔ tools until stop
  - Custom `BaseChatModel` — we do NOT use vendor native tool_calls; planner returns JSON
  - StructuredTool wrappers — real side effects live here (DB, gateway, events)

Run (from repo root, with backend venv):
  cd backend && .venv\\Scripts\\python examples/minimal_langgraph_agent_loop.py

Production entry: app/runtime/langgraph_loop.py → LangGraphLoop.run()
Orchestration outside the loop: app/runtime/executor.py (interpret, credits, SSE events)
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 1) Fake planner: returns the same JSON shape as PLAN_CONTRACT in prompts.py
# ---------------------------------------------------------------------------

class FakePlanner(BaseChatModel):
    """Like GatewayChatModel: one chat_json call per graph step."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    plans_done: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-planner"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(self, messages: list[Any], **kwargs: Any) -> ChatResult:
        last = messages[-1] if messages else None
        after_tool = last is not None and getattr(last, "type", "") == "tool"

        if not after_tool and self.plans_done == 0:
            self.plans_done += 1
            data = {
                "content": "先生成一版白底图。",
                "tool_calls": [{"name": "echo_work", "args": {"prompt": "white bg product"}}],
            }
        elif after_tool and self.plans_done == 1:
            self.plans_done += 1
            data = {
                "content": "",
                "tool_calls": [{
                    "name": "ask_question",
                    "args": {"question": "主体是什么？", "options": ["剃须刀", "上传图片"]},
                }],
            }
        else:
            data = {"content": "图已生成；等你确认后可以继续改。", "tool_calls": []}

        tool_calls = data.get("tool_calls") or []
        if tool_calls:
            msg = AIMessage(
                content=str(data.get("content") or ""),
                tool_calls=[
                    {
                        "name": tc["name"],
                        "args": tc.get("args") or {},
                        "id": tc.get("id") or tc["name"],
                        "type": "tool_call",
                    }
                    for tc in tool_calls
                ],
            )
        else:
            msg = AIMessage(content=str(data.get("content") or "完成"))
        return ChatResult(generations=[ChatGeneration(message=msg)])


# ---------------------------------------------------------------------------
# 2) Session: what production puts in _Session.handle()
# ---------------------------------------------------------------------------

class Session:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.answer = ""
        self.human_inputs: list[dict[str, Any]] = []

    def handle(self, name: str, args: dict[str, Any]) -> str:
        if name == "ask_question":
            payload = {
                "kind": "human_input_request",
                "question": args["question"],
                "options": args.get("options") or [],
            }
            self.human_inputs.append(payload)
            self.log.append(f"EVENT human_input_request {payload['question']!r}")
            return json.dumps({"status": "awaiting_user"})
        if name == "echo_work":
            self.log.append(f"TOOL echo_work prompt={args.get('prompt')!r}")
            return json.dumps({"status": "ok", "version_id": "ver_demo"})
        return json.dumps({"status": "error", "message": "unknown tool"})

    def note_plan(self, content: str) -> None:
        if content.strip():
            self.answer = content.strip()


def bind_tools(session: Session) -> list[StructuredTool]:
    def ask(question: str, options: list[str] | None = None) -> str:
        return session.handle("ask_question", {"question": question, "options": options or []})

    def work(prompt: str) -> str:
        return session.handle("echo_work", {"prompt": prompt})

    return [
        StructuredTool.from_function(ask, name="ask_question", description="Ask the user"),
        StructuredTool.from_function(work, name="echo_work", description="Pretend image gen"),
    ]


# ---------------------------------------------------------------------------
# 3) Graph: create_agent + checkpointer (thread_id = run_id in production)
# ---------------------------------------------------------------------------

def main() -> None:
    session = Session()
    model = FakePlanner()
    agent = create_agent(
        model,
        bind_tools(session),
        system_prompt="You are a demo agent. Reply in JSON with tool_calls.",
        checkpointer=MemorySaver(),
        name="minimal-demo",
    )

    payload = {"phase": "plan", "item": {"text": "做白底主图"}, "view": {"goal": "主图"}}
    result = agent.invoke(
        {"messages": [HumanMessage(content=json.dumps(payload, ensure_ascii=False))]},
        config={"configurable": {"thread_id": "run_demo"}, "recursion_limit": 10},
    )

    print("=== message trace (what the graph kept) ===")
    for m in result["messages"]:
        t = getattr(m, "type", "?")
        if t == "human":
            print("HUMAN", m.content[:80])
        elif t == "ai":
            tc = getattr(m, "tool_calls", None) or []
            print("AI", "tool_calls=", [x["name"] for x in tc], "content=", (m.content or "")[:60])
        elif t == "tool":
            print("TOOL", m.name, m.content[:80])

    print("\n=== session side effects (what RunExecutor would turn into events) ===")
    for line in session.log:
        print(line)
    if session.human_inputs:
        print("human_input_requests:", session.human_inputs)
    if session.answer:
        print("answer (content-only):", session.answer)


if __name__ == "__main__":
    main()

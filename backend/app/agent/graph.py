"""
The LangGraph agent.

Built as an explicit StateGraph rather than the one-line `create_react_agent`
helper, because the explicit form is what makes the ReAct loop legible and
controllable: you can see the state, the two nodes, and the conditional edge that
decides whether to loop again.

    START
      |
      v
   call_model  --- no tool calls --->  END
      |  ^
      |  | tool results appended to state
      v  |
     tools

`create_react_agent` was also being called with `state_modifier=`, a keyword that
does not exist in the pinned LangGraph version.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.agent.prompts import build_system_prompt
from app.agent.tools import ALL_TOOLS
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class AgentState(TypedDict):
    """
    What flows through the graph.

    `messages` uses the `add_messages` reducer, so each node returns only the
    messages it *adds* and LangGraph appends them. The other keys are read-only
    context: the tools receive them through InjectedState, which keeps them out
    of the model's tool schema entirely.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    workspace_id: str
    spreadsheet_path: Optional[str]
    spreadsheet_type: Optional[str]
    system_prompt: str


@lru_cache
def get_llm():
    """Built lazily so importing this module never requires an API key."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.chat_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.2,  # low: we want faithful reporting, not creative writing
    ).bind_tools(ALL_TOOLS)


async def call_model(state: AgentState) -> dict[str, Any]:
    """Reasoning step: decide whether to answer or to call a tool."""
    messages = [SystemMessage(content=state["system_prompt"]), *state["messages"]]
    response = await get_llm().ainvoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    """Conditional edge: loop back through the tools, or stop."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


@lru_cache
def get_graph():
    builder = StateGraph(AgentState)
    builder.add_node("call_model", call_model)
    builder.add_node("tools", ToolNode(ALL_TOOLS))

    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", should_continue, ["tools", END])
    builder.add_edge("tools", "call_model")  # observe, then think again

    return builder.compile()


async def run_agent(
    user_message: str,
    chat_history: list[dict[str, str]],
    workspace_id: str,
    spreadsheet_path: str | None = None,
    spreadsheet_type: str | None = None,
    spreadsheet_schema: str | None = None,
) -> dict[str, Any]:
    """Run one turn. Returns {"answer": str, "tools_used": list[str]}."""
    messages: list[AnyMessage] = []
    for msg in chat_history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=user_message))

    state: AgentState = {
        "messages": messages,
        "workspace_id": workspace_id,
        "spreadsheet_path": spreadsheet_path,
        "spreadsheet_type": spreadsheet_type,
        "system_prompt": build_system_prompt(spreadsheet_schema),
    }

    try:
        result = await get_graph().ainvoke(
            state,
            # Bounds the think→act→observe loop. Without it a confused model can
            # ping-pong between nodes and burn dozens of API calls on one question.
            config={"recursion_limit": settings.agent_recursion_limit},
        )
    except GraphRecursionError:
        logger.warning("Agent hit the recursion limit in workspace %s", workspace_id)
        return {
            "answer": (
                "I wasn't able to settle on an answer for that one. "
                "Could you try asking it a different way, or more specifically?"
            ),
            "tools_used": [],
        }

    # Which tools actually ran — the UI renders these as badges.
    tools_used: list[str] = []
    for msg in result["messages"]:
        for call in getattr(msg, "tool_calls", None) or []:
            name = call.get("name")
            if name and name not in tools_used:
                tools_used.append(name)

    answer = result["messages"][-1].content
    if isinstance(answer, list):
        # Gemini can return content as a list of parts rather than a plain string.
        answer = "".join(
            part if isinstance(part, str) else part.get("text", "") for part in answer
        )

    return {
        "answer": (answer or "").strip() or "I couldn't generate an answer for that.",
        "tools_used": tools_used,
    }

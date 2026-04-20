"""Support agent with Qdrant-backed RAG and legacy fallback."""

from __future__ import annotations

import asyncio
from typing import Any, Optional, TypedDict

from sqlalchemy import text

from backend.app.agents.base import AgentResult, get_checkpointer, make_thread_id
from backend.app.core.observability import AgentObservabilityCallback, get_logger
from backend.app.database import session_scope
from backend.domains.leads.models.support_log import SupportLog
from backend.services.chatwoot import ChatwootClient
from backend.services.llm_router import call_llm

log = get_logger("support_agent")


class SupportState(TypedDict):
    user_id: str
    account_id: Optional[int]
    conversation_id: Optional[int]
    conversation: dict[str, Any]
    customer_message: str
    kb_context: str
    reply_draft: str
    send_result: dict[str, Any]
    errors: list[str]
    run_id: str


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_user_id(payload: dict[str, Any]) -> str:
    conversation = payload.get("conversation") or {}
    candidates = [
        payload.get("user_id"),
        conversation.get("user_id"),
        (conversation.get("additional_attributes") or {}).get("user_id"),
        (conversation.get("custom_attributes") or {}).get("user_id"),
        ((conversation.get("meta") or {}).get("sender") or {}).get("id"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        return str(candidate)
    return "0"


async def kb_retriever(state: SupportState) -> SupportState:
    """Fetch the most relevant KB chunks, with Postgres fallback."""
    errors = list(state.get("errors") or [])
    kb_context = ""
    try:
        from backend.app.services.embeddings import embed_text
        from backend.app.services.qdrant_client import get_qdrant, search_kb

        query_embedding = await embed_text(state["customer_message"])
        client = await get_qdrant()
        try:
            chunks = await search_kb(client, query_embedding, state["user_id"])
        finally:
            await client.close()
        kb_context = "\n\n".join(chunks)
    except Exception as exc:
        errors.append(f"qdrant_kb_fallback: {str(exc)}")

        def _load_full_kb() -> str:
            with session_scope() as db:
                row = db.execute(
                    text("SELECT kb_text FROM user_support_config WHERE user_id = :uid"),
                    {"uid": state["user_id"]},
                ).fetchone()
                return str(row[0]) if row and row[0] else ""

        kb_context = await asyncio.to_thread(_load_full_kb)

    return {**state, "kb_context": kb_context, "errors": errors}


async def reply_drafter(state: SupportState) -> SupportState:
    """Draft a grounded support reply using the retrieved KB context."""
    system = (
        "You are a helpful customer support assistant. Reply clearly and concisely. "
        "Use the provided knowledge base context when it is relevant. "
        "If the context is empty or insufficient, answer conservatively and do not invent policies."
    )
    prompt = (
        f"Customer message:\n{state['customer_message']}\n\n"
        f"Conversation context:\n{state['conversation']}\n\n"
        f"Knowledge base context:\n{state['kb_context'] or 'No relevant KB context found.'}\n\n"
        "Write the support reply only."
    )
    reply = await call_llm(prompt, system=system, task="support_reply")
    return {**state, "reply_draft": reply}


async def send_reply(state: SupportState) -> SupportState:
    """Persist the reply and send it back to Chatwoot when possible."""

    def _persist_and_send() -> dict[str, Any]:
        with session_scope() as db:
            log_row = SupportLog(
                user_id=_safe_int(state["user_id"]),
                conversation_id=str(state["conversation_id"]) if state["conversation_id"] is not None else None,
                inbox_id=str(state["conversation"].get("inbox_id")) if state["conversation"].get("inbox_id") else None,
                user_message=state["customer_message"],
                bot_response=state["reply_draft"],
                status="responded",
            )
            db.add(log_row)
            db.flush()
            result: dict[str, Any] = {"logged": True, "log_id": log_row.id}

            if state["account_id"] and state["conversation_id"]:
                response = ChatwootClient().send_message(
                    state["account_id"],
                    state["conversation_id"],
                    state["reply_draft"],
                )
                result["chatwoot"] = response

            return result

    send_result = await asyncio.to_thread(_persist_and_send)
    return {**state, "send_result": send_result}


async def build_support_graph():
    """Compile the support graph, using a checkpointer when available."""
    try:
        from langgraph.graph import END, StateGraph
    except Exception as exc:
        raise RuntimeError("LangGraph is not available") from exc

    graph = StateGraph(SupportState)
    graph.add_node("kb_retriever", kb_retriever)
    graph.add_node("reply_drafter", reply_drafter)
    graph.add_node("send_reply", send_reply)
    graph.set_entry_point("kb_retriever")
    graph.add_edge("kb_retriever", "reply_drafter")
    graph.add_edge("reply_drafter", "send_reply")
    graph.add_edge("send_reply", END)

    try:
        checkpointer = await get_checkpointer()
    except Exception:
        checkpointer = None

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


async def run_support(payload: dict[str, Any]) -> AgentResult:
    """Run the support agent, falling back to the legacy worker on failure."""
    from backend.domains.leads.workers.support import process_chatwoot_webhook

    conversation = payload.get("conversation") or {}
    thread_user = _resolve_user_id(payload)
    thread_id = make_thread_id("support", thread_user)
    initial_state: SupportState = {
        "user_id": thread_user,
        "account_id": _safe_int((payload.get("account") or {}).get("id") or payload.get("account_id")),
        "conversation_id": _safe_int(conversation.get("id") or payload.get("conversation_id")),
        "conversation": conversation,
        "customer_message": payload.get("content") or payload.get("message") or "",
        "kb_context": "",
        "reply_draft": "",
        "send_result": {},
        "errors": [],
        "run_id": thread_id,
    }

    try:
        graph = await build_support_graph()
        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": [AgentObservabilityCallback("support", thread_user)],
        }
        result = await graph.ainvoke(initial_state, config=config)
        return {
            "success": True,
            "data": result,
            "error": None,
            "fallback_used": False,
            "run_id": thread_id,
            "agent_name": "support",
        }
    except Exception as exc:
        fallback_result = await asyncio.to_thread(process_chatwoot_webhook, payload)
        log.warning("support_agent_failed_using_fallback", error=str(exc), user_id=thread_user)
        return {
            "success": True,
            "data": fallback_result,
            "error": str(exc),
            "fallback_used": True,
            "run_id": thread_id,
            "agent_name": "support",
        }

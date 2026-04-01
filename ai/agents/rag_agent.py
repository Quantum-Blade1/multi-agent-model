"""
RAG Agent module.

Retrieves regulatory context via the RAG pipeline and enriches
the agent state with relevant compliance clauses.
"""

import logging

from ai.core.schemas import AgentState

logger = logging.getLogger(__name__)

# Global retriever for dependency injection
_rag_retriever = None


async def init_query_handler(retriever):
    """Initialize the global RAG retriever."""
    global _rag_retriever
    _rag_retriever = retriever


def _retrieve_context(query: str) -> list[dict]:
    """Use the injected retriever when available, otherwise build a QueryHandler."""
    if _rag_retriever is not None:
        if hasattr(_rag_retriever, "retrieve"):
            return _rag_retriever.retrieve(query=query, top_k=5)
        if hasattr(_rag_retriever, "handle"):
            return _rag_retriever.handle(query=query)
        raise TypeError("Injected RAG retriever must define retrieve() or handle()")

    from ai.rag.query_handler import QueryHandler

    handler = QueryHandler()
    return handler.handle(query=query)


def rag_agent(state: AgentState) -> AgentState:
    """
    Query the RAG pipeline and attach retrieved regulatory context to state.

    Populates ``state["rag_context"]`` with the concatenated clause texts and
    ``state["agent_outputs"]["rag_agent"]`` with:
        - ``clauses_found`` (int)  — number of chunks retrieved
        - ``top_clauses``   (list) — list of ``{clause_id, text, score}`` dicts

    Args:
        state: Current agent graph state.

    Returns:
        Updated AgentState with RAG retrieval results.
    """
    try:
        results = _retrieve_context(query=state["query"])

        top_clauses = [
            {
                "clause_id": r.get("clause_id", ""),
                "text": r.get("text", ""),
                "score": r.get("score", 0.0),
            }
            for r in results
        ]

        # Build a readable context string for downstream agents / LLM prompts
        context_parts = [
            f"[{r['clause_id']}] {r['text']}" for r in top_clauses if r["text"]
        ]
        state["rag_context"] = "\n\n".join(context_parts)

        state["agent_outputs"]["rag_agent"] = {
            "clauses_found": len(top_clauses),
            "top_clauses": top_clauses,
        }

        logger.info("rag_agent: retrieved %d clauses.", len(top_clauses))

    except Exception as exc:
        logger.warning("rag_agent: retrieval failed — %s", exc)
        state["rag_context"] = ""
        state["agent_outputs"]["rag_agent"] = {
            "clauses_found": 0,
            "top_clauses": [],
        }

    return state

"""
Temporal Agent module.

Checks document expiry dates and flags any expired or soon-to-expire
documents in the compliance request.
"""

import logging
from datetime import date, datetime

from ai.schemas import AgentState

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> date | None:
    """Try common date formats and return a date, or None on failure."""
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def temporal_agent(state: AgentState) -> AgentState:
    """
    Validate document expiry dates from user metadata.

    Reads ``state.user_data["documents_meta"]`` — expected to be a list of
    dicts, each with at least:
        - ``doc_type``    (str) — e.g. "aadhaar", "pan", "address_proof"
        - ``expiry_date`` (str) — date string in a common format

    Populates ``state.agent_outputs["temporal_agent"]`` with:
        - ``expired_docs`` (list) — list of ``{doc_type, expiry_date}`` dicts
        - ``all_valid``    (bool) — True if no documents are expired

    Args:
        state: Current agent graph state.

    Returns:
        Updated AgentState with temporal validation results.
    """
    expired_docs: list[dict[str, str]] = []

    try:
        documents_meta = state.user_data.get("documents_meta", [])

        if not isinstance(documents_meta, list):
            logger.warning(
                "temporal_agent: 'documents_meta' is not a list — skipping."
            )
            documents_meta = []

        today = date.today()

        for doc in documents_meta:
            if not isinstance(doc, dict):
                logger.warning("temporal_agent: skipping non-dict entry in documents_meta.")
                continue

            doc_type = doc.get("doc_type", "unknown")
            expiry_str = doc.get("expiry_date", "")

            if not expiry_str:
                logger.warning(
                    "temporal_agent: no expiry_date for doc_type=%s — skipping.",
                    doc_type,
                )
                continue

            expiry = _parse_date(str(expiry_str))

            if expiry is None:
                logger.warning(
                    "temporal_agent: unparseable expiry_date '%s' for doc_type=%s.",
                    expiry_str,
                    doc_type,
                )
                continue

            if expiry < today:
                expired_docs.append(
                    {"doc_type": doc_type, "expiry_date": str(expiry)}
                )

    except Exception as exc:
        logger.warning("temporal_agent: check failed — %s", exc)

    all_valid = len(expired_docs) == 0

    state["agent_outputs"]["temporal_agent"] = {
        "expired_docs": expired_docs,
        "all_valid": all_valid,
    }

    logger.info(
        "temporal_agent: all_valid=%s, expired=%d", all_valid, len(expired_docs)
    )
    return state

"""
Document Agent module.

Validates the presence and format of compliance documents (S3 URLs)
submitted in the user's request.
"""

import logging

from ai.core.schemas import AgentState

logger = logging.getLogger(__name__)


def document_agent(state: AgentState) -> AgentState:
    """
    Check that required documents are present and S3 URLs are non-empty.

    Populates state with:
        - doc_check_passed (bool) — True if all checks pass
        - missing_docs (list) — names of expected but missing document types

    Args:
        state: Current agent graph state.

    Returns:
        Updated AgentState with document validation results.
    """
    missing: list[str] = []
    issues: list[str] = []

    # --- Check that the documents list itself exists and is non-empty -------
    documents = state["documents"]
    if not documents:
        issues.append("No documents were submitted.")
        logger.warning("document_agent: documents list is empty.")
    else:
        for idx, doc in enumerate(documents):
            if not isinstance(doc, dict):
                issues.append(f"Document at index {idx} is not a dict.")
                continue
            url = doc.get("url", "")
            if not url or not url.strip():
                issues.append(f"Document {doc.get('type', 'unknown')} has an empty URL.")
            elif not url.startswith("s3://"):
                issues.append(f"Document {doc.get('type', 'unknown')} is not a valid S3 URL: {url}")

    # --- Check expected document types via user_data hints ------------------
    expected_docs = state["user_data"].get("required_documents", [])
    provided_labels = state["user_data"].get("provided_documents", [])

    if expected_docs:
        for doc_type in expected_docs:
            if doc_type not in provided_labels:
                missing.append(doc_type)

    if missing:
        issues.append(f"Missing required document types: {missing}")

    valid = len(issues) == 0

    state["doc_check_passed"] = valid
    state["missing_docs"] = missing

    logger.info("document_agent: valid=%s, issues=%d", valid, len(issues))
    return state

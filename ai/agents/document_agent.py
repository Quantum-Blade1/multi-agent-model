"""
Document Agent module.

Validates the presence and format of compliance documents (S3 URLs)
submitted in the user's request.
"""

import logging

from ai.schemas import AgentState

logger = logging.getLogger(__name__)


def document_agent(state: AgentState) -> AgentState:
    """
    Check that required documents are present and S3 URLs are non-empty.

    Populates ``state.agent_outputs["document_agent"]`` with:
        - ``valid``   (bool)  — True if all checks pass
        - ``missing`` (list)  — names of expected but missing document types
        - ``issues``  (list)  — descriptions of any problems found

    Args:
        state: Current agent graph state.

    Returns:
        Updated AgentState with document validation results.
    """
    missing: list[str] = []
    issues: list[str] = []

    # --- Check that the documents list itself exists and is non-empty -------
    documents = state.documents
    if not documents:
        issues.append("No documents were submitted.")
        logger.warning("document_agent: documents list is empty.")
    else:
        for idx, url in enumerate(documents):
            if not isinstance(url, str) or not url.strip():
                issues.append(f"Document at index {idx} has an empty or invalid URL.")
            elif not url.startswith("s3://"):
                issues.append(
                    f"Document at index {idx} is not a valid S3 URL: {url}"
                )

    # --- Check expected document types via user_data hints ------------------
    expected_docs = state.user_data.get("required_documents", [])
    provided_labels = state.user_data.get("provided_documents", [])

    if expected_docs:
        for doc_type in expected_docs:
            if doc_type not in provided_labels:
                missing.append(doc_type)

    if missing:
        issues.append(f"Missing required document types: {missing}")

    valid = len(issues) == 0

    state.agent_outputs["document_agent"] = {
        "valid": valid,
        "missing": missing,
        "issues": issues,
    }

    logger.info("document_agent: valid=%s, issues=%d", valid, len(issues))
    return state

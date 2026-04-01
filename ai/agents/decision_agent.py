"""
Decision Agent module.

Aggregates outputs from all upstream compliance agents, invokes the LLM
via Bedrock to synthesise a final compliance decision, and parses the
response into a structured ComplianceOutput.
"""

import json
import logging
from typing import Optional

from ai.prompts.compliance_prompts import (
    DECISION_AGENT_PROMPT,
    FORMAT_INSTRUCTION,
    SYSTEM_PROMPT,
)
from ai.schemas import AgentState, ComplianceOutput, ComplianceStatus
from ai.tools.function_registry import BedrockLLMClient, get_bedrock_client

logger = logging.getLogger(__name__)

# Global client instance for dependency injection
_bedrock_client: Optional[BedrockLLMClient] = None


def set_bedrock_client(client: BedrockLLMClient) -> None:
    """Set the global Bedrock client for the decision agent."""
    global _bedrock_client
    _bedrock_client = client


def _normalize_status(raw: str) -> ComplianceStatus:
    """Map LLM / JSON status strings to ComplianceStatus (case-insensitive)."""
    key = raw.strip().lower()
    mapping = {
        "approved": ComplianceStatus.APPROVED,
        "rejected": ComplianceStatus.REJECTED,
        "review": ComplianceStatus.REVIEW,
    }
    return mapping.get(key, ComplianceStatus.REVIEW)


def decision_agent(state: AgentState) -> AgentState:
    """
    Synthesise a final compliance decision from all upstream agent outputs.

    Workflow:
        1. Collect ``state["agent_outputs"]`` and ``state["rag_context"]``.
        2. Build a prompt using ``DECISION_AGENT_PROMPT`` + ``FORMAT_INSTRUCTION``.
        3. Call ``BedrockLLMClient.invoke_with_fallback()`` (with fallback on failure).
        4. Parse the JSON response into a ``ComplianceOutput``.
        5. Set ``state["compliance_output"]``.

    On JSON parse failure the decision defaults to
    ``status=REVIEW``, ``reason="Decision parsing failed"``.

    Args:
        state: Current agent graph state.

    Returns:
        Updated AgentState with ``compliance_output`` populated.
    """
    request_id = state["request_id"]
    correlation_id = state["correlation_id"]

    try:
        client = _bedrock_client if _bedrock_client is not None else get_bedrock_client()

        agent_outputs_str = json.dumps(state["agent_outputs"], indent=2, default=str)

        user_prompt_parts = [
            DECISION_AGENT_PROMPT.format(
                agent_outputs=agent_outputs_str,
                regulatory_context=state["rag_context"] or "(none)",
            ),
        ]

        if state["rag_context"]:
            user_prompt_parts.append(
                f"Regulatory reference context:\n{state['rag_context']}"
            )

        user_prompt_parts.append(FORMAT_INSTRUCTION)
        user_prompt = "\n\n".join(user_prompt_parts)

        system_prompt = SYSTEM_PROMPT
        raw_response = client.invoke_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        state["compliance_output"] = _parse_response(
            raw_response, request_id=request_id, correlation_id=correlation_id
        )

    except Exception as exc:
        logger.warning("decision_agent: unexpected error — %s", exc)
        state["compliance_output"] = _fallback_decision(
            reason=f"Decision agent encountered an error: {exc}",
            request_id=request_id,
            correlation_id=correlation_id,
        )

    out = state["compliance_output"]
    logger.info(
        "decision_agent: status=%s, confidence=%s",
        out.status.value if out else "N/A",
        out.confidence if out else "N/A",
    )
    return state


def _parse_response(
    raw: str, *, request_id: str, correlation_id: str | None
) -> ComplianceOutput:
    """
    Attempt to parse a raw LLM response string into a ComplianceOutput.

    Falls back to a Review decision if parsing fails.
    """
    try:
        data = json.loads(raw)
        status = _normalize_status(str(data.get("status", "review")))
        return ComplianceOutput(
            request_id=request_id,
            correlation_id=correlation_id,
            status=status,
            reason=data.get("reason", ""),
            clauses=data.get("clauses", []),
            confidence=float(data.get("confidence", 0.0)),
            rules_used=data.get("rules_used", []),
            agent_errors=[],
            short_circuit_reason=None,
            processing_ms=None,
        )
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning("decision_agent: failed to parse LLM response — %s", exc)
        return _fallback_decision(
            reason="Decision parsing failed",
            request_id=request_id,
            correlation_id=correlation_id,
        )


def _fallback_decision(
    reason: str, *, request_id: str, correlation_id: str | None
) -> ComplianceOutput:
    """Return a safe fallback Review decision."""
    return ComplianceOutput(
        request_id=request_id,
        correlation_id=correlation_id,
        status=ComplianceStatus.REVIEW,
        reason=reason,
        clauses=[],
        confidence=0.0,
        rules_used=[],
        agent_errors=[],
        short_circuit_reason=None,
        processing_ms=None,
    )

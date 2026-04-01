"""
Decision Agent module.

Aggregates outputs from all upstream compliance agents, invokes the LLM
via Bedrock to synthesise a final compliance decision, and parses the
response into a structured ComplianceOutput.
"""

import json
import logging

from ai.prompts.compliance_prompts import (
    DECISION_AGENT_PROMPT,
    FORMAT_INSTRUCTION,
    RAG_CONTEXT_PROMPT,
    SYSTEM_PROMPT,
)
from ai.schemas import AgentState, ComplianceOutput, ComplianceStatus
from ai.tools.function_registry import BedrockLLMClient, get_bedrock_client

logger = logging.getLogger(__name__)


def decision_agent(state: AgentState) -> AgentState:
    """
    Synthesise a final compliance decision from all upstream agent outputs.

    Workflow:
        1. Collect ``state.agent_outputs`` and ``state.rag_context``.
        2. Build a prompt using ``DECISION_AGENT_PROMPT`` + ``FORMAT_INSTRUCTION``.
        3. Call ``BedrockLLMClient.invoke()`` (with fallback on failure).
        4. Parse the JSON response into a ``ComplianceOutput``.
        5. Set ``state.final_decision``.

    On JSON parse failure the decision defaults to
    ``status="Review", reason="Decision parsing failed"``.

    Args:
        state: Current agent graph state.

    Returns:
        Updated AgentState with ``final_decision`` populated.
    """
    try:
        client: BedrockLLMClient = get_bedrock_client()

        # --- Build the user prompt ------------------------------------------------
        agent_outputs_str = json.dumps(state.agent_outputs, indent=2, default=str)

        user_prompt_parts = [
            DECISION_AGENT_PROMPT.format(agent_outputs=agent_outputs_str),
        ]

        if state.rag_context:
            user_prompt_parts.append(
                f"Regulatory reference context:\n{state.rag_context}"
            )

        user_prompt_parts.append(FORMAT_INSTRUCTION)
        user_prompt = "\n\n".join(user_prompt_parts)

        # --- Call the LLM ---------------------------------------------------------
        system_prompt = SYSTEM_PROMPT
        raw_response = client.invoke_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        # --- Parse the response ---------------------------------------------------
        state.final_decision = _parse_response(raw_response)

    except Exception as exc:
        logger.warning("decision_agent: unexpected error — %s", exc)
        state.final_decision = _fallback_decision(
            reason=f"Decision agent encountered an error: {exc}"
        )

    logger.info(
        "decision_agent: status=%s, confidence=%s",
        state.final_decision.status.value if state.final_decision else "N/A",
        state.final_decision.confidence if state.final_decision else "N/A",
    )
    return state


def _parse_response(raw: str) -> ComplianceOutput:
    """
    Attempt to parse a raw LLM response string into a ComplianceOutput.

    Falls back to a Review decision if parsing fails.
    """
    try:
        data = json.loads(raw)
        return ComplianceOutput(
            status=ComplianceStatus(data["status"]),
            reason=data.get("reason", ""),
            clauses=data.get("clauses", []),
            confidence=float(data.get("confidence", 0.0)),
            rules_used=data.get("rules_used", []),
        )
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning("decision_agent: failed to parse LLM response — %s", exc)
        return _fallback_decision(reason="Decision parsing failed")


def _fallback_decision(reason: str) -> ComplianceOutput:
    """Return a safe fallback Review decision."""
    return ComplianceOutput(
        status=ComplianceStatus.REVIEW,
        reason=reason,
        clauses=[],
        confidence=0.0,
        rules_used=[],
    )

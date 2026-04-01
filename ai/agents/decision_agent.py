"""
Decision Agent module.

Aggregates outputs from all upstream compliance agents, invokes the LLM
via Bedrock to synthesise a final compliance decision, and parses the
response into a structured ComplianceOutput.

The agent is async so it can call the :class:`LiveConfidenceAdjuster`
(which reads the penalty from :class:`RuleEngine` via DynamoDB) and the
async ``build_decision_prompt`` (which fetches the latest calibration
report).  LangGraph handles async nodes natively via ``ainvoke``.
"""

import json
import logging
from typing import Optional

from ai.prompts.compliance_prompts import (
    FORMAT_INSTRUCTION,
    SYSTEM_PROMPT,
    build_decision_prompt,
)
from ai.schemas import AgentState, ComplianceOutput, ComplianceStatus
from ai.tools.function_registry import BedrockLLMClient, get_bedrock_client

logger = logging.getLogger(__name__)

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


async def decision_agent(state: AgentState) -> AgentState:
    """Synthesise a final compliance decision from all upstream agent outputs.

    Workflow:
        1. Build an async prompt with calibration context injected.
        2. Call ``BedrockLLMClient.invoke_with_fallback()``.
        3. Parse the JSON response into a ``ComplianceOutput``.
        4. Apply :class:`LiveConfidenceAdjuster` to the raw confidence.
        5. Set ``state["compliance_output"]``.

    On JSON parse failure the decision defaults to
    ``status=REVIEW``, ``reason="Decision parsing failed"``.
    """
    request_id = state["request_id"]
    correlation_id = state["correlation_id"]

    try:
        client = _bedrock_client if _bedrock_client is not None else get_bedrock_client()

        user_prompt = await build_decision_prompt(state)

        system_prompt = SYSTEM_PROMPT
        raw_response = client.invoke_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        output = _parse_response(
            raw_response, request_id=request_id, correlation_id=correlation_id
        )

        output = await _apply_confidence_adjustment(output, state)
        state["compliance_output"] = output

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


async def _apply_confidence_adjustment(
    output: ComplianceOutput, state: AgentState
) -> ComplianceOutput:
    """Apply the live calibration adjuster to the parsed output.

    Best-effort: if the rule engine is unavailable the raw confidence
    is kept and a warning is logged.
    """
    try:
        from ai.calibration.live_adjuster import LiveConfidenceAdjuster
        from ai.compliance_loop.rule_engine import get_rule_engine

        rule_engine = await get_rule_engine()
        adjuster = LiveConfidenceAdjuster(rule_engine)

        adjusted = await adjuster.adjust(
            raw_confidence=output.confidence,
            agent_errors=output.agent_errors,
            rag_context_empty=len(state.get("rag_context") or "") == 0,
            sanctions_hit=state.get("sanctions_hit", False),
            short_circuit_reason=state.get("short_circuit_reason"),
        )

        output.confidence = adjusted.adjusted
        output.confidence_adjustment = adjusted.model_dump()

        logger.debug(
            "decision_agent: confidence adjusted — raw=%.4f adjusted=%.4f "
            "total_deduction=%.4f deductions=%d request_id=%s",
            adjusted.raw,
            adjusted.adjusted,
            adjusted.total_deduction,
            len(adjusted.deductions),
            output.request_id,
        )
    except Exception as exc:
        logger.warning(
            "decision_agent: confidence adjustment skipped — %s", exc
        )

    return output


def _parse_response(
    raw: str, *, request_id: str, correlation_id: str | None
) -> ComplianceOutput:
    """Attempt to parse a raw LLM response string into a ComplianceOutput.

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

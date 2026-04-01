"""
Decision Engine module.

Core coordination for compliance request processing.
"""

import asyncio
import logging
import time
from typing import List, Optional
from uuid import uuid4

from ai.agents.graph import run_graph
from ai.agents.decision_agent import set_bedrock_client
from ai.agents.rag_agent import init_query_handler
from ai.core.output_formatter import OutputFormatter
from ai.core.schemas import (
    AgentState,
    ComplianceInput,
    ComplianceOutput,
    ComplianceStatus,
)
from ai.llm.bedrock_client import get_bedrock_client

logger = logging.getLogger(__name__)


class DecisionEngine:
    """Orchestrates compliance processing through the LangGraph agent pipeline."""

    def __init__(self, bedrock_client=None, rag_retriever=None):
        self._bedrock_client = bedrock_client
        self._rag_retriever = rag_retriever
        self._formatter = OutputFormatter()

    async def _ensure_dependencies(self):
        if self._bedrock_client is None:
            self._bedrock_client = get_bedrock_client()
        set_bedrock_client(self._bedrock_client)

        if self._rag_retriever is not None:
            await init_query_handler(self._rag_retriever)

    async def process(
        self, input: ComplianceInput
    ) -> tuple[ComplianceOutput, AgentState]:
        """Process one compliance input and return formatted output plus final state.

        Returns:
            A ``(ComplianceOutput, AgentState)`` tuple.  The state is
            needed by the audit trail to capture per-agent signals.
        """
        await self._ensure_dependencies()

        start_time = time.monotonic()

        initial_state = AgentState(
            request_id=input.request_id,
            correlation_id=input.correlation_id,
            user_data=input.user_data,
            documents=input.documents,
            query=input.query,
            agent_errors=[],
            short_circuit_reason=None,
            graph_start_time=time.monotonic(),
            doc_check_passed=False,
            missing_docs=[],
            rag_context="",
            agent_outputs={},
            foir_value=-1.0,
            foir_passed=False,
            emi_breakdown={},
            sanctions_hit=False,
            matched_entity=None,
            sanctions_score=0.0,
            expired_docs=[],
            temporal_passed=False,
            days_to_expiry={},
            compliance_output=None,
        )

        logger.info(
            "DecisionEngine.process start request_id=%s correlation_id=%s",
            input.request_id,
            input.correlation_id,
        )

        try:
            final_state = await run_graph(initial_state)
        except Exception as exc:
            logger.error("DecisionEngine.process graph failure request_id=%s %s", input.request_id, exc)
            final_output = ComplianceOutput(
                request_id=input.request_id or str(uuid4()),
                correlation_id=input.correlation_id,
                status=ComplianceStatus.REVIEW,
                reason=f"Pipeline execution failed: {exc}",
                clauses=[],
                confidence=0.0,
                rules_used=[],
                agent_errors=initial_state.get("agent_errors", []),
                short_circuit_reason=initial_state.get("short_circuit_reason"),
                processing_ms=None,
            )
            return self._formatter.format(final_output, start_time), initial_state

        output = final_state.get("compliance_output") if isinstance(final_state, dict) else final_state.compliance_output

        if output is None:
            output = ComplianceOutput(
                request_id=input.request_id or str(uuid4()),
                correlation_id=input.correlation_id,
                status=ComplianceStatus.REVIEW,
                reason="Pipeline completed without generated compliance output.",
                clauses=[],
                confidence=0.0,
                rules_used=[],
                agent_errors=(final_state.get("agent_errors") if isinstance(final_state, dict) else final_state.agent_errors) or [],
                short_circuit_reason=(final_state.get("short_circuit_reason") if isinstance(final_state, dict) else final_state.short_circuit_reason),
                processing_ms=None,
            )

        formatted_output = self._formatter.format(output, start_time)

        logger.info(
            "DecisionEngine.process complete request_id=%s status=%s confidence=%.4f",
            formatted_output.request_id,
            formatted_output.status.value,
            formatted_output.confidence,
        )

        return formatted_output, final_state

    async def process_batch(
        self, inputs: List[ComplianceInput]
    ) -> List[tuple[ComplianceOutput, AgentState]]:
        """Process a batch of inputs with resilient per-item error handling.

        Returns:
            List of ``(ComplianceOutput, AgentState)`` tuples, one per input.
        """
        results = await asyncio.gather(
            *[self.process(item) for item in inputs],
            return_exceptions=True,
        )

        outputs: List[tuple[ComplianceOutput, AgentState]] = []
        for idx, item_result in enumerate(results):
            if isinstance(item_result, Exception):
                logger.error("DecisionEngine.process_batch item failed idx=%d error=%s", idx, item_result)
                fallback_output = ComplianceOutput(
                    request_id=str(uuid4()),
                    correlation_id=None,
                    status=ComplianceStatus.REVIEW,
                    reason=f"Batch processing failure: {item_result}",
                    clauses=[],
                    confidence=0.0,
                    rules_used=[],
                    agent_errors=[],
                    short_circuit_reason=None,
                    processing_ms=None,
                )
                fallback_state: AgentState = {
                    "request_id": fallback_output.request_id,
                    "correlation_id": None,
                    "user_data": {},
                    "documents": [],
                    "query": "",
                    "agent_errors": [],
                    "short_circuit_reason": None,
                    "graph_start_time": 0.0,
                    "doc_check_passed": False,
                    "missing_docs": [],
                    "rag_context": "",
                    "agent_outputs": {},
                    "foir_value": -1.0,
                    "foir_passed": False,
                    "emi_breakdown": {},
                    "sanctions_hit": False,
                    "matched_entity": None,
                    "sanctions_score": 0.0,
                    "expired_docs": [],
                    "temporal_passed": False,
                    "days_to_expiry": {},
                    "compliance_output": None,
                }
                outputs.append((fallback_output, fallback_state))
            else:
                outputs.append(item_result)

        logger.info(
            "DecisionEngine.process_batch complete batch=%d success=%d",
            len(inputs),
            sum(1 for o in outputs if o is not None),
        )

        return outputs

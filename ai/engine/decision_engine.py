"""
Decision Engine module.

Core engine that accepts a ComplianceInput, runs the full LangGraph
agent pipeline, and returns the final ComplianceOutput.
"""

import logging

from ai.agents.graph import compliance_graph
from ai.schemas import AgentState, ComplianceInput, ComplianceOutput, ComplianceStatus

logger = logging.getLogger(__name__)


class DecisionEngine:
    """Orchestrates a compliance check by driving the compiled LangGraph."""

    def run(self, input: ComplianceInput) -> ComplianceOutput:
        """
        Execute the full compliance pipeline.

        Args:
            input: A validated ComplianceInput payload.

        Returns:
            The final ComplianceOutput produced by the decision agent.
        """
        initial_state = AgentState(
            user_data=input.user_data,
            documents=input.documents,
            query=input.query,
        )

        logger.info("DecisionEngine: starting compliance graph for query=%r", input.query)

        try:
            final_state = compliance_graph.invoke(initial_state.model_dump())
        except Exception as exc:
            logger.error("DecisionEngine: graph execution failed — %s", exc)
            return ComplianceOutput(
                status=ComplianceStatus.REVIEW,
                reason=f"Pipeline execution failed: {exc}",
                clauses=[],
                confidence=0.0,
                rules_used=[],
            )

        # LangGraph returns a dict; reconstruct AgentState to access typed fields
        result_state = AgentState(**final_state)

        if result_state.final_decision is not None:
            logger.info(
                "DecisionEngine: completed — status=%s",
                result_state.final_decision.status.value,
            )
            return result_state.final_decision

        logger.warning("DecisionEngine: graph finished without a final_decision.")
        return ComplianceOutput(
            status=ComplianceStatus.REVIEW,
            reason="Pipeline completed but no decision was produced.",
            clauses=[],
            confidence=0.0,
            rules_used=[],
        )

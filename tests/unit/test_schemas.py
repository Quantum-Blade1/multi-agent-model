"""
Tests for Pydantic schema models, validators, and the AgentState TypedDict.

Covers auto-generation of request IDs, query validation, confidence capping
on non-recoverable errors, UTC timestamps on AgentError, and a structural
check that the sample_agent_state fixture satisfies every AgentState key.
"""

from datetime import timezone

import pytest
from pydantic import ValidationError

from ai.core.schemas import (
    AgentError,
    AgentErrorType,
    AgentState,
    ComplianceInput,
    ComplianceOutput,
    ComplianceStatus,
)


class TestComplianceInput:

    def test_compliance_input_auto_generates_request_id(self):
        """Omitting request_id (or passing '') should auto-generate a UUID4 string.

        The field_validator generate_request_id fires on mode='before' and
        produces a non-empty UUID when the value is ''.
        """
        # Arrange
        inp = ComplianceInput(
            request_id="",
            user_data={"name": "Test"},
            documents=[{"type": "pan", "url": "s3://b/p.pdf"}],
            query="Auto-generate request ID test query.",
        )

        # Act / Assert
        assert inp.request_id, "request_id should not be empty after auto-generation"
        assert len(inp.request_id) == 36, (
            "Auto-generated request_id should be a UUID4 (36 chars with hyphens)"
        )

    def test_compliance_input_rejects_blank_query(self):
        """A query that becomes blank after stripping whitespace must be rejected.

        The validate_query field_validator strips and raises ValueError.
        """
        # Arrange / Act / Assert
        with pytest.raises(ValidationError) as exc_info:
            ComplianceInput(
                user_data={"name": "Test"},
                documents=[{"type": "pan", "url": "s3://b/p.pdf"}],
                query="          ",  # blank after strip
            )

        errors = exc_info.value.errors()
        assert any(
            e["loc"] == ("query",) for e in errors
        ), "Validation error should target the 'query' field"


class TestComplianceOutput:

    def test_compliance_output_caps_confidence_on_unrecoverable_errors(self):
        """When any AgentError has recoverable=False, confidence must be <= 0.6.

        The cap_confidence_on_errors model_validator runs after init.
        """
        # Arrange
        error = AgentError(
            agent="sanctions_agent",
            error_type=AgentErrorType.SANCTIONS,
            message="Screening service timeout",
            recoverable=False,
        )

        # Act
        output = ComplianceOutput(
            request_id="test-cap",
            status=ComplianceStatus.APPROVED,
            reason="Test",
            clauses=[],
            confidence=1.0,
            rules_used=[],
            agent_errors=[error],
        )

        # Assert
        assert output.confidence <= 0.6, (
            f"Confidence should be capped to 0.6 but was {output.confidence}"
        )


class TestAgentError:

    def test_agent_error_timestamp_is_utc(self):
        """The default timestamp factory should produce a UTC-aware datetime."""
        # Arrange / Act
        err = AgentError(
            agent="rag_agent",
            error_type=AgentErrorType.RETRIEVAL,
            message="Index missing",
            recoverable=True,
        )

        # Assert
        assert err.timestamp.tzinfo is not None, (
            "AgentError.timestamp must be timezone-aware"
        )
        assert err.timestamp.utcoffset().total_seconds() == 0, (
            "AgentError.timestamp should be in UTC (offset 0)"
        )


class TestAgentState:

    def test_sample_agent_state_is_graph_ready(self, sample_agent_state):
        """The sample_agent_state fixture must contain every AgentState key.

        AgentState is a TypedDict — it has no runtime defaults — so the
        fixture must provide all keys for agents to work without KeyError.
        """
        # Arrange
        required_keys = set(AgentState.__annotations__.keys())

        # Act
        actual_keys = set(sample_agent_state.keys())

        # Assert
        missing = required_keys - actual_keys
        assert not missing, (
            f"sample_agent_state is missing AgentState keys: {missing}"
        )

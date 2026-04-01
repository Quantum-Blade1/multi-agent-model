"""
Shared pytest fixtures for the NBFC compliance AI test suite.

Provides reusable ComplianceInput samples, AgentState factories,
mocked Bedrock clients, RAG retrievers, and scenario-specific inputs.
"""

import json
import time
from unittest.mock import MagicMock

import pytest

from ai.core.schemas import (
    AgentState,
    ComplianceInput,
    ComplianceOutput,
    ComplianceStatus,
    RagChunk,
)


# ---------------------------------------------------------------------------
# LLM response JSON strings (match decision_agent._parse_response expectations)
# ---------------------------------------------------------------------------

@pytest.fixture()
def approved_bedrock_response() -> str:
    """JSON the LLM returns for an APPROVED decision."""
    return json.dumps({
        "status": "approved",
        "reason": "All KYC documents present; FOIR within limits.",
        "clauses": ["RBI/MD-KYC/2016/Sec38"],
        "confidence": 0.95,
        "rules_used": ["RULE-KYC-001", "RULE-FOIR-001"],
    })


@pytest.fixture()
def rejected_bedrock_response() -> str:
    """JSON the LLM returns for a REJECTED decision."""
    return json.dumps({
        "status": "rejected",
        "reason": "Sanctions match detected; PAN on blacklist.",
        "clauses": ["PMLA-Sec12"],
        "confidence": 0.97,
        "rules_used": ["RULE-SANCTIONS-001"],
    })


@pytest.fixture()
def review_bedrock_response() -> str:
    """JSON the LLM returns for a REVIEW decision."""
    return json.dumps({
        "status": "review",
        "reason": "Borderline FOIR; RAG context missing.",
        "clauses": [],
        "confidence": 0.45,
        "rules_used": ["RULE-FOIR-001"],
    })


# ---------------------------------------------------------------------------
# Mock Bedrock client (sync — matches BedrockLLMClient interface)
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_bedrock_client(approved_bedrock_response) -> MagicMock:
    """MagicMock standing in for BedrockLLMClient.

    ``invoke_with_fallback`` and ``invoke`` both return the approved JSON
    by default.  Override ``return_value`` in individual tests as needed.
    """
    client = MagicMock()
    client.invoke_with_fallback.return_value = approved_bedrock_response
    client.invoke.return_value = approved_bedrock_response
    return client


# ---------------------------------------------------------------------------
# Mock RAG retriever — returns 3 result dicts matching QueryHandler.handle
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_rag_retriever() -> MagicMock:
    """MagicMock for QueryHandler.handle that returns 3 clause dicts."""
    handler = MagicMock()
    handler.handle.return_value = [
        {"clause_id": "CL-001", "text": "Capital adequacy ratio must be 15%.", "source": "s3://docs/cap.pdf", "score": 0.92},
        {"clause_id": "CL-002", "text": "KYC verification within 30 days.", "source": "s3://docs/kyc.pdf", "score": 0.88},
        {"clause_id": "CL-003", "text": "Suspicious transaction reporting to FIU.", "source": "s3://docs/aml.pdf", "score": 0.81},
    ]
    return handler


# ---------------------------------------------------------------------------
# Sample ComplianceInput (all-valid happy path)
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_compliance_input() -> ComplianceInput:
    """A fully valid ComplianceInput suitable for end-to-end tests."""
    return ComplianceInput(
        user_data={
            "name": "Alice Kumar",
            "pan_number": "LMNOP1234Q",
            "income": 80_000,
            "existing_emi": 5_000,
            "loan_amount": 300_000,
            "tenure_months": 60,
            "required_documents": ["aadhaar", "pan", "address_proof"],
            "provided_documents": ["aadhaar", "pan", "address_proof"],
            "documents_meta": [
                {"doc_type": "aadhaar", "expiry_date": "2030-12-31"},
                {"doc_type": "pan", "expiry_date": "2035-06-15"},
                {"doc_type": "address_proof", "expiry_date": "2028-03-01"},
            ],
        },
        documents=[
            {"type": "aadhaar", "url": "s3://bucket/aadhaar.pdf"},
            {"type": "pan", "url": "s3://bucket/pan.pdf"},
        ],
        query="Run full KYC compliance check for loan application.",
    )


# ---------------------------------------------------------------------------
# Sample AgentState (safe defaults for all keys)
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_agent_state() -> dict:
    """Full AgentState dict with safe defaults for every key.

    TypedDict has no runtime defaults, so this factory provides a complete
    dict that satisfies the LangGraph graph and all agents.
    """
    return {
        "request_id": "test-request-001",
        "correlation_id": None,
        "user_data": {
            "name": "Alice Kumar",
            "pan_number": "LMNOP1234Q",
            "income": 80_000,
            "existing_emi": 5_000,
            "loan_amount": 300_000,
            "tenure_months": 60,
            "required_documents": ["aadhaar", "pan", "address_proof"],
            "provided_documents": ["aadhaar", "pan", "address_proof"],
            "documents_meta": [
                {"doc_type": "aadhaar", "expiry_date": "2030-12-31"},
                {"doc_type": "pan", "expiry_date": "2035-06-15"},
                {"doc_type": "address_proof", "expiry_date": "2028-03-01"},
            ],
        },
        "documents": [
            {"type": "aadhaar", "url": "s3://bucket/aadhaar.pdf"},
            {"type": "pan", "url": "s3://bucket/pan.pdf"},
        ],
        "query": "Check KYC compliance for loan application.",
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
        "agent_errors": [],
        "short_circuit_reason": None,
        "graph_start_time": time.monotonic(),
    }


# ---------------------------------------------------------------------------
# Scenario-specific inputs
# ---------------------------------------------------------------------------

@pytest.fixture()
def expired_doc_input() -> dict:
    """user_data + documents_meta with one expired document (aadhaar in 2020)."""
    return {
        "name": "Alice Kumar",
        "pan_number": "LMNOP1234Q",
        "income": 80_000,
        "existing_emi": 5_000,
        "loan_amount": 300_000,
        "tenure_months": 60,
        "required_documents": ["aadhaar"],
        "provided_documents": ["aadhaar"],
        "documents_meta": [
            {"doc_type": "aadhaar", "expiry_date": "2020-01-01"},
        ],
    }


@pytest.fixture()
def sanctions_hit_input() -> dict:
    """user_data with a name present on the mock sanctions list."""
    return {
        "name": "John Doe",
        "pan_number": "ZZZZZZ999Z",
        "income": 100_000,
        "existing_emi": 0,
        "loan_amount": 500_000,
        "tenure_months": 60,
        "required_documents": ["aadhaar"],
        "provided_documents": ["aadhaar"],
        "documents_meta": [
            {"doc_type": "aadhaar", "expiry_date": "2035-01-01"},
        ],
    }


@pytest.fixture()
def high_foir_input() -> dict:
    """user_data that produces FOIR > 0.50 under the flat-EMI formula.

    existing_emi=35000, new_emi=300000/60=5000 → FOIR = 40000/60000 = 0.6667
    """
    return {
        "name": "Heavy Borrower",
        "pan_number": "QQQQQ0000Q",
        "income": 60_000,
        "existing_emi": 35_000,
        "loan_amount": 300_000,
        "tenure_months": 60,
        "required_documents": ["aadhaar"],
        "provided_documents": ["aadhaar"],
        "documents_meta": [
            {"doc_type": "aadhaar", "expiry_date": "2035-01-01"},
        ],
    }

"""
Integration tests for the CompliancePipeline.

Bedrock LLM calls are mocked via a pytest fixture that patches
BedrockLLMClient to return a hardcoded compliance decision JSON.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from ai.pipeline import CompliancePipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_LLM_RESPONSE = json.dumps(
    {
        "status": "Approved",
        "reason": "All KYC documents are present and valid.",
        "clauses": ["RBI/MD-KYC/2016/Sec38"],
        "confidence": 0.94,
        "rules_used": ["RULE-KYC-001"],
    }
)


@pytest.fixture(autouse=True)
def mock_bedrock():
    """Patch BedrockLLMClient so no real AWS calls are made."""
    with patch("ai.tools.function_registry.boto3") as mock_boto:
        # Make the mocked client's invoke_model return our canned response
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {"content": [{"text": MOCK_LLM_RESPONSE}]}
        ).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}
        mock_boto.client.return_value = mock_client
        yield mock_client


@pytest.fixture()
def valid_input() -> dict:
    return {
        "user_data": {
            "name": "Priya Sharma",
            "pan_number": "ZZZZZ9999Z",
            "income": 120000,
            "existing_emi": 10000,
            "loan_amount": 500000,
            "tenure_months": 60,
            "required_documents": ["aadhaar", "pan"],
            "provided_documents": ["aadhaar", "pan"],
            "documents_meta": [
                {"doc_type": "aadhaar", "expiry_date": "2032-06-01"},
                {"doc_type": "pan", "expiry_date": "2035-12-31"},
            ],
        },
        "documents": [
            "s3://compliance-docs/aadhaar.pdf",
            "s3://compliance-docs/pan.pdf",
        ],
        "query": "Run full KYC compliance check for loan application.",
    }


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestCompliancePipeline:
    """End-to-end pipeline tests with mocked Bedrock."""

    def test_valid_input_returns_all_fields(self, valid_input):
        pipeline = CompliancePipeline()
        result = pipeline.process(valid_input)

        assert "status" in result
        assert "reason" in result
        assert "confidence" in result
        assert "clauses" in result
        assert "rules_used" in result

    def test_valid_input_status_is_valid(self, valid_input):
        pipeline = CompliancePipeline()
        result = pipeline.process(valid_input)

        assert result["status"] in ("Approved", "Rejected", "Review")

    def test_valid_input_has_metadata(self, valid_input):
        pipeline = CompliancePipeline()
        result = pipeline.process(valid_input)

        assert "request_id" in result
        assert "timestamp" in result

    def test_invalid_input_returns_error(self):
        pipeline = CompliancePipeline()
        result = pipeline.process({"bad_key": "bad_value"})

        assert result["status"] == "Error"
        assert result["reason"] == "Invalid input schema"

    def test_missing_required_fields(self):
        pipeline = CompliancePipeline()
        result = pipeline.process({"user_data": {}, "documents": []})

        assert result["status"] == "Error"

    def test_empty_input_returns_error(self):
        pipeline = CompliancePipeline()
        result = pipeline.process({})

        assert result["status"] == "Error"
        assert "errors" in result

    def test_confidence_in_range(self, valid_input):
        pipeline = CompliancePipeline()
        result = pipeline.process(valid_input)

        conf = result.get("confidence", 0.0)
        assert 0.0 <= conf <= 1.0

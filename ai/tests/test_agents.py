"""
Unit tests for all compliance agents.

Each agent is tested with a mock AgentState. Bedrock calls are not
involved here — these tests verify agent logic in isolation.
"""

import pytest

from ai.schemas import AgentState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(**overrides) -> AgentState:
    """Create a minimal valid AgentState with optional overrides."""
    defaults = {
        "user_data": {
            "name": "Alice Kumar",
            "pan_number": "LMNOP1234Q",
            "income": 80000,
            "existing_emi": 5000,
            "loan_amount": 300000,
            "tenure_months": 60,
            "required_documents": ["aadhaar", "pan", "address_proof"],
            "provided_documents": ["aadhaar", "pan", "address_proof"],
            "documents_meta": [
                {"doc_type": "aadhaar", "expiry_date": "2030-12-31"},
                {"doc_type": "pan", "expiry_date": "2035-06-15"},
                {"doc_type": "address_proof", "expiry_date": "2028-03-01"},
            ],
        },
        "documents": ["s3://bucket/aadhaar.pdf", "s3://bucket/pan.pdf"],
        "query": "Check KYC compliance for loan application.",
    }
    defaults.update(overrides)
    return AgentState(**defaults)


# ---------------------------------------------------------------------------
# document_agent
# ---------------------------------------------------------------------------

class TestDocumentAgent:
    def test_valid_documents(self):
        from ai.agents.document_agent import document_agent

        state = _base_state()
        result = document_agent(state)
        out = result.agent_outputs["document_agent"]

        assert "valid" in out
        assert "missing" in out
        assert "issues" in out
        assert out["valid"] is True

    def test_empty_documents(self):
        from ai.agents.document_agent import document_agent

        state = _base_state(documents=[])
        result = document_agent(state)
        out = result.agent_outputs["document_agent"]

        assert out["valid"] is False
        assert any("No documents" in i for i in out["issues"])

    def test_invalid_s3_url(self):
        from ai.agents.document_agent import document_agent

        state = _base_state(documents=["https://not-s3.com/file.pdf"])
        result = document_agent(state)
        out = result.agent_outputs["document_agent"]

        assert out["valid"] is False

    def test_missing_document_types(self):
        from ai.agents.document_agent import document_agent

        user_data = _base_state().user_data.copy()
        user_data["provided_documents"] = ["aadhaar"]  # missing pan, address_proof
        state = _base_state(user_data=user_data)
        result = document_agent(state)
        out = result.agent_outputs["document_agent"]

        assert len(out["missing"]) == 2


# ---------------------------------------------------------------------------
# transaction_agent
# ---------------------------------------------------------------------------

class TestTransactionAgent:
    def test_foir_pass(self):
        from ai.agents.transaction_agent import transaction_agent

        state = _base_state()
        result = transaction_agent(state)
        out = result.agent_outputs["transaction_agent"]

        assert "foir_pass" in out
        assert "foir_value" in out
        assert isinstance(out["foir_value"], float)
        # (5000 + 300000/60) / 80000 = (5000 + 5000) / 80000 = 0.125
        assert out["foir_pass"] is True

    def test_foir_fail(self):
        from ai.agents.transaction_agent import transaction_agent

        user_data = _base_state().user_data.copy()
        user_data["existing_emi"] = 35000  # pushes FOIR way above 0.5
        state = _base_state(user_data=user_data)
        result = transaction_agent(state)
        out = result.agent_outputs["transaction_agent"]

        assert out["foir_pass"] is False

    def test_zero_income(self):
        from ai.agents.transaction_agent import transaction_agent

        user_data = _base_state().user_data.copy()
        user_data["income"] = 0
        state = _base_state(user_data=user_data)
        result = transaction_agent(state)
        out = result.agent_outputs["transaction_agent"]

        assert out["foir_pass"] is False
        assert out["foir_value"] == 1.0


# ---------------------------------------------------------------------------
# sanctions_agent
# ---------------------------------------------------------------------------

class TestSanctionsAgent:
    def test_no_match(self):
        from ai.agents.sanctions_agent import sanctions_agent

        state = _base_state()
        result = sanctions_agent(state)
        out = result.agent_outputs["sanctions_agent"]

        assert "sanctioned" in out
        assert "match" in out
        assert out["sanctioned"] is False
        assert out["match"] is None

    def test_sanctions_match_by_name(self):
        from ai.agents.sanctions_agent import sanctions_agent

        user_data = _base_state().user_data.copy()
        user_data["name"] = "John Doe"  # hardcoded in mock sanctions list
        state = _base_state(user_data=user_data)
        result = sanctions_agent(state)
        out = result.agent_outputs["sanctions_agent"]

        assert out["sanctioned"] is True
        assert "John Doe" in out["match"]

    def test_sanctions_match_by_pan(self):
        from ai.agents.sanctions_agent import sanctions_agent

        user_data = _base_state().user_data.copy()
        user_data["pan_number"] = "ABCDE1234F"  # hardcoded in mock list
        state = _base_state(user_data=user_data)
        result = sanctions_agent(state)
        out = result.agent_outputs["sanctions_agent"]

        assert out["sanctioned"] is True

    def test_case_insensitive_match(self):
        from ai.agents.sanctions_agent import sanctions_agent

        user_data = _base_state().user_data.copy()
        user_data["name"] = "john doe"  # lowercase
        state = _base_state(user_data=user_data)
        result = sanctions_agent(state)
        out = result.agent_outputs["sanctions_agent"]

        assert out["sanctioned"] is True


# ---------------------------------------------------------------------------
# temporal_agent
# ---------------------------------------------------------------------------

class TestTemporalAgent:
    def test_all_valid(self):
        from ai.agents.temporal_agent import temporal_agent

        state = _base_state()
        result = temporal_agent(state)
        out = result.agent_outputs["temporal_agent"]

        assert "expired_docs" in out
        assert "all_valid" in out
        assert out["all_valid"] is True
        assert out["expired_docs"] == []

    def test_expired_document(self):
        from ai.agents.temporal_agent import temporal_agent

        user_data = _base_state().user_data.copy()
        user_data["documents_meta"] = [
            {"doc_type": "aadhaar", "expiry_date": "2020-01-01"},
        ]
        state = _base_state(user_data=user_data)
        result = temporal_agent(state)
        out = result.agent_outputs["temporal_agent"]

        assert out["all_valid"] is False
        assert len(out["expired_docs"]) == 1
        assert out["expired_docs"][0]["doc_type"] == "aadhaar"

    def test_missing_documents_meta(self):
        from ai.agents.temporal_agent import temporal_agent

        user_data = _base_state().user_data.copy()
        user_data.pop("documents_meta", None)
        state = _base_state(user_data=user_data)
        result = temporal_agent(state)
        out = result.agent_outputs["temporal_agent"]

        assert out["all_valid"] is True
        assert out["expired_docs"] == []

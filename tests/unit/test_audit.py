"""
Tests for the audit trail subsystem: models, hash chain, DynamoDB store, and REST API.

All DynamoDB calls are mocked with AsyncMock — no real AWS calls.
Endpoint tests use httpx AsyncClient + ASGITransport.
"""

import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from audit.models import (
    AgentSignalSnapshot,
    AuditRecord,
    HashChainEngine,
    OverrideRecord,
    ReviewerStatus,
    VerificationResult,
    build_audit_record,
    scrub_input_for_audit,
)
from audit.store import (
    AuditAlreadyOverriddenError,
    AuditStore,
    AuditWriteError,
    to_dynamo_item,
)
from ai.core.schemas import (
    ComplianceInput,
    ComplianceOutput,
    ComplianceStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signals() -> AgentSignalSnapshot:
    return AgentSignalSnapshot(
        doc_check_passed=True,
        missing_docs=[],
        foir_value=0.38,
        foir_passed=True,
        emi_breakdown={"principal": 4000.0, "interest": 1000.0, "total_emi": 5000.0},
        sanctions_hit=False,
        matched_entity=None,
        sanctions_score=0.0,
        expired_docs=[],
        temporal_passed=True,
        days_to_expiry={"aadhaar": 900},
        rag_chunks_retrieved=3,
        rag_sources=["s3://docs/a.pdf"],
    )


def _make_record(*, request_id: str = "req-001", prev_hash: str | None = None) -> AuditRecord:
    prev = prev_hash or HashChainEngine.GENESIS_HASH
    record = AuditRecord(
        request_id=request_id,
        correlation_id=None,
        processing_ms=120.0,
        input_snapshot={"user_data": {"name": "Test"}},
        query="Run compliance check for test",
        agent_signals=_make_signals(),
        agent_errors=[],
        short_circuit_reason=None,
        final_status="APPROVED",
        final_reason="All checks passed",
        clauses_cited=["RBI/KYC/2016"],
        confidence=0.92,
        rules_used=["FOIR_LIMIT"],
        content_hash="",
        chain_hash="",
        previous_chain_hash=prev,
    )
    record.content_hash = HashChainEngine.compute_content_hash(record)
    record.chain_hash = HashChainEngine.compute_chain_hash(prev, record.content_hash)
    return record


# ===========================================================================
# Models & hash chain
# ===========================================================================


class TestBuildAuditRecord:

    async def test_build_audit_record_populates_all_fields(self):
        """build_audit_record should fill audit_id, hashes, and all nested fields."""
        ci = ComplianceInput(
            user_data={"name": "Alice", "pan_number": "ABCDE1234F", "income": 50000,
                        "existing_emi": 2000, "loan_amount": 100000, "tenure_months": 12},
            documents=[{"type": "pan", "url": "s3://b/p.pdf"}],
            query="Compliance check for loan application.",
        )
        co = ComplianceOutput(
            request_id=ci.request_id,
            status=ComplianceStatus.APPROVED,
            reason="OK",
            clauses=["C1"],
            confidence=0.90,
            rules_used=["R1"],
            agent_errors=[],
        )
        state = {
            "doc_check_passed": True, "missing_docs": [], "foir_value": 0.38,
            "foir_passed": True, "emi_breakdown": {}, "sanctions_hit": False,
            "matched_entity": None, "sanctions_score": 0.0, "expired_docs": [],
            "temporal_passed": True, "days_to_expiry": {}, "agent_outputs": {},
        }
        rec = await build_audit_record(ci, co, state, HashChainEngine.GENESIS_HASH)

        assert rec.audit_id, "audit_id must be populated"
        assert rec.content_hash and len(rec.content_hash) == 64
        assert rec.chain_hash and len(rec.chain_hash) == 64
        assert rec.final_status == "APPROVED"
        assert rec.input_snapshot["user_data"]["pan_number"] == "***REDACTED***"


class TestScrubInput:

    def test_scrub_input_removes_pan_and_aadhaar(self):
        """PII fields must be replaced with ***REDACTED***."""
        raw = {
            "user_data": {
                "name": "Alice",
                "pan_number": "ABCDE1234F",
                "aadhaar_number": "123412341234",
            }
        }
        scrubbed = scrub_input_for_audit(raw)
        assert scrubbed["user_data"]["pan_number"] == "***REDACTED***"
        assert scrubbed["user_data"]["aadhaar_number"] == "***REDACTED***"
        assert scrubbed["user_data"]["name"] == "Alice"


class TestHashChain:

    def test_hash_chain_genesis_record_uses_genesis_hash(self):
        """First record's previous_chain_hash must be 64 zeros."""
        rec = _make_record()
        assert rec.previous_chain_hash == "0" * 64

    def test_hash_chain_verify_detects_tampered_record(self):
        """Altering an immutable field must break verification."""
        rec = _make_record()
        rec.final_status = "REJECTED"
        result = HashChainEngine.verify_record(rec, HashChainEngine.GENESIS_HASH)
        assert result is False, "Tampered record should fail verification"

    async def test_hash_chain_verify_chain_returns_first_broken_index(self):
        """A 3-record chain with tampered record[1] should report first_broken_at=1."""
        r0 = _make_record(request_id="r0")
        r1 = _make_record(request_id="r1", prev_hash=r0.chain_hash)
        r2 = _make_record(request_id="r2", prev_hash=r1.chain_hash)

        r1.final_status = "REJECTED"

        result = await HashChainEngine.verify_chain([r0, r1, r2])
        assert result.valid is False
        assert result.first_broken_at == 1


# ===========================================================================
# AuditStore (DynamoDB mocked)
# ===========================================================================


class TestAuditStore:

    async def test_audit_store_save_record_calls_transact_write(self):
        """save_record must call transact_write_items exactly once."""
        store = AuditStore()
        mock_client = AsyncMock()
        mock_client.transact_write_items = AsyncMock(return_value={})
        mock_client.update_item = AsyncMock(return_value={
            "Attributes": {"value": {"N": "1"}}
        })
        store._client = mock_client

        rec = _make_record()
        await store.save_record(rec)
        mock_client.transact_write_items.assert_called_once()

    async def test_audit_store_prevents_overwrite_on_duplicate_request_id(self):
        """Duplicate request_id should raise AuditWriteError."""
        store = AuditStore()
        mock_client = AsyncMock()
        mock_client.update_item = AsyncMock(return_value={
            "Attributes": {"value": {"N": "1"}}
        })
        err_resp = {
            "Error": {"Code": "TransactionCanceledException", "Message": "dup"},
            "CancellationReasons": [{"Code": "ConditionalCheckFailed"}],
        }
        mock_client.transact_write_items = AsyncMock(
            side_effect=ClientError(err_resp, "TransactWriteItems")
        )
        store._client = mock_client

        rec = _make_record()
        with pytest.raises(AuditWriteError):
            await store.save_record(rec)

    async def test_apply_override_changes_reviewer_status(self):
        """apply_override should set reviewer_status to OVERRIDDEN."""
        store = AuditStore()
        rec = _make_record()

        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={
            "Items": [to_dynamo_item(rec)]
        })
        updated_rec = rec.model_copy()
        updated_rec.reviewer_status = ReviewerStatus.OVERRIDDEN
        mock_client.update_item = AsyncMock(return_value={
            "Attributes": to_dynamo_item(updated_rec)
        })
        store._client = mock_client

        override = OverrideRecord(
            audit_id=rec.audit_id,
            reviewer_id="reviewer-1",
            reviewer_email="rev@test.com",
            original_status="APPROVED",
            override_status="REJECTED",
            override_reason="This decision needs reversal due to new evidence found.",
        )
        result = await store.apply_override(rec.request_id, override)
        assert result.reviewer_status == ReviewerStatus.OVERRIDDEN

    async def test_apply_override_raises_on_double_override(self):
        """Double override should raise AuditAlreadyOverriddenError."""
        store = AuditStore()
        rec = _make_record()

        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={
            "Items": [to_dynamo_item(rec)]
        })
        err_resp = {
            "Error": {"Code": "ConditionalCheckFailedException", "Message": "already overridden"},
        }
        mock_client.update_item = AsyncMock(
            side_effect=ClientError(err_resp, "UpdateItem")
        )
        store._client = mock_client

        override = OverrideRecord(
            audit_id=rec.audit_id,
            reviewer_id="reviewer-2",
            reviewer_email="rev2@test.com",
            original_status="APPROVED",
            override_status="REVIEW",
            override_reason="Second override attempt should fail completely.",
        )
        with pytest.raises(AuditAlreadyOverriddenError):
            await store.apply_override(rec.request_id, override)


# ===========================================================================
# Audit REST API (httpx + ASGITransport)
# ===========================================================================


class TestAuditAPI:

    @pytest.fixture()
    def _test_app(self):
        """Minimal FastAPI app mounting the audit router with mocked store."""
        from fastapi import FastAPI
        from audit.router import audit_router

        app = FastAPI()
        app.include_router(audit_router)
        return app

    async def test_audit_query_api_returns_paginated_results(self, _test_app):
        """GET /audit/records should return paginated results."""
        import httpx

        rec = _make_record()
        mock_store = AsyncMock()
        mock_store.query_by_date_range = AsyncMock(return_value=MagicMock(
            records=[rec], total_returned=1, has_more=False, next_key=None,
        ))
        _test_app.state.audit_store = mock_store

        transport = httpx.ASGITransport(app=_test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/audit/records")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_returned"] == 1
        assert len(body["records"]) == 1

    async def test_override_endpoint_rejects_invalid_api_key(self, _test_app):
        """POST /audit/record/{id}/override with wrong key should return 403."""
        import httpx

        _test_app.state.audit_store = AsyncMock()
        os.environ["REVIEWER_API_KEY"] = "correct-key"

        transport = httpx.ASGITransport(app=_test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/audit/record/req-001/override",
                json={
                    "override_status": "REJECTED",
                    "override_reason": "This override should be rejected by auth middleware.",
                    "reviewer_id": "rev-1",
                    "reviewer_email": "rev@test.com",
                },
                headers={"X-Reviewer-Key": "wrong-key"},
            )
        assert resp.status_code == 403
        os.environ.pop("REVIEWER_API_KEY", None)

    async def test_chain_verify_endpoint_returns_verification_result(self, _test_app):
        """GET /audit/chain/verify should return a VerificationResult."""
        import httpx

        mock_store = AsyncMock()
        mock_store.verify_chain_integrity = AsyncMock(return_value=VerificationResult(
            valid=True, first_broken_at=None, total_records=5, verified_records=5,
        ))
        _test_app.state.audit_store = mock_store

        transport = httpx.ASGITransport(app=_test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/audit/chain/verify")
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["total_records"] == 5

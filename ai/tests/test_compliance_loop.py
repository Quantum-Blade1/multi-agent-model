"""
Tests for the compliance loop subsystem: rule engine, index swapper, feedback store.

All DynamoDB and S3 calls are mocked with AsyncMock — no real AWS calls.
"""

import asyncio
import copy
import os
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from ai.audit.models import ReviewerStatus
from ai.compliance_loop.feedback_store import (
    CalibrationDataset,
    FeedbackAlreadyExistsError,
    FeedbackRecord,
    FeedbackStore,
    InsufficientFeedbackError,
    ReviewerVerdict,
)
from ai.compliance_loop.index_swapper import IndexSwapper, SwapResult
from ai.compliance_loop.rule_engine import (
    DEFAULT_RULES,
    ComplianceRule,
    RuleChangeLog,
    RuleEngine,
    RuleUpdate,
    RuleValueType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feedback(
    verdict: ReviewerVerdict = ReviewerVerdict.AGREE,
    confidence: float = 0.90,
    status: str = "APPROVED",
    request_id: str | None = None,
) -> FeedbackRecord:
    return FeedbackRecord(
        request_id=request_id or f"req-{id(verdict)}",
        audit_id="audit-001",
        ai_status=status,
        ai_confidence=confidence,
        ai_clauses=["C1"],
        foir_value=0.38,
        sanctions_hit=False,
        doc_check_passed=True,
        temporal_passed=True,
        rag_chunks_retrieved=3,
        reviewer_verdict=verdict,
        reviewer_id="reviewer-1",
    )


# ===========================================================================
# RuleEngine
# ===========================================================================


class TestRuleEngine:

    async def test_rule_engine_returns_default_on_empty_dynamo(self):
        """When DynamoDB table is empty, the engine should fall back to DEFAULT_RULES."""
        engine = RuleEngine()
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(return_value={"Items": []})
        engine._client = mock_client

        value = await engine.foir_limit()
        assert value == 0.50, f"Expected default FOIR_LIMIT 0.50, got {value}"

    async def test_rule_engine_caches_rules_for_ttl_seconds(self):
        """get_rule() called twice should hit DynamoDB only once within TTL."""
        engine = RuleEngine()
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(return_value={"Items": []})
        engine._client = mock_client

        await engine.get_rule("FOIR_LIMIT")
        await engine.get_rule("FOIR_LIMIT")

        assert mock_client.scan.call_count == 1, (
            "DynamoDB should be called only once due to caching"
        )

    async def test_rule_engine_invalidates_cache_on_update(self):
        """After update_rule, the cache timestamp should be cleared."""
        engine = RuleEngine()
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(return_value={"Items": []})
        mock_client.put_item = AsyncMock(return_value={})
        engine._client = mock_client

        await engine.get_rule("FOIR_LIMIT")
        assert engine._cache_loaded_at is not None

        update = RuleUpdate(
            rule_id="FOIR_LIMIT",
            new_value=0.48,
            updated_by="test-user",
            justification="Testing cache invalidation after update rule call.",
        )
        await engine.update_rule(update)
        assert engine._cache_loaded_at is None, "Cache should be invalidated after update"

    def test_rule_update_rejects_out_of_bounds_value(self):
        """FOIR_LIMIT with value 0.70 (> max 0.65) should raise ValueError."""
        with pytest.raises(ValueError, match="max_value"):
            ComplianceRule(
                rule_id="FOIR_LIMIT",
                category="TRANSACTION",
                value_type=RuleValueType.FLOAT,
                current_value=0.70,
                default_value=0.50,
                min_value=0.30,
                max_value=0.65,
                description="Test",
            )

    async def test_rule_update_writes_changelog_entry(self):
        """update_rule should write both the rule and a changelog entry."""
        engine = RuleEngine()
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(return_value={"Items": []})
        mock_client.put_item = AsyncMock(return_value={})
        engine._client = mock_client

        await engine.get_rule("FOIR_LIMIT")
        update = RuleUpdate(
            rule_id="FOIR_LIMIT",
            new_value=0.48,
            updated_by="test-user",
            justification="Lowering FOIR limit for stricter compliance.",
        )
        rule, changelog = await engine.update_rule(update)

        assert mock_client.put_item.call_count == 2, (
            "Should write rule + changelog = 2 put_item calls"
        )
        assert rule.current_value == 0.48
        assert changelog.old_value == 0.50

    async def test_rule_reset_restores_default_value(self):
        """Updating a rule back to its default should succeed."""
        engine = RuleEngine()
        mock_client = AsyncMock()
        mock_client.scan = AsyncMock(return_value={"Items": []})
        mock_client.put_item = AsyncMock(return_value={})
        engine._client = mock_client

        await engine.get_rule("FOIR_LIMIT")

        update_away = RuleUpdate(
            rule_id="FOIR_LIMIT",
            new_value=0.55,
            updated_by="test",
            justification="First change to move away from default value.",
        )
        await engine.update_rule(update_away)

        engine._cache_loaded_at = None
        mock_client.scan.return_value = {"Items": []}
        await engine._refresh_cache_if_stale()

        update_back = RuleUpdate(
            rule_id="FOIR_LIMIT",
            new_value=0.50,
            updated_by="test",
            justification="Resetting back to the original default value.",
        )
        rule, _ = await engine.update_rule(update_back)
        assert rule.current_value == DEFAULT_RULES["FOIR_LIMIT"].default_value


# ===========================================================================
# IndexSwapper
# ===========================================================================


class TestIndexSwapper:

    async def test_index_swapper_swap_validates_new_index_before_committing(self):
        """If validation query fails, SwapResult.success should be False."""
        from ai.compliance_loop.index_watcher import IndexManifest

        swapper = IndexSwapper()

        bad_retriever = MagicMock()
        bad_retriever.retrieve.side_effect = RuntimeError("index corrupt")

        manifest = IndexManifest(
            index_type="master",
            built_at=datetime.now(UTC),
            vector_count=100,
            s3_faiss_key="indexes/master/index.faiss",
            s3_meta_key="indexes/master/index.meta.json",
            pipeline_run_id="run-001",
        )

        with patch.object(swapper, "_download_from_s3", new_callable=AsyncMock, return_value="/tmp/test"), \
             patch("ai.compliance_loop.index_swapper.FAISSRetriever") as MockRetriever:
            MockRetriever.load.return_value = bad_retriever
            result = await swapper.swap(manifest)

        assert result.success is False
        assert "Validation failed" in (result.reason or "")

    async def test_index_swapper_aborts_on_validation_failure(self):
        """After validation abort, get_retriever should still return old retriever."""
        from ai.compliance_loop.index_watcher import IndexManifest

        swapper = IndexSwapper()
        old_retriever = MagicMock()
        old_retriever.indexer = MagicMock()
        old_retriever.indexer.index = MagicMock(ntotal=50)
        swapper._retrievers["master"] = old_retriever

        bad_retriever = MagicMock()
        bad_retriever.retrieve.side_effect = RuntimeError("bad index")
        bad_retriever.indexer = MagicMock()
        bad_retriever.indexer.index = MagicMock(ntotal=10)

        manifest = IndexManifest(
            index_type="master",
            built_at=datetime.now(UTC),
            vector_count=10,
            s3_faiss_key="k.faiss",
            s3_meta_key="k.meta.json",
            pipeline_run_id="run-002",
        )

        with patch.object(swapper, "_download_from_s3", new_callable=AsyncMock, return_value="/tmp/t"), \
             patch("ai.compliance_loop.index_swapper.FAISSRetriever") as MockRetriever:
            MockRetriever.load.return_value = bad_retriever
            await swapper.swap(manifest)

        assert swapper.get_retriever("master") is old_retriever

    async def test_index_swapper_increments_swap_count_on_success(self):
        """A successful swap should increment _swap_count to 1."""
        from ai.compliance_loop.index_watcher import IndexManifest

        swapper = IndexSwapper()
        good_retriever = MagicMock()
        good_retriever.retrieve.return_value = [{"text": "OK", "score": 0.9}]
        good_retriever.indexer = MagicMock()
        good_retriever.indexer.index = MagicMock(ntotal=100)

        manifest = IndexManifest(
            index_type="master",
            built_at=datetime.now(UTC),
            vector_count=100,
            s3_faiss_key="k.faiss",
            s3_meta_key="k.meta.json",
            pipeline_run_id="run-003",
        )

        with patch.object(swapper, "_download_from_s3", new_callable=AsyncMock, return_value="/tmp/t"), \
             patch("ai.compliance_loop.index_swapper.FAISSRetriever") as MockRetriever:
            MockRetriever.load.return_value = good_retriever
            result = await swapper.swap(manifest)

        assert result.success is True
        assert swapper._swap_count == 1


# ===========================================================================
# FeedbackStore
# ===========================================================================


class TestFeedbackStore:

    async def test_feedback_save_prevents_duplicate_for_same_request(self):
        """Duplicate request_id should raise FeedbackAlreadyExistsError."""
        store = FeedbackStore()
        mock_client = AsyncMock()
        err_resp = {
            "Error": {"Code": "ConditionalCheckFailedException", "Message": "dup"},
        }
        mock_client.put_item = AsyncMock(
            side_effect=ClientError(err_resp, "PutItem")
        )
        store._client = mock_client

        rec = _make_feedback(request_id="dup-req")
        with pytest.raises(FeedbackAlreadyExistsError):
            await store.save_feedback(rec)

    async def test_feedback_disagreement_triggers_audit_override(self):
        """POST /feedback with DISAGREE should call apply_override on AuditStore."""
        from fastapi import FastAPI
        from ai.compliance_loop.feedback_router import feedback_router
        import httpx

        app = FastAPI()
        app.include_router(feedback_router)

        mock_audit = AsyncMock()
        mock_record = MagicMock()
        mock_record.final_status = "APPROVED"
        mock_record.confidence = 0.90
        mock_record.clauses_cited = ["C1"]
        mock_record.reviewer_status = ReviewerStatus.PENDING
        mock_signals = MagicMock()
        mock_signals.foir_value = 0.38
        mock_signals.sanctions_hit = False
        mock_signals.doc_check_passed = True
        mock_signals.temporal_passed = True
        mock_signals.rag_chunks_retrieved = 3
        mock_record.agent_signals = mock_signals
        mock_record.audit_id = "audit-001"
        mock_audit.get_by_request_id = AsyncMock(return_value=mock_record)
        mock_audit.apply_override = AsyncMock(return_value=mock_record)

        mock_feedback = AsyncMock()
        mock_feedback.save_feedback = AsyncMock(return_value="fb-001")

        app.state.audit_store = mock_audit
        app.state.feedback_store = mock_feedback
        os.environ["REVIEWER_API_KEY"] = "test-key"

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/feedback",
                json={
                    "request_id": "req-001",
                    "audit_id": "audit-001",
                    "reviewer_verdict": "DISAGREE",
                    "reviewer_id": "rev-1",
                    "actual_status": "REJECTED",
                    "reviewer_notes": "Incorrect decision",
                },
                headers={"X-Reviewer-Key": "test-key"},
            )

        assert resp.status_code == 200
        mock_audit.apply_override.assert_called_once()
        os.environ.pop("REVIEWER_API_KEY", None)

    async def test_feedback_summary_computes_accuracy_correctly(self):
        """3 AGREE + 1 DISAGREE should yield accuracy=0.75."""
        records = [
            _make_feedback(ReviewerVerdict.AGREE, request_id=f"r-{i}") for i in range(3)
        ] + [
            _make_feedback(ReviewerVerdict.DISAGREE, request_id="r-dis")
        ]

        total = len(records)
        agree = sum(1 for r in records if r.reviewer_verdict == ReviewerVerdict.AGREE)
        accuracy = agree / total

        assert accuracy == pytest.approx(0.75)

    async def test_calibration_dataset_raises_on_insufficient_records(self):
        """get_calibration_dataset with fewer than min_records should raise."""
        store = FeedbackStore()
        mock_client = AsyncMock()
        mock_client.query = AsyncMock(return_value={"Items": []})
        store._client = mock_client

        with pytest.raises(InsufficientFeedbackError) as exc_info:
            await store.get_calibration_dataset(min_records=30)
        assert exc_info.value.count == 0
        assert exc_info.value.required == 30

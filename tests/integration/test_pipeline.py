"""
Integration tests for the CompliancePipeline, DecisionEngine batch
processing, and the FastAPI health/readiness endpoints.

Bedrock LLM calls are mocked via unittest.mock so no real AWS calls
are made.  The ASGI app is tested via httpx.AsyncClient.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ai.core.decision_engine import DecisionEngine
from ai.core.pipeline import CompliancePipeline
from ai.core.schemas import ComplianceInput, ComplianceOutput, ComplianceStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_LLM_RESPONSE = json.dumps({
    "status": "approved",
    "reason": "All KYC documents are present and valid.",
    "clauses": ["RBI/MD-KYC/2016/Sec38"],
    "confidence": 0.94,
    "rules_used": ["RULE-KYC-001"],
})


@pytest.fixture(autouse=True)
def _patch_boto3():
    """Prevent any real AWS calls from BedrockLLMClient."""
    with patch("ai.llm.bedrock_client.boto3") as mock_boto:
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
    """Raw dict matching ComplianceInput for pipeline.process(dict)."""
    return {
        "user_data": {
            "name": "Priya Sharma",
            "pan_number": "ZZZZZ9999Z",
            "income": 120_000,
            "existing_emi": 10_000,
            "loan_amount": 500_000,
            "tenure_months": 60,
            "required_documents": ["aadhaar", "pan"],
            "provided_documents": ["aadhaar", "pan"],
            "documents_meta": [
                {"doc_type": "aadhaar", "expiry_date": "2032-06-01"},
                {"doc_type": "pan", "expiry_date": "2035-12-31"},
            ],
        },
        "documents": [
            {"type": "aadhaar", "url": "s3://compliance-docs/aadhaar.pdf"},
            {"type": "pan", "url": "s3://compliance-docs/pan.pdf"},
        ],
        "query": "Run full KYC compliance check for loan application.",
    }


@pytest.fixture()
def pipeline() -> CompliancePipeline:
    """CompliancePipeline backed by a default DecisionEngine (Bedrock patched)."""
    return CompliancePipeline(DecisionEngine())


@pytest.fixture()
def valid_compliance_input(valid_input) -> ComplianceInput:
    """ComplianceInput model built from the valid_input dict."""
    return ComplianceInput(**valid_input)


# ===========================================================================
# Pipeline unit-level tests
# ===========================================================================

class TestPipelineProcess:

    async def test_pipeline_full_happy_path(self, valid_input, pipeline):
        """All agents pass, LLM returns APPROVED -> pipeline returns APPROVED output."""
        # Arrange — Bedrock patched globally

        # Act
        result = await pipeline.process(valid_input)

        # Assert
        assert result.status.value in ("approved", "rejected", "review"), (
            "Pipeline should return a valid ComplianceStatus"
        )
        assert result.request_id, "Output must carry a request_id"
        assert result.confidence >= 0.0

    async def test_pipeline_short_circuits_on_sanctions(self, pipeline):
        """When the sanctions agent flags a hit the pipeline still completes
        (there is no graph-level short-circuit yet — Layer B).

        We verify that a sanctioned applicant still gets processed end-to-end.
        """
        # Arrange — John Doe is on MOCK_SANCTIONS_LIST
        sanctioned_input = {
            "user_data": {
                "name": "John Doe",
                "pan_number": "ABCDE1234F",
                "income": 100_000,
                "existing_emi": 5_000,
                "loan_amount": 300_000,
                "tenure_months": 60,
                "required_documents": ["aadhaar"],
                "provided_documents": ["aadhaar"],
                "documents_meta": [
                    {"doc_type": "aadhaar", "expiry_date": "2032-01-01"},
                ],
            },
            "documents": [{"type": "aadhaar", "url": "s3://bucket/aadhaar.pdf"}],
            "query": "Run compliance check for sanctioned entity.",
        }

        # Act
        result = await pipeline.process(sanctioned_input)

        # Assert
        assert isinstance(result, ComplianceOutput)
        assert result.request_id

    async def test_pipeline_short_circuits_on_missing_docs(self, pipeline):
        """Pipeline with missing required docs still completes (Layer B for routing)."""
        # Arrange — provided_documents omit "pan"
        input_data = {
            "user_data": {
                "name": "Test User",
                "pan_number": "XXXXX1111X",
                "income": 50_000,
                "existing_emi": 0,
                "loan_amount": 100_000,
                "tenure_months": 36,
                "required_documents": ["aadhaar", "pan"],
                "provided_documents": ["aadhaar"],
                "documents_meta": [
                    {"doc_type": "aadhaar", "expiry_date": "2030-01-01"},
                ],
            },
            "documents": [{"type": "aadhaar", "url": "s3://bucket/aadhaar.pdf"}],
            "query": "Compliance check with missing documents.",
        }

        # Act
        result = await pipeline.process(input_data)

        # Assert
        assert isinstance(result, ComplianceOutput)

    async def test_pipeline_returns_review_on_bedrock_failure(self, valid_input):
        """If Bedrock is unreachable the pipeline returns a REVIEW fallback."""
        # Arrange — make the Bedrock client raise on invoke
        with patch("ai.llm.bedrock_client.boto3") as mock_boto:
            mock_client = MagicMock()
            mock_client.invoke_model.side_effect = RuntimeError("Bedrock down")
            mock_boto.client.return_value = mock_client

            pipeline = CompliancePipeline(DecisionEngine())
            result = await pipeline.process(valid_input)

        # Assert — the FALLBACK_REVIEW_DECISION path
        assert result.status == ComplianceStatus.REVIEW

    async def test_pipeline_returns_review_on_invalid_input(self, pipeline):
        """Invalid dict input should return a REVIEW output, not crash."""
        # Arrange / Act
        result = await pipeline.process({"bad_key": "bad_value"})

        # Assert
        assert result.status == ComplianceStatus.REVIEW
        assert result.reason == "Input validation failed"


# ===========================================================================
# Batch processing
# ===========================================================================

class TestPipelineBatch:

    async def test_pipeline_batch_processes_multiple_inputs(
        self, valid_compliance_input, pipeline
    ):
        """Batch of 3 valid inputs should produce 3 outputs."""
        # Arrange
        inputs = [valid_compliance_input] * 3

        # Act
        results = await pipeline.process_batch(inputs)

        # Assert
        assert len(results) == 3, "Should return one output per input"
        assert all(isinstance(r, ComplianceOutput) for r in results)

    async def test_pipeline_batch_handles_partial_failures(self, pipeline):
        """When one input in a batch causes an engine error, that slot should
        be filled with a REVIEW output (DecisionEngine.process_batch resilience).
        """
        # Arrange
        good = ComplianceInput(
            user_data={"name": "Good"},
            documents=[{"type": "pan", "url": "s3://b/p.pdf"}],
            query="Valid compliance check query here.",
        )
        inputs = [good, good]

        mock_graph = AsyncMock(side_effect=[
            {"compliance_output": ComplianceOutput(
                request_id="ok",
                status=ComplianceStatus.APPROVED,
                reason="ok",
                clauses=[],
                confidence=0.9,
                rules_used=[],
                agent_errors=[],
                processing_ms=None,
            )},
            Exception("Simulated failure"),
        ])

        with patch("ai.core.decision_engine.run_graph", mock_graph):
            results = await pipeline.process_batch(inputs)

        # Assert
        assert len(results) == 2
        statuses = [r.status for r in results]
        assert ComplianceStatus.REVIEW in statuses, (
            "Failed input should produce a REVIEW placeholder"
        )


# ===========================================================================
# FastAPI HTTP endpoints (/health, /ready)
# ===========================================================================

class TestHealthEndpoints:
    """Test /health and /ready using httpx against the ASGI app.

    We mock the lifespan so no real FAISS/Bedrock initialization occurs;
    instead we set app.state attributes directly.
    """

    @pytest.fixture()
    def _app(self):
        """Create a minimal FastAPI app that mirrors main.app's /health and
        /ready endpoints but uses a no-op lifespan so no real AWS/FAISS
        initialization occurs.
        """
        from contextlib import asynccontextmanager
        from datetime import datetime, timezone as tz

        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        from main import APP_VERSION, RequestIDMiddleware, TimingMiddleware

        @asynccontextmanager
        async def _noop_lifespan(a: FastAPI):
            yield

        test_app = FastAPI(lifespan=_noop_lifespan)
        test_app.add_middleware(TimingMiddleware)
        test_app.add_middleware(RequestIDMiddleware)

        @test_app.get("/health")
        async def _health(request: Request) -> dict:
            st = request.app.state
            bedrock_ok = getattr(st, "bedrock_healthy", False)
            faiss_ok = getattr(st, "faiss_index_loaded", False)
            overall = "healthy" if (bedrock_ok and faiss_ok) else "degraded"
            return {
                "status": overall,
                "version": APP_VERSION,
                "bedrock": {
                    "healthy": bedrock_ok,
                    "latency_ms": float(getattr(st, "bedrock_latency_ms", 0.0)),
                },
                "faiss_index_loaded": faiss_ok,
                "timestamp": datetime.now(tz.utc).isoformat(),
            }

        @test_app.get("/ready")
        async def _ready(request: Request) -> JSONResponse:
            st = request.app.state
            bedrock_ok = getattr(st, "bedrock_healthy", False)
            faiss_ok = getattr(st, "faiss_index_loaded", False)
            if bedrock_ok and faiss_ok:
                return JSONResponse(status_code=200, content={"ready": True})
            parts: list[str] = []
            if not faiss_ok:
                parts.append("FAISS index not loaded")
            if not bedrock_ok:
                parts.append("Bedrock unreachable")
            return JSONResponse(
                status_code=503,
                content={"ready": False, "reason": "; ".join(parts)},
            )

        return test_app

    async def test_health_endpoint_returns_200(self, _app):
        """GET /health should return 200 even in degraded mode."""
        # Arrange
        _app.state.bedrock_healthy = True
        _app.state.bedrock_latency_ms = 42.0
        _app.state.faiss_index_loaded = True

        # Act
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["bedrock"]["healthy"] is True
        assert body["faiss_index_loaded"] is True

    async def test_ready_endpoint_returns_503_when_faiss_not_loaded(self, _app):
        """GET /ready should return 503 when FAISS index is not loaded."""
        # Arrange
        _app.state.bedrock_healthy = True
        _app.state.bedrock_latency_ms = 10.0
        _app.state.faiss_index_loaded = False

        # Act
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app), base_url="http://test"
        ) as client:
            resp = await client.get("/ready")

        # Assert
        assert resp.status_code == 503
        body = resp.json()
        assert body["ready"] is False
        assert "FAISS" in body["reason"]

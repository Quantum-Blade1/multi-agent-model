"""
Unit tests for all compliance agents.

Each agent is tested with a mock AgentState. Bedrock calls are not
involved here — these tests verify agent logic in isolation.
"""

import You are a senior FastAPI engineer building a production async API for an 
NBFC compliance AI system deployed on AWS ECS.

CONTEXT:
- Files: ai/pipeline.py and main.py (project root)
- FastAPI, fully async, AWS ECS deployment
- Uses DecisionEngine from ai.engine.decision_engine
- Uses BedrockLLMClient from ai.tools.function_registry
- FAISS index loaded once at startup via FastAPI lifespan

TASK:
Rewrite ai/pipeline.py and create main.py from scratch.

--- FILE 1: ai/pipeline.py ---

REQUIREMENTS:

1. Class: CompliancePipeline
   
   __init__(self, engine: DecisionEngine):
   - Store engine (injected, not constructed here)

   async def process(self, input: ComplianceInput) -> ComplianceOutput:
   - Validate input using Pydantic (already done by FastAPI, but add 
     a manual .model_validate() call for programmatic use)
   - Log input hash (sha256 of request_id + query) for traceability
   - Call await self.engine.process(input)
   - Return result
   - On ValidationError: return ComplianceOutput with status=REVIEW, 
     reason="Input validation failed", confidence=0.0

   async def process_batch(self, inputs: list[ComplianceInput]) -> list[ComplianceOutput]:
   - Delegate to engine.process_batch()
   - Enforce batch size limit: max 20 items (raise HTTPException 413 if exceeded)

2. FastAPI Router (APIRouter with prefix="/ai", tags=["compliance"]):

   POST /ai/process:
   - Body: ComplianceInput
   - Response: ComplianceOutput
   - Response model: ComplianceOutput
   - Add response_model_exclude_none=True
   - Add OpenAPI description and summary
   - Inject pipeline via FastAPI Depends()

   POST /ai/process/batch:
   - Body: list[ComplianceInput]
   - Response: list[ComplianceOutput]
   - Enforce max 20 items
   - Add X-Batch-Size response header

--- FILE 2: main.py (project root) ---

REQUIREMENTS:

1. FastAPI app instance:
   - title: "NBFC Compliance AI"
   - version: read from environment APP_VERSION (default "1.0.0")
   - docs_url: "/docs" (disable in production via ENV check)

2. Lifespan context manager (startup/shutdown):
   
   Startup:
   - Load FAISS index: FAISSRetriever.load(INDEX_MASTER_PATH)
     where INDEX_MASTER_PATH comes from rag_pipeline/config.py settings
   - Initialize BedrockLLMClient via get_bedrock_client()
   - Run check_bedrock_health() — if unhealthy, log WARNING but do NOT 
     refuse startup (degraded mode)
   - Initialize DecisionEngine with both dependencies injected
   - Initialize CompliancePipeline with engine
   - Store everything on app.state
   - Log "Application startup complete" with all component statuses

   Shutdown:
   - Log "Application shutdown initiated"
   - Close aiobotocore session cleanly

3. Dependency injection functions:
   def get_pipeline(request: Request) -> CompliancePipeline:
       return request.app.state.pipeline

4. MIDDLEWARE STACK (add in this order):
   
   a) CORSMiddleware:
      - origins from CORS_ORIGINS env var (comma-separated), default ["*"]
   
   b) Custom RequestIDMiddleware (implement inline):
      - Read X-Request-ID from incoming header
      - If missing, generate UUID4
      - Attach to request.state.request_id
      - Add X-Request-ID to every response header
   
   c) Custom TimingMiddleware (implement inline):
      - Record start time in request.state
      - Add X-Processing-Time-Ms to every response header
   
   d) Custom StructuredLoggingMiddleware (implement inline):
      - Log every request: method, path, status_code, processing_ms, request_id
      - JSON format: {"timestamp": ..., "level": "INFO", "request_id": ..., 
        "method": ..., "path": ..., "status": ..., "ms": ...}
      - Do NOT log request body (PII risk)

5. EXCEPTION HANDLERS:
   
   RequestValidationError → 422 JSON:
   {"error": "validation_error", "detail": exc.errors(), "request_id": ...}
   
   HTTPException → passthrough with request_id added to body
   
   Exception (catch-all) → 500 JSON:
   {"error": "internal_error", "message": "An unexpected error occurred", "request_id": ...}
   Log the full traceback at CRITICAL level.

6. ROUTES (mounted directly on app):
   
   GET /health:
   - Returns: {
       "status": "healthy" | "degraded",
       "version": APP_VERSION,
       "bedrock": {"healthy": bool, "latency_ms": float},
       "faiss_index_loaded": bool,
       "timestamp": ISO string
     }
   - "degraded" if bedrock health check fails, still returns 200
   
   GET /ready:
   - Returns 200 {"ready": true} only if FAISS index is loaded AND 
     bedrock is reachable
   - Returns 503 {"ready": false, "reason": "..."} otherwise
   - Used by ECS/ALB health checks to gate traffic

7. Include the ai/ router: app.include_router(ai_router)

8. At the bottom:
   if __name__ == "__main__":
       import uvicorn
       uvicorn.run("main:app", host="0.0.0.0", port=8000, 
                   reload=False, workers=1, log_config=None)

Output both files clearly delimited.pytest

from ai.schemas import AgentState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(**overrides) -> AgentState:
    """Create a minimal valid AgentState with optional overrides."""
    defaults = {
        "request_id": "test-request-123",
        "correlation_id": None,
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
        "documents": [
            {"type": "aadhaar", "url": "s3://bucket/aadhaar.pdf"},
            {"type": "pan", "url": "s3://bucket/pan.pdf"}
        ],
        "query": "Check KYC compliance for loan application.",
        "doc_check_passed": True,
        "missing_docs": [],
        "rag_context": [],
        "foir_value": 0.5,
        "foir_passed": True,
        "emi_breakdown": {"principal": 250000, "interest": 50000, "total_emi": 300000},
        "sanctions_hit": False,
        "matched_entity": None,
        "sanctions_score": 0.0,
        "expired_docs": [],
        "temporal_passed": True,
        "days_to_expiry": {"aadhaar": 365, "pan": 730, "address_proof": 180},
        "compliance_output": None,
        "agent_errors": [],
        "short_circuit_reason": None,
        "graph_start_time": 1234567890.0,
        "agent_outputs": {},
    }
    defaults.update(overrides)
    return defaults  # Return dict, since TypedDict is just a dict at runtime


# ---------------------------------------------------------------------------
# document_agent
# ---------------------------------------------------------------------------

class TestDocumentAgent:
    def test_valid_documents(self):
        from ai.agents.document_agent import document_agent

        state = _base_state()
        result = document_agent(state)

        assert result["doc_check_passed"] is True
        assert result["missing_docs"] == []

    def test_empty_documents(self):
        from ai.agents.document_agent import document_agent

        state = _base_state(documents=[])
        result = document_agent(state)

        assert result["doc_check_passed"] is False
        assert result["missing_docs"] == []

    def test_invalid_s3_url(self):
        from ai.agents.document_agent import document_agent

        state = _base_state(documents=[{"type": "aadhaar", "url": "https://not-s3.com/file.pdf"}])
        result = document_agent(state)

        assert result["doc_check_passed"] is False

    def test_missing_document_types(self):
        from ai.agents.document_agent import document_agent

        user_data = _base_state()["user_data"].copy()
        user_data["provided_documents"] = ["aadhaar"]  # missing pan, address_proof
        state = _base_state(user_data=user_data)
        result = document_agent(state)

        assert result["doc_check_passed"] is False
        assert len(result["missing_docs"]) == 2


# ---------------------------------------------------------------------------
# transaction_agent
# ---------------------------------------------------------------------------

class TestTransactionAgent:
    def test_foir_pass(self):
        from ai.agents.transaction_agent import transaction_agent

        state = _base_state()
        result = transaction_agent(state)
        out = result["agent_outputs"]["transaction_agent"]

        assert "foir_pass" in out
        assert "foir_value" in out
        assert isinstance(out["foir_value"], float)
        # (5000 + 300000/60) / 80000 = (5000 + 5000) / 80000 = 0.125
        assert out["foir_pass"] is True

    def test_foir_fail(self):
        from ai.agents.transaction_agent import transaction_agent

        user_data = _base_state()["user_data"].copy()
        user_data["existing_emi"] = 35000  # pushes FOIR way above 0.5
        state = _base_state(user_data=user_data)
        result = transaction_agent(state)
        out = result["agent_outputs"]["transaction_agent"]

        assert out["foir_pass"] is False

    def test_zero_income(self):
        from ai.agents.transaction_agent import transaction_agent

        user_data = _base_state()["user_data"].copy()
        user_data["income"] = 0
        state = _base_state(user_data=user_data)
        result = transaction_agent(state)
        out = result["agent_outputs"]["transaction_agent"]

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
        out = result["agent_outputs"]["sanctions_agent"]

        assert "sanctioned" in out
        assert "match" in out
        assert out["sanctioned"] is False
        assert out["match"] is None

    def test_sanctions_match_by_name(self):
        from ai.agents.sanctions_agent import sanctions_agent

        user_data = _base_state()["user_data"].copy()
        user_data["name"] = "John Doe"  # hardcoded in mock sanctions list
        state = _base_state(user_data=user_data)
        result = sanctions_agent(state)
        out = result["agent_outputs"]["sanctions_agent"]

        assert out["sanctioned"] is True
        assert "John Doe" in out["match"]

    def test_sanctions_match_by_pan(self):
        from ai.agents.sanctions_agent import sanctions_agent

        user_data = _base_state()["user_data"].copy()
        user_data["pan_number"] = "ABCDE1234F"  # hardcoded in mock list
        state = _base_state(user_data=user_data)
        result = sanctions_agent(state)
        out = result["agent_outputs"]["sanctions_agent"]

        assert out["sanctioned"] is True

    def test_case_insensitive_match(self):
        from ai.agents.sanctions_agent import sanctions_agent

        user_data = _base_state()["user_data"].copy()
        user_data["name"] = "john doe"  # lowercase
        state = _base_state(user_data=user_data)
        result = sanctions_agent(state)
        out = result["agent_outputs"]["sanctions_agent"]

        assert out["sanctioned"] is True


# ---------------------------------------------------------------------------
# temporal_agent
# ---------------------------------------------------------------------------

class TestTemporalAgent:
    def test_all_valid(self):
        from ai.agents.temporal_agent import temporal_agent

        state = _base_state()
        result = temporal_agent(state)
        out = result["agent_outputs"]["temporal_agent"]

        assert "expired_docs" in out
        assert "all_valid" in out
        assert out["all_valid"] is True
        assert out["expired_docs"] == []

    def test_expired_document(self):
        from ai.agents.temporal_agent import temporal_agent

        user_data = _base_state()["user_data"].copy()
        user_data["documents_meta"] = [
            {"doc_type": "aadhaar", "expiry_date": "2020-01-01"},
        ]
        state = _base_state(user_data=user_data)
        result = temporal_agent(state)
        out = result["agent_outputs"]["temporal_agent"]

        assert out["all_valid"] is False
        assert len(out["expired_docs"]) == 1
        assert out["expired_docs"][0]["doc_type"] == "aadhaar"

    def test_missing_documents_meta(self):
        from ai.agents.temporal_agent import temporal_agent

        user_data = _base_state()["user_data"].copy()
        user_data.pop("documents_meta", None)
        state = _base_state(user_data=user_data)
        result = temporal_agent(state)
        out = result["agent_outputs"]["temporal_agent"]

        assert out["all_valid"] is True
        assert out["expired_docs"] == []


# ---------------------------------------------------------------------------
# DecisionEngine
# ---------------------------------------------------------------------------

class TestDecisionEngine:
    @pytest.mark.asyncio
    async def test_process_success(self, mocker):
        from ai.engine.decision_engine import DecisionEngine
        from ai.schemas import ComplianceInput, ComplianceOutput, ComplianceStatus

        # Mock dependencies
        mock_bedrock = mocker.AsyncMock()
        mock_rag = mocker.AsyncMock()
        mock_graph = mocker.AsyncMock(return_value={
            "compliance_output": ComplianceOutput(
                request_id="test-123",
                correlation_id=None,
                status=ComplianceStatus.APPROVED,
                reason="All checks passed",
                clauses=["RBI Guideline 1"],
                confidence=0.95,
                rules_used=["doc_check", "foir_check"],
                agent_errors=[],
                short_circuit_reason=None,
                processing_ms=None,
            ),
            "agent_errors": [],
            "short_circuit_reason": None,
        })

        mocker.patch("ai.engine.decision_engine.get_bedrock_client", return_value=mock_bedrock)
        mocker.patch("ai.engine.decision_engine.run_graph", mock_graph)

        engine = DecisionEngine(bedrock_client=mock_bedrock, rag_retriever=mock_rag)
        input_data = ComplianceInput(
            request_id="test-123",
            correlation_id=None,
            user_data=_base_state()["user_data"],
            documents=_base_state()["documents"],
            query="Check compliance",
        )

        result = await engine.process(input_data)

        assert result.request_id == "test-123"
        assert result.status == ComplianceStatus.APPROVED
        assert result.confidence == 0.95
        assert result.processing_ms is not None
        assert result.processing_ms > 0

    @pytest.mark.asyncio
    async def test_process_graph_failure(self, mocker):
        from ai.engine.decision_engine import DecisionEngine
        from ai.schemas import ComplianceInput, ComplianceStatus

        mock_bedrock = mocker.AsyncMock()
        mock_graph = mocker.AsyncMock(side_effect=Exception("Graph error"))

        mocker.patch("ai.engine.decision_engine.get_bedrock_client", return_value=mock_bedrock)
        mocker.patch("ai.engine.decision_engine.run_graph", mock_graph)

        engine = DecisionEngine(bedrock_client=mock_bedrock)
        input_data = ComplianceInput(
            request_id="test-123",
            correlation_id=None,
            user_data=_base_state()["user_data"],
            documents=_base_state()["documents"],
            query="Check compliance",
        )

        result = await engine.process(input_data)

        assert result.status == ComplianceStatus.REVIEW
        assert "Pipeline execution failed" in result.reason
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_process_no_output(self, mocker):
        from ai.engine.decision_engine import DecisionEngine
        from ai.schemas import ComplianceInput, ComplianceStatus

        mock_bedrock = mocker.AsyncMock()
        mock_graph = mocker.AsyncMock(return_value={"compliance_output": None, "agent_errors": [], "short_circuit_reason": None})

        mocker.patch("ai.engine.decision_engine.get_bedrock_client", return_value=mock_bedrock)
        mocker.patch("ai.engine.decision_engine.run_graph", mock_graph)

        engine = DecisionEngine(bedrock_client=mock_bedrock)
        input_data = ComplianceInput(
            request_id="test-123",
            correlation_id=None,
            user_data=_base_state()["user_data"],
            documents=_base_state()["documents"],
            query="Check compliance",
        )

        result = await engine.process(input_data)

        assert result.status == ComplianceStatus.REVIEW
        assert "Pipeline completed without generated compliance output" in result.reason

    @pytest.mark.asyncio
    async def test_process_batch(self, mocker):
        from ai.engine.decision_engine import DecisionEngine
        from ai.schemas import ComplianceInput, ComplianceOutput, ComplianceStatus

        mock_bedrock = mocker.AsyncMock()
        mock_graph = mocker.AsyncMock(return_value={
            "compliance_output": ComplianceOutput(
                request_id="test-123",
                correlation_id=None,
                status=ComplianceStatus.APPROVED,
                reason="Passed",
                clauses=[],
                confidence=1.0,
                rules_used=[],
                agent_errors=[],
                short_circuit_reason=None,
                processing_ms=None,
            )
        })

        mocker.patch("ai.engine.decision_engine.get_bedrock_client", return_value=mock_bedrock)
        mocker.patch("ai.engine.decision_engine.run_graph", mock_graph)

        engine = DecisionEngine(bedrock_client=mock_bedrock)
        inputs = [
            ComplianceInput(
                request_id="test-1",
                correlation_id=None,
                user_data=_base_state()["user_data"],
                documents=_base_state()["documents"],
                query="Check compliance for loan application 1",
            ),
            ComplianceInput(
                request_id="test-2",
                correlation_id=None,
                user_data=_base_state()["user_data"],
                documents=_base_state()["documents"],
                query="Check compliance for loan application 2",
            ),
        ]

        results = await engine.process_batch(inputs)

        assert len(results) == 2
        assert all(r.status == ComplianceStatus.APPROVED for r in results)


# ---------------------------------------------------------------------------
# OutputFormatter
# ---------------------------------------------------------------------------

class TestOutputFormatter:
    def test_format_valid_output(self):
        from ai.engine.output_formatter import OutputFormatter
        from ai.schemas import ComplianceOutput, ComplianceStatus
        import time

        formatter = OutputFormatter()
        start_time = time.monotonic()

        output = ComplianceOutput(
            request_id="test-123",
            correlation_id=None,
            status=ComplianceStatus.APPROVED,
            reason="All good",
            clauses=["Clause 1"],
            confidence=0.85,
            rules_used=["rule1"],
            agent_errors=[],
            short_circuit_reason=None,
            processing_ms=None,
        )

        result = formatter.format(output, start_time)

        assert result.request_id == "test-123"
        assert result.status == ComplianceStatus.APPROVED
        assert result.confidence == 0.85
        assert result.processing_ms is not None
        assert result.processing_ms >= 0

    def test_format_invalid_status(self):
        from ai.engine.output_formatter import OutputFormatter
        from ai.schemas import ComplianceOutput, ComplianceStatus
        import time

        formatter = OutputFormatter()
        start_time = time.monotonic()

        output = ComplianceOutput.model_construct(
            request_id="test-123",
            correlation_id=None,
            status="invalid_status",  # Invalid
            reason="Test",
            clauses=[],
            confidence=0.5,
            rules_used=[],
            agent_errors=[],
            short_circuit_reason=None,
            processing_ms=None,
        )

        result = formatter.format(output, start_time)

        assert result.status == ComplianceStatus.REVIEW

    def test_format_confidence_clamping(self):
        from ai.engine.output_formatter import OutputFormatter
        from ai.schemas import ComplianceOutput, ComplianceStatus
        import time

        formatter = OutputFormatter()
        start_time = time.monotonic()

        # Test high confidence
        output = ComplianceOutput.model_construct(
            request_id="test-123",
            correlation_id=None,
            status=ComplianceStatus.APPROVED,
            reason="Test",
            clauses=[],
            confidence=1.5,  # Above 1.0
            rules_used=[],
            agent_errors=[],
            short_circuit_reason=None,
            processing_ms=None,
        )

        result = formatter.format(output, start_time)
        assert result.confidence == 1.0

        # Test negative confidence
        output.confidence = -0.1
        result = formatter.format(output, start_time)
        assert result.confidence == 0.0

    def test_format_nonrecoverable_error_override(self):
        from ai.engine.output_formatter import OutputFormatter
        from ai.schemas import ComplianceOutput, ComplianceStatus, AgentError, AgentErrorType
        import time

        formatter = OutputFormatter()
        start_time = time.monotonic()

        output = ComplianceOutput(
            request_id="test-123",
            correlation_id=None,
            status=ComplianceStatus.APPROVED,
            reason="Test",
            clauses=[],
            confidence=0.9,
            rules_used=[],
            agent_errors=[AgentError(agent="test", error_type=AgentErrorType.LLM, message="fail", recoverable=False)],
            short_circuit_reason=None,
            processing_ms=None,
        )

        result = formatter.format(output, start_time)

        assert result.status == ComplianceStatus.REVIEW
        assert "Overridden to REVIEW" in result.reason

    def test_format_missing_request_id(self):
        from ai.engine.output_formatter import OutputFormatter
        from ai.schemas import ComplianceOutput, ComplianceStatus
        import time

        formatter = OutputFormatter()
        start_time = time.monotonic()

        output = ComplianceOutput.model_construct(
            request_id=None,  # Missing
            correlation_id=None,
            status=ComplianceStatus.APPROVED,
            reason="Test",
            clauses=[],
            confidence=0.8,
            rules_used=[],
            agent_errors=[],
            short_circuit_reason=None,
            processing_ms=None,
        )

        result = formatter.format(output, start_time)

        assert result.request_id is not None
        assert len(result.request_id) > 0

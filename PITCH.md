# NBFC Compliance AI -- Multi-Agent Decision Engine

> Automated regulatory compliance for Non-Banking Financial Companies using a multi-agent LLM architecture on AWS.

---

## The Problem

Indian NBFCs process thousands of loan applications daily. Each must be checked against a web of RBI regulations -- KYC norms, FOIR limits, sanctions lists, document validity, and temporal constraints. Today this is a manual, error-prone bottleneck where:

- **Compliance officers spend 20--40 minutes per application** cross-referencing regulation documents.
- **Inconsistent decisions** across reviewers create regulatory risk.
- **RBI regulation updates** take weeks to propagate into workflows.

---

## Our Solution

A **six-agent pipeline** where each agent is a domain specialist that examines one compliance dimension, writes its findings into a shared state, and passes control to the next. The final agent synthesises all signals through an LLM on Amazon Bedrock to produce a structured APPROVED / REJECTED / REVIEW decision with cited RBI clauses.

```
  Request ──▶ Document Agent ──▶ RAG Agent ──▶ Transaction Agent
                                                       │
  Response ◀── Decision Agent ◀── Temporal Agent ◀── Sanctions Agent
```

The system doesn't replace the compliance officer -- it gives them a pre-scored, regulation-cited assessment that reduces review time from minutes to seconds.

---

## Architecture

```
┌───────────────────────────────────────────────────────────┐
│                   FastAPI (async)                          │
│         /health    /ready    /ai/process    /ai/batch      │
├───────────────────────────────────────────────────────────┤
│  RequestID Middleware → Timing → Structured JSON Logging   │
├───────────────────────────────────────────────────────────┤
│                  CompliancePipeline                        │
│                  DecisionEngine                            │
├───────────────────────────────────────────────────────────┤
│              LangGraph StateGraph (6 nodes)                │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐        │
│  │ Document │  │   RAG    │  │   Transaction    │        │
│  │  Agent   │→│  Agent   │→│     Agent         │        │
│  │          │  │ (FAISS)  │  │   (FOIR/EMI)     │        │
│  └──────────┘  └──────────┘  └────────┬─────────┘        │
│                                        │                  │
│  ┌──────────┐  ┌──────────┐  ┌────────▼─────────┐        │
│  │ Decision │  │ Temporal │  │   Sanctions      │        │
│  │  Agent   │←│  Agent   │←│     Agent         │        │
│  │(Bedrock) │  │ (Expiry) │  │  (PAN/Name)      │        │
│  └──────────┘  └──────────┘  └──────────────────┘        │
├───────────────────────────────────────────────────────────┤
│  AWS Bedrock (Claude 3 Sonnet)  │  FAISS (BGE embeddings) │
└───────────────────────────────────────────────────────────┘
```

### Why This Architecture

| Decision | Rationale |
|----------|-----------|
| **Multi-agent over monolithic prompt** | Each agent has a single responsibility -- easier to test, debug, and extend. Adding a new compliance dimension means adding one file, not rewriting a mega-prompt. |
| **LangGraph StateGraph** | Typed shared state (`AgentState` TypedDict) eliminates agent-to-agent serialisation. The graph compiles to a DAG we can visualise and reason about. |
| **RAG over fine-tuning** | RBI regulations change quarterly. RAG lets us re-index new circulars in minutes without retraining. FAISS with BGE-small embeddings keeps latency under 50ms for retrieval. |
| **Bedrock over self-hosted LLM** | No GPU fleet to manage. IAM-scoped access. Pay-per-token. Fallback to REVIEW on timeout -- the system never blocks on an LLM failure. |
| **FastAPI async** | Non-blocking I/O for Bedrock calls. Batch endpoint processes up to 20 applications concurrently via `asyncio.gather`. |

---

## What Each Agent Does

| # | Agent | Input | Output | Failure Mode |
|---|-------|-------|--------|--------------|
| 1 | **Document Agent** | Required vs. provided document lists, S3 URLs | `doc_check_passed`, `missing_docs` | Flags missing docs; never crashes |
| 2 | **RAG Agent** | User query | `rag_context` (regulatory text from FAISS) | Empty context on failure; no short-circuit |
| 3 | **Transaction Agent** | Income, existing EMI, loan amount, tenure | `foir_value`, `foir_passed`, `emi_breakdown` | FOIR=1.0 on missing data (safe default) |
| 4 | **Sanctions Agent** | PAN number, applicant name | `sanctions_hit`, `matched_entity` | Exact PAN + case-insensitive name match |
| 5 | **Temporal Agent** | Document expiry dates | `expired_docs`, `temporal_passed` | Skips unparseable dates silently |
| 6 | **Decision Agent** | All agent outputs + RAG context | `ComplianceOutput` (status, reason, clauses, confidence) | Falls back to REVIEW with confidence=0.0 |

---

## Engineering Quality

### Codebase Metrics

| Metric | Value |
|--------|-------|
| Production code | **2,808 lines** across 24 modules |
| Test code | **1,558 lines** across 6 test files |
| Test count | **63 tests** (all passing) |
| Code coverage | **89%** (enforced minimum: 80%) |
| Test : production ratio | **1 : 1.8** |

### Production Patterns Implemented

- **Structured JSON logging** -- every log line is machine-parseable with `request_id`, `correlation_id`, and automatic PII scrubbing (PAN, Aadhaar, email, password never reach stdout).
- **CloudWatch EMF metrics** -- compliance decisions, agent errors, and Bedrock latency emitted as CloudWatch Embedded Metric Format via stdout. Zero SDK dependencies.
- **Request tracing** -- `X-Request-ID` propagated through middleware → contextvars → every log line and metric. End-to-end traceability without an APM agent.
- **Graceful degradation** -- Bedrock down? Decision agent returns REVIEW. FAISS index missing? RAG returns empty context but pipeline continues. `/health` reports "degraded" but still returns 200.
- **Pydantic validation** -- `ComplianceInput` rejects blank queries, auto-generates request IDs. `ComplianceOutput` caps confidence to 0.6 when non-recoverable errors are present (model_validator).
- **Dependency injection** -- `CompliancePipeline` receives its `DecisionEngine` via constructor. FastAPI routes use `Depends()`. Tests swap in mocks with zero monkey-patching.

### Testing Strategy

| Layer | What's Tested | How |
|-------|--------------|-----|
| **Unit** | Each agent in isolation, Pydantic validators, OutputFormatter | Direct function calls with crafted `AgentState` dicts |
| **Integration** | Full pipeline end-to-end (all 6 agents) | Bedrock mocked at `boto3.client` level; real agent logic runs |
| **HTTP** | `/health`, `/ready` endpoints | `httpx.AsyncClient` + `ASGITransport` against FastAPI app |
| **RAG** | Embedder, FAISS indexer, retriever, QueryHandler | In-memory FAISS indexes; real BGE model; no disk I/O |

Every test uses **Arrange / Act / Assert** structure with meaningful assertion messages. No real AWS calls in any test.

---

## Deployment

```
┌─────────────────────────────────────────────┐
│              AWS ECS Fargate                 │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │  Docker (python:3.11-slim)             │ │
│  │  Multi-stage build, non-root user      │ │
│  │  HEALTHCHECK curl /health q30s         │ │
│  │  uvicorn --workers 2                   │ │
│  └────────────────────────────────────────┘ │
│         │              │                    │
│    IAM Task Role   CloudWatch Logs          │
│    (Bedrock access) (stdout → CW)           │
│                                             │
│  ALB ──▶ /ready (503 if FAISS not loaded)  │
└─────────────────────────────────────────────┘
```

- **Multi-stage Dockerfile** -- builder stage compiles C extensions (FAISS, numpy), runtime stage is a clean slim image with a non-root `appuser`.
- **No hardcoded credentials** -- IAM task role provides Bedrock access. `.env` is git-ignored.
- **ALB health gating** -- `/ready` returns 503 until both FAISS index and Bedrock are reachable. Traffic never hits an uninitialized container.

---

## RAG Pipeline (Offline)

```
RBI Website ──▶ Scraper ──▶ Cleaner ──▶ Chunker ──▶ BGE Embedder ──▶ FAISS Index
                  │                       │                              │
              HTML/PDF              512-token chunks              .faiss + .meta.json
              extraction           with 64-token overlap          (master + updated)
```

When RBI publishes new circulars, a team member runs `python -m rag_pipeline.run_pipeline` to rebuild the index. No model retraining required -- the decision agent immediately sees the new regulations at query time.

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| API framework | FastAPI | Async-native, auto OpenAPI docs, Pydantic integration |
| Agent orchestration | LangGraph (StateGraph) | Typed state, compiled graph, async execution |
| LLM | Amazon Bedrock (Claude 3 Sonnet) | Managed, IAM-scoped, no GPU infra |
| Vector search | FAISS + BGE-small-en-v1.5 | Sub-50ms retrieval, 384-dim embeddings, CPU-only |
| Validation | Pydantic v2 | Runtime type safety with model_validators for business rules |
| Observability | stdlib logging + CloudWatch EMF | Zero external dependencies, native AWS integration |
| Containerisation | Docker multi-stage + ECS Fargate | Serverless containers, ALB health gating |
| Testing | pytest + pytest-asyncio | 63 tests, 89% coverage, async-native |

---

## What's Next (Roadmap)

1. **Conditional graph routing** -- short-circuit the pipeline on sanctions hits or missing critical documents (skip remaining agents, go straight to REVIEW/REJECT).
2. **Fuzzy sanctions matching** -- replace exact name match with token-sort ratio (rapidfuzz, threshold >= 85).
3. **Reducing-balance EMI** -- upgrade the flat-EMI approximation to a proper amortisation formula.
4. **Async Bedrock client** -- migrate from sync `boto3` to `aiobotocore` for true non-blocking LLM calls under high concurrency.
5. **Confidence calibration** -- log predictions vs. human reviewer outcomes and fine-tune the confidence scoring.

---

## Run It Yourself

```bash
git clone <repo> && cd multi-agent-model
pip install -r requirements.txt
cp .env.example .env              # configure AWS_REGION + credentials
python -m rag_pipeline.run_pipeline  # build FAISS index
uvicorn main:app --port 8000      # start API
# open http://localhost:8000/docs
```

```bash
# Run tests (no AWS credentials needed)
export PYTHONPATH=$(pwd)
pytest                            # 63 tests, 89% coverage
```

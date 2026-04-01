# File Reference -- NBFC Compliance AI

Every file in the project, what it does, and why it exists.

---

## Root Files

| File | Purpose |
|------|---------|
| `main.py` | **FastAPI application entrypoint.** Configures the lifespan (loads FAISS index, initialises Bedrock client and DecisionEngine at startup), adds middleware (request ID, timing, structured logging, CORS), registers exception handlers (422/HTTPException/500), exposes `/health` and `/ready` endpoints, and mounts the compliance API router. |
| `requirements.txt` | Pinned production and dev dependencies grouped into Core API (FastAPI, uvicorn, Pydantic), AI/ML (LangGraph, sentence-transformers, FAISS, numpy), AWS (boto3, aiobotocore), and Testing (pytest, pytest-asyncio, pytest-cov). |
| `Dockerfile` | Multi-stage Docker build for ECS Fargate. Stage 1 (`builder`) compiles C extensions (FAISS, numpy) into `/install`. Stage 2 (`runtime`) is a clean `python:3.11-slim` with a non-root `appuser` (uid 1001), `HEALTHCHECK` via `curl /health`, and uvicorn with 2 workers. |
| `docker-compose.yml` | Local development only. Single `app` service that builds from the Dockerfile, maps port 8000, loads `.env`, and bind-mounts RAG data directories read-only. |
| `pytest.ini` | Test runner config: `asyncio_mode = auto`, test discovery in `ai/tests` and `rag_pipeline/tests`, CLI logging at WARNING, coverage on the `ai` package with an 80% floor. |
| `.env.example` | Documented template of every environment variable the app reads. Covers app settings, AWS/Bedrock config, FAISS index paths, RAG pipeline directories, sanctions list path, and embedder batch size. Copy to `.env` for local use. |
| `.gitignore` | Excludes `__pycache__`, `.env`, IDE configs, coverage artifacts, virtual environments, and generated RAG data files (`.faiss`, PDFs, HTMLs) while preserving directory structure via `.gitkeep`. |
| `.dockerignore` | Keeps `.git`, tests, docs, raw data, and IDE files out of the Docker build context for faster builds and smaller images. |
| `README.md` | Team onboarding doc: architecture diagram, full directory tree with descriptions, quickstart (clone, install, build index, run API, run tests), Docker/ECS deployment notes, API table, agent pipeline table, env var reference, and team conventions. |
| `PITCH.md` | Stakeholder pitch for judges/reviewers: problem statement, solution overview, architecture rationale, per-agent breakdown, engineering quality metrics (63 tests, 89% coverage), deployment diagram, RAG pipeline, tech stack justification, and roadmap. |

---

## `ai/` -- Core Application Package

### `ai/schemas.py`

Pydantic models and TypedDicts that define the data contracts for the entire system.

- **`ComplianceStatus`** -- Enum: `APPROVED`, `REJECTED`, `REVIEW`.
- **`AgentErrorType`** -- Enum: `VALIDATION`, `LLM`, `RETRIEVAL`, `TIMEOUT`, `S3`, `SANCTIONS`, `UNKNOWN`.
- **`ShortCircuitReason`** -- Enum: `DOCUMENT_MISSING`, `SANCTIONS_HIT`.
- **`AgentError`** -- Pydantic model with `agent`, `error_type`, `message`, `recoverable`, and an auto-UTC `timestamp`.
- **`RagChunk`** -- Pydantic model for a retrieved regulatory text chunk.
- **`ComplianceInput`** -- Request body: `user_data` (dict), `documents` (list of dicts), `query` (string). Auto-generates `request_id` if empty. Rejects blank queries via `field_validator`.
- **`ComplianceOutput`** -- Response body: status, reason, clauses, confidence, rules_used, agent_errors. Has a `model_validator` that caps confidence to 0.6 when any `AgentError` has `recoverable=False`.
- **`AgentState`** -- TypedDict used as the LangGraph shared state. Every agent reads/writes fields on this dict.

### `ai/pipeline.py`

The glue between FastAPI and the decision engine.

- **`CompliancePipeline`** -- Accepts a `DecisionEngine` via constructor injection. `process()` validates input (manual `model_validate` for programmatic use), logs a SHA-256 input hash for traceability, and delegates to the engine. Returns `ComplianceOutput` on success, a REVIEW fallback on validation errors.
- **`process_batch()`** -- Enforces a max of 20 items (raises HTTP 413 if exceeded), delegates to `DecisionEngine.process_batch`.
- **`create_router(get_pipeline)`** -- Factory that returns an `APIRouter` (prefix `/ai`, tag `compliance`) with `POST /ai/process` and `POST /ai/process/batch` endpoints. Uses `Depends()` for pipeline injection.

---

### `ai/agents/` -- LangGraph Agent Nodes

Each file exports a single function with the signature `def agent_name(state: AgentState) -> AgentState`. All agents are synchronous. They read from and write to the shared `AgentState` dict.

#### `ai/agents/graph.py`

Builds and compiles the LangGraph `StateGraph`. Defines the linear execution order:

```
document_agent → rag_agent → transaction_agent → sanctions_agent → temporal_agent → decision_agent → END
```

Exports `compliance_graph` (compiled graph) and `run_graph(initial_state)` (async wrapper around `ainvoke`).

#### `ai/agents/document_agent.py`

**KYC document validation.** Checks that `state["documents"]` is non-empty, each entry is a dict with an `s3://` URL, and (if `user_data` provides `required_documents` and `provided_documents`) that no required documents are missing.

Sets: `doc_check_passed` (bool), `missing_docs` (list of strings).

#### `ai/agents/rag_agent.py`

**Regulatory context retrieval.** Instantiates a `QueryHandler`, calls `handle(query)` to search the FAISS index, and concatenates the top clause texts into `rag_context`. On failure, sets context to empty and logs a warning -- never crashes or short-circuits.

Sets: `rag_context` (string), `agent_outputs["rag_agent"]` (dict with `clauses_found`, `top_clauses`).

#### `ai/agents/transaction_agent.py`

**FOIR (Fixed Obligations to Income Ratio) calculation.** Computes `new_emi = loan_amount / tenure_months` (flat EMI), then `foir = (existing_emi + new_emi) / income`. Threshold is 0.50. If income is zero or missing, FOIR defaults to 1.0 (automatic fail).

Sets: `agent_outputs["transaction_agent"]` (dict with `foir_value`, `foir_pass`, `emi_breakdown`).

#### `ai/agents/sanctions_agent.py`

**Sanctions screening.** Matches `user_data["pan_number"]` and `user_data["name"]` (case-insensitive) against `MOCK_SANCTIONS_LIST` (hardcoded for demo; production would connect to an external API or database).

Sets: `agent_outputs["sanctions_agent"]` (dict with `sanctioned` bool, `match` string or None).

#### `ai/agents/temporal_agent.py`

**Document expiry validation.** Parses `expiry_date` strings from `user_data["documents_meta"]` using multiple date format attempts (`_parse_date`). Flags any document whose expiry is in the past. Silently skips unparseable dates.

Sets: `agent_outputs["temporal_agent"]` (dict with `all_valid` bool, `expired_docs` list).

#### `ai/agents/decision_agent.py`

**Final LLM decision.** Aggregates all `agent_outputs` into a JSON string, formats the prompt using `DECISION_AGENT_PROMPT`, calls Bedrock via `BedrockLLMClient.invoke_with_fallback`, and parses the JSON response into a `ComplianceOutput`.

- `set_bedrock_client(client)` / `get_bedrock_client()` -- injectable client for testing.
- `_normalize_status(raw)` -- maps case-insensitive status strings to `ComplianceStatus` enum values.
- `_parse_response(raw, ...)` -- JSON parse with fallback to REVIEW on any error.
- `_fallback_decision(reason, ...)` -- safe REVIEW output with confidence 0.0.

Sets: `compliance_output` (ComplianceOutput).

---

### `ai/engine/` -- Orchestration Layer

#### `ai/engine/decision_engine.py`

**Orchestrates the full compliance pipeline.** Receives a `BedrockLLMClient` (and optional RAG retriever) via constructor. `process(input)` builds the initial `AgentState` from a `ComplianceInput`, runs the compiled graph via `run_graph`, handles graph exceptions (returns REVIEW fallback), checks for missing `compliance_output`, and formats the final result via `OutputFormatter`.

- `process_batch(inputs)` -- runs multiple inputs concurrently via `asyncio.gather` with per-item exception handling (failed items get a REVIEW placeholder).

#### `ai/engine/output_formatter.py`

**Post-processing for `ComplianceOutput`.** `format(output, start_time)` performs:
- Sets `processing_ms` from elapsed time.
- Coerces invalid status values to REVIEW.
- Clamps confidence to the 0.0--1.0 range.
- Auto-fills missing `request_id` with a UUID.
- Downgrades APPROVED to REVIEW if any `AgentError` has `recoverable=False`, prepending "Overridden to REVIEW" to the reason.

`to_api_response(output)` adds an `api_version` field for API consumers.

---

### `ai/prompts/` -- LLM Prompt Templates

#### `ai/prompts/compliance_prompts.py`

All prompt text used by the decision agent. Stored as module-level string constants:

- **`SYSTEM_PROMPT`** -- Persona (NBFC compliance officer), JSON schema the LLM must follow, confidence calibration rules, bias instruction (default to REVIEW on ambiguity).
- **`FEW_SHOT_EXAMPLES`** -- Three input/output examples for APPROVED, REJECTED, and REVIEW.
- **`RAG_CONTEXT_TEMPLATE`** -- Template for injecting retrieved regulatory chunks, with a WARNING fallback when RAG is empty.
- **`AGENT_SUMMARY_TEMPLATE`** -- Structured summary of all agent signals (docs, FOIR, sanctions, temporal, errors).
- **`FORMAT_REMINDER`** -- Strict instruction to return only valid JSON.
- **`DECISION_AGENT_PROMPT`** -- Assembled template with `{regulatory_context}` and `{agent_outputs}` placeholders. Uses `_escape_braces()` to prevent JSON examples from breaking `str.format()`.
- **`build_decision_prompt(state)`** -- Alternate function-based assembler that fills all templates from an `AgentState` dict.

---

### `ai/rag/` -- Runtime RAG (Query-Time Retrieval)

#### `ai/rag/embedder.py`

**`BGEEmbedder`** -- Wraps `sentence-transformers` with `BAAI/bge-small-en-v1.5`. `embed(texts)` returns L2-normalised `numpy` arrays (384-dim). Raises `ValueError` on empty input. Used at query time to embed the user's query.

#### `ai/rag/indexer.py`

**`FAISSIndexer`** -- Manages a `faiss.IndexFlatIP` index (inner product, which behaves as cosine similarity with normalised vectors). Methods:
- `build_index(embeddings, metadata)` -- creates the index in memory.
- `save(path)` -- writes `{path}.faiss` and `{path}.meta.json`.
- `load(path)` -- reads both files back.

#### `ai/rag/retriever.py`

**`FAISSRetriever`** -- Embeds a query, runs `index.search(top_k)`, attaches metadata and scores to results. Raises `InsufficientRegulationError` when the index is missing, search fails, or no results are found.

`FAISSRetriever.load(path)` -- classmethod that builds a ready-to-query retriever from a saved index path.

#### `ai/rag/query_handler.py`

**`QueryHandler`** -- High-level orchestrator for RAG queries. Resolves index paths from environment variables (`INDEX_MASTER_PATH`, `INDEX_UPDATED_PATH`), loads the FAISS index, runs retrieval, and returns normalised result dicts with keys: `clause_id`, `text`, `source`, `score`. This is what `rag_agent` calls.

---

### `ai/tools/` -- External Service Clients

#### `ai/tools/function_registry.py`

**`BedrockLLMClient`** -- Thin wrapper around Amazon Bedrock `invoke_model` for the Anthropic Claude message format.

- `invoke(system_prompt, user_prompt)` -- calls Bedrock with retry logic (`MAX_RETRIES=2`, `RETRY_DELAY_SECONDS=1.0`). Raises `LLMFailureError` after exhausting retries.
- `invoke_with_fallback(system_prompt, user_prompt)` -- calls `invoke`, but on failure returns `FALLBACK_REVIEW_DECISION` (a hardcoded REVIEW JSON string) instead of raising.
- `get_bedrock_client(region)` -- factory function.

---

### `ai/observability/` -- Logging & Metrics

#### `ai/observability/logger.py`

**Structured JSON logging for CloudWatch.** Every log line is a single-line JSON object to stdout.

- **`REQUEST_ID_VAR`** / **`CORRELATION_ID_VAR`** -- `contextvars.ContextVar` instances set per request, automatically injected into every log line.
- **`set_request_context(request_id, correlation_id)`** -- call in middleware to bind context vars.
- **`PII_FIELDS`** -- frozen set of 7 field names (`pan_number`, `aadhaar_number`, `account_number`, `mobile_number`, `email`, `password`, `dob`).
- **`ScrubFilter`** -- `logging.Filter` that replaces PII field values with `***REDACTED***` before they reach stdout.
- **`get_logger(name)`** -- returns a logger with a JSON handler and scrub filter. Safe to call repeatedly (handler attached once).

#### `ai/observability/metrics.py`

**CloudWatch Embedded Metric Format (EMF) emitters.** Writes EMF JSON to stdout -- CloudWatch auto-parses it into metrics with no SDK needed.

- **`emit_compliance_decision(status, processing_ms, confidence, request_id, short_circuited)`** -- publishes ComplianceDecision (count), ProcessingTime (ms), Confidence.
- **`emit_agent_error(agent_name, error_type, recoverable, request_id)`** -- publishes AgentError (count).
- **`emit_bedrock_call(latency_ms, success, fallback_used)`** -- publishes BedrockLatency (ms) and BedrockFailure (count on failure).

All functions are synchronous (stdout write is fast).

---

### `ai/tests/` -- Test Suite

#### `ai/tests/conftest.py`

**Shared pytest fixtures** used across all test files:

| Fixture | Returns |
|---------|---------|
| `approved_bedrock_response` | JSON string for an APPROVED decision |
| `rejected_bedrock_response` | JSON string for a REJECTED decision |
| `review_bedrock_response` | JSON string for a REVIEW decision |
| `mock_bedrock_client` | `MagicMock` with `invoke_with_fallback` returning approved JSON |
| `mock_rag_retriever` | `MagicMock` with `handle` returning 3 clause dicts |
| `sample_compliance_input` | Fully valid `ComplianceInput` |
| `sample_agent_state` | Complete `AgentState` dict with safe defaults for all keys |
| `expired_doc_input` | `user_data` with an aadhaar expired in 2020 |
| `sanctions_hit_input` | `user_data` with name "John Doe" (on mock sanctions list) |
| `high_foir_input` | `user_data` that produces FOIR ~0.67 (above 0.50 threshold) |

#### `ai/tests/test_schemas.py` -- 5 tests

Tests Pydantic validators and TypedDict structure:
- Auto-generation of `request_id` when empty.
- Rejection of blank/whitespace-only queries.
- Confidence capping to 0.6 on non-recoverable `AgentError`.
- UTC-aware `timestamp` on `AgentError`.
- `sample_agent_state` fixture contains every `AgentState` key.

#### `ai/tests/test_agents.py` -- 33 tests

Tests for every agent plus DecisionEngine and OutputFormatter:

| Class | Tests |
|-------|-------|
| `TestDocumentAgent` | Passes with all docs, fails on missing docs, handles bad S3 URLs, short-circuit behaviour documented as Layer B |
| `TestRagAgent` | Populates context on success, empty on failure, no short-circuit on failure |
| `TestTransactionAgent` | FOIR within limit, FOIR exceeds limit, flat-EMI formula correctness, missing fields handled |
| `TestSanctionsAgent` | Clears clean applicant, flags PAN match, flags name match, short-circuit documented as Layer B |
| `TestTemporalAgent` | Passes valid docs, flags expired, handles unparseable dates, verifies expired doc metadata |
| `TestDecisionAgent` | Parses approved/rejected responses, falls back on invalid JSON, confidence capping |
| `TestDecisionEngine` | Process success, graph failure, no output, batch |
| `TestOutputFormatter` | Valid format, invalid status coercion, confidence clamping, non-recoverable error override, missing request_id |

#### `ai/tests/test_pipeline.py` -- 9 tests

Integration tests with Bedrock mocked at the `boto3.client` level:

| Class | Tests |
|-------|-------|
| `TestPipelineProcess` | Happy path, sanctions input, missing docs, Bedrock failure (REVIEW fallback), invalid input |
| `TestPipelineBatch` | Multiple inputs, partial failure handling |
| `TestHealthEndpoints` | `/health` returns 200, `/ready` returns 503 when FAISS not loaded |

Health/ready tests use `httpx.AsyncClient` with `ASGITransport` against a minimal FastAPI app with mocked `app.state`.

#### `ai/tests/test_rag.py` -- 13 tests

Tests for the full RAG stack with real BGE model and in-memory FAISS (no disk, no network):

| Class | Tests |
|-------|-------|
| `TestBGEEmbedder` | Normalised vectors, empty input raises, correct output shape |
| `TestFAISSIndexer` | In-memory build + search, ntotal, empty raises, metadata mismatch raises, save/load roundtrip |
| `TestFAISSRetriever` | Raises on empty/missing index, returns results with scores |
| `TestQueryHandler` | Formats results with correct keys (clause_id, text, source, score), missing index raises, invalid type raises |

---

## `rag_pipeline/` -- Offline Index-Building Pipeline

This package is run offline (`python -m rag_pipeline.run_pipeline`) to build the FAISS indexes that the runtime API queries. It is **not** imported by the FastAPI app at request time (only `rag_pipeline.config.settings` is used for index paths).

### `rag_pipeline/config.py`

**`Settings`** -- `pydantic-settings` `BaseSettings` that reads from `.env`. Defines:
- RBI circular URLs.
- Data directories (`RAW_DATA_DIR`, `CLEANED_DATA_DIR`, `INDEX_DIR`).
- Index names (`MASTER_INDEX_NAME`, `UPDATED_INDEX_NAME`).
- Chunking parameters (`CHUNK_SIZE=512`, `CHUNK_OVERLAP=64`).
- BGE model name (`BAAI/bge-small-en-v1.5`).
- Target categories for RBI classification.
- AWS credentials (from env vars).

Exports a singleton `settings` instance.

### `rag_pipeline/run_pipeline.py`

**CLI orchestrator.** Runs the full pipeline in stages:

1. **Scrape** -- download RBI circulars (HTML + PDF links).
2. **Extract** -- pull text from PDFs via pdfplumber (PyPDF2 fallback).
3. **Clean** -- normalise Unicode, strip headers/footers, remove noise.
4. **Chunk** -- split into 512-token chunks with 64-token overlap using tiktoken.
5. **Embed** -- batch-encode chunks with BGE-small.
6. **Index** -- build FAISS `IndexFlatIP` and save `.faiss` + `.meta.json`.

Supports `--force` to skip already-completed stages. Writes a `pipeline_manifest.json` with timestamps and counts.

### `rag_pipeline/scraper/rbi_scraper.py`

**`RBIScraper`** -- Uses `requests` with retries to parse RBI circular index pages. Resolves relative URLs, deduplicates by URL, and saves `circular_links.json`. `scrape_rbi()` is the module-level entrypoint that drives scraping from configured target categories.

### `rag_pipeline/scraper/pdf_extractor.py`

**`PDFExtractor`** -- Downloads PDFs to `RAW_DATA_DIR` (skips if already present). Extracts text with `pdfplumber`, falls back to `PyPDF2`. `process_all` writes a `failed.json` for any PDFs that couldn't be extracted.

### `rag_pipeline/scraper/cleaner.py`

**`TextCleaner`** -- Normalises Unicode (NFC), fixes hyphenated line breaks, strips headers/footers and noisy short lines, restricts characters to a safe set. Writes one JSON per circular under `CLEANED_DATA_DIR` with `cleaned_text`. Optional `filter_relevant` keyword gating against target categories.

### `rag_pipeline/chunker/chunker.py`

**`RegulatoryChunker`** -- Splits `cleaned_text` into tiktoken-counted overlapping chunks, preferring breaks at clause-like lines (regex pattern for "Section X" / "Clause Y" headers). Merges tiny trailing chunks. Each chunk dict includes `chunk_id`, metadata, and `clause_hint`.

### `rag_pipeline/ingestion/embedder.py`

**`PipelineEmbedder`** -- Loads `SentenceTransformer` BGE on CPU/CUDA, batch-encodes via `asyncio.to_thread`, validates output shape `(n, 384)`, and L2-normalises with sklearn. `embed_chunks` drops empty texts so embeddings align with filtered chunks.

### `rag_pipeline/ingestion/faiss_builder.py`

**`FAISSBuilder`** -- Builds `faiss.IndexFlatIP`, L2-normalises vectors with `faiss.normalize_L2`, writes `{name}.faiss` and `{name}_meta.json`. `build_two_indexes` supports separate master vs. full corpora. `load` + `search` attaches `similarity_score` to results.

### `rag_pipeline/tests/test_faiss_builder.py` -- 3 tests

Tests `FAISSBuilder.build`/`load`, self-match search (score near 1.0), and dual-index build. Uses temporary `settings.INDEX_DIR` overrides and verifies metadata JSON excludes the `embedding` field.

---

## `__init__.py` Files

Every Python package directory contains an empty `__init__.py` to ensure proper module resolution. These are required for `from ai.agents import ...` style imports to work reliably across all environments (CLI, pytest, Docker, IDE).

Directories with `__init__.py`:
`ai/`, `ai/agents/`, `ai/engine/`, `ai/observability/`, `ai/prompts/`, `ai/rag/`, `ai/tests/`, `ai/tools/`, `rag_pipeline/`, `rag_pipeline/chunker/`, `rag_pipeline/ingestion/`, `rag_pipeline/scraper/`, `rag_pipeline/tests/`.

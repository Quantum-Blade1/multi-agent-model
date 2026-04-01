# NBFC Compliance AI

A multi-agent compliance decision engine for Non-Banking Financial Companies (NBFCs), built with **FastAPI**, **LangGraph**, **AWS Bedrock**, and **FAISS**.

The system evaluates loan applications against RBI regulations by orchestrating six specialised agents through a LangGraph state graph, then synthesises a final APPROVED / REJECTED / REVIEW decision via an LLM on Amazon Bedrock.

---

## Architecture

```
                        ┌─────────────────────────────────┐
                        │          FastAPI (main.py)       │
                        │  /health  /ready  /ai/process    │
                        └──────────────┬──────────────────┘
                                       │
                              CompliancePipeline
                                       │
                              DecisionEngine
                                       │
                        ┌──────────────▼──────────────────┐
                        │     LangGraph State Graph        │
                        │                                  │
                        │  document_agent                  │
                        │       │                          │
                        │  rag_agent (FAISS retrieval)     │
                        │       │                          │
                        │  transaction_agent (FOIR calc)   │
                        │       │                          │
                        │  sanctions_agent (PAN/name)      │
                        │       │                          │
                        │  temporal_agent (doc expiry)     │
                        │       │                          │
                        │  decision_agent (Bedrock LLM)    │
                        └─────────────────────────────────┘
```

Each agent writes its findings into a shared `AgentState` dict. The decision agent reads all signals, queries Bedrock for an LLM judgement, and produces a `ComplianceOutput`.

---

## Directory Structure

```
multi-agent-model/
│
├── main.py                        # FastAPI entrypoint (lifespan, middleware, routes)
├── requirements.txt               # Pinned Python dependencies
├── Dockerfile                     # Multi-stage production Docker image
├── docker-compose.yml             # Local dev compose
├── pytest.ini                     # Test runner configuration
├── .env.example                   # All environment variables with descriptions
├── .gitignore
├── .dockerignore
│
├── ai/                            # ── Core application package ──
│   ├── schemas.py                 # Pydantic models (ComplianceInput/Output, AgentState)
│   ├── pipeline.py                # CompliancePipeline class + FastAPI router factory
│   │
│   ├── agents/                    # LangGraph node functions (one file per agent)
│   │   ├── graph.py               #   StateGraph wiring & run_graph()
│   │   ├── document_agent.py      #   KYC document presence & S3 URL validation
│   │   ├── rag_agent.py           #   FAISS retrieval for regulatory context
│   │   ├── transaction_agent.py   #   FOIR / EMI calculation
│   │   ├── sanctions_agent.py     #   PAN & name screening
│   │   ├── temporal_agent.py      #   Document expiry checks
│   │   └── decision_agent.py      #   Bedrock LLM final decision
│   │
│   ├── engine/                    # Orchestration layer
│   │   ├── decision_engine.py     #   Runs the graph, formats output
│   │   └── output_formatter.py    #   Status coercion, confidence clamping
│   │
│   ├── prompts/                   # LLM prompt templates
│   │   └── compliance_prompts.py  #   System prompt, few-shot, format instructions
│   │
│   ├── rag/                       # Runtime RAG (query-time retrieval)
│   │   ├── embedder.py            #   BGEEmbedder (sentence-transformers)
│   │   ├── indexer.py             #   FAISSIndexer (build / save / load)
│   │   ├── retriever.py           #   FAISSRetriever (similarity search)
│   │   └── query_handler.py       #   QueryHandler (orchestrates embed → search → format)
│   │
│   ├── tools/                     # External service clients
│   │   └── function_registry.py   #   BedrockLLMClient with retry + fallback
│   │
│   ├── observability/             # Structured logging & CloudWatch metrics
│   │   ├── logger.py              #   JSON stdout logger, PII scrubbing, contextvars
│   │   └── metrics.py             #   CloudWatch EMF metric emitters
│   │
│   └── tests/                     # Test suite (pytest + pytest-asyncio)
│       ├── conftest.py            #   Shared fixtures (inputs, mocks, LLM JSON)
│       ├── test_schemas.py        #   Pydantic validation & AgentState tests
│       ├── test_agents.py         #   Per-agent unit tests + DecisionEngine + OutputFormatter
│       ├── test_pipeline.py       #   Integration + FastAPI /health & /ready tests
│       └── test_rag.py            #   Embedder, indexer, retriever, QueryHandler tests
│
└── rag_pipeline/                  # ── Offline index-building pipeline ──
    ├── config.py                  #   pydantic-settings configuration
    ├── run_pipeline.py            #   CLI entrypoint: scrape → clean → chunk → index
    │
    ├── scraper/                   #   RBI circular scraping
    │   ├── rbi_scraper.py
    │   ├── cleaner.py
    │   └── pdf_extractor.py
    │
    ├── chunker/
    │   └── chunker.py             #   Text chunking (size + overlap)
    │
    ├── ingestion/
    │   ├── embedder.py            #   Batch embedding for index building
    │   └── faiss_builder.py       #   Build & persist FAISS indexes
    │
    ├── data/                      #   Generated data (git-ignored except .gitkeep)
    │   ├── raw/                   #     Downloaded HTML / PDFs
    │   ├── cleaned/               #     Cleaned JSON
    │   └── indexes/               #     .faiss + .meta.json index files
    │
    └── tests/
        └── test_faiss_builder.py
```

---

## Quick Start

### 1. Clone & install

```bash
git clone <repo-url> && cd multi-agent-model
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set AWS_REGION, BEDROCK_MODEL_ID, and (for local dev) AWS credentials
```

### 3. Build the FAISS index (first time)

```bash
python -m rag_pipeline.run_pipeline
```

This scrapes RBI circulars, cleans, chunks, embeds, and writes the FAISS index files into `rag_pipeline/data/indexes/`.

### 4. Run the API

```bash
uvicorn main:app --reload --port 8000
```

Then open [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive API docs.

### 5. Run tests

```bash
# Set PYTHONPATH so imports resolve from the project root
export PYTHONPATH=$(pwd)     # Windows: $env:PYTHONPATH = (Get-Location).Path

pytest                       # runs ai/tests + rag_pipeline/tests with coverage
pytest ai/tests/ --no-cov   # quick run without coverage
```

---

## Docker

### Build & run locally

```bash
docker compose up --build
```

### Production (ECS Fargate)

The `Dockerfile` produces a lean multi-stage image. Mount or bake FAISS index files into `rag_pipeline/data/indexes/`. AWS credentials come from the ECS task IAM role — never bake them into the image.

---

## API Endpoints

| Method | Path               | Description                        |
|--------|--------------------|------------------------------------|
| GET    | `/health`          | Liveness check (always 200)        |
| GET    | `/ready`           | Readiness gate for ECS/ALB         |
| POST   | `/ai/process`      | Single compliance decision         |
| POST   | `/ai/process/batch` | Batch (up to 20 inputs)           |

---

## Agent Pipeline

| Agent               | Responsibility                                   | Key State Fields Set                      |
|---------------------|--------------------------------------------------|-------------------------------------------|
| `document_agent`    | Validates required KYC docs are present           | `doc_check_passed`, `missing_docs`        |
| `rag_agent`         | Retrieves regulatory context from FAISS           | `rag_context`, `agent_outputs["rag_agent"]` |
| `transaction_agent` | Computes FOIR (Fixed Obligations to Income Ratio) | `foir_value`, `foir_passed`, `emi_breakdown` |
| `sanctions_agent`   | Screens against sanctions list (PAN + name)       | `sanctions_hit`, `matched_entity`         |
| `temporal_agent`    | Checks document expiry dates                      | `expired_docs`, `temporal_passed`         |
| `decision_agent`    | Calls Bedrock LLM for final APPROVED/REJECTED/REVIEW | `compliance_output`                   |

---

## Environment Variables

See [`.env.example`](.env.example) for the full list with descriptions. Key variables:

| Variable           | Default                                       | Purpose                          |
|--------------------|-----------------------------------------------|----------------------------------|
| `ENVIRONMENT`      | `development`                                 | Controls log level, metric dims  |
| `ENV`              | `development`                                 | Controls `/docs` visibility      |
| `AWS_REGION`       | `us-east-1`                                   | Bedrock + other AWS services     |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-sonnet-20240229-v1:0`     | Foundation model for decisions   |
| `CORS_ORIGINS`     | `*`                                           | Allowed origins (comma-sep)      |
| `INDEX_DIR`        | `rag_pipeline/data/indexes/`                  | Where FAISS indexes live         |

---

## Testing

- **60 tests** across 5 files, **89% code coverage**
- All Bedrock / AWS calls are mocked — tests never hit real AWS
- FAISS tests use in-memory indexes — no disk or network I/O
- `pytest.ini` enforces `--cov-fail-under=80`

---

## Team Conventions

- **Imports**: Always use absolute imports from the project root (`from ai.schemas import ...`)
- **State access**: Use bracket notation on `AgentState` (`state["field"]`), never dot notation
- **Logging**: Use `from ai.observability.logger import get_logger` — never `print()` or bare `logging`
- **Secrets**: Never commit `.env` — use `.env.example` as the template
- **Tests**: Every new agent or module needs tests in `ai/tests/` with `async def` + Arrange/Act/Assert

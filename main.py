"""
NBFC Compliance AI — FastAPI application entrypoint for AWS ECS.

Loads FAISS once at startup, wires Bedrock and the LangGraph decision engine,
and exposes health, readiness, and compliance APIs.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import boto3
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ai.audit.router import audit_router
from ai.audit.store import AuditStore
from ai.calibration.engine import CalibrationEngine
from ai.calibration.router import calibration_router
from ai.calibration.store import CalibrationStore
from ai.compliance_loop.feedback_router import feedback_router
from ai.compliance_loop.feedback_store import FeedbackStore
from ai.compliance_loop.index_swapper import IndexSwapper
from ai.compliance_loop.index_watcher import IndexWatcher
from ai.compliance_loop.rule_engine import RuleEngine
from ai.compliance_loop.rule_router import rule_router
from ai.engine.decision_engine import DecisionEngine
from ai.pipeline import CompliancePipeline, create_router
from ai.rag.retriever import FAISSRetriever
from ai.tools.function_registry import BedrockLLMClient, get_bedrock_client
from rag_pipeline.config import settings

APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
ENV = os.getenv("ENV", "development")
INDEX_MASTER_PATH = os.path.join(settings.INDEX_DIR, settings.MASTER_INDEX_NAME)

logger = logging.getLogger(__name__)


def check_bedrock_health(client: BedrockLLMClient) -> tuple[bool, float]:
    """Return ``(healthy, latency_ms)`` via a lightweight Bedrock control-plane call."""
    t0 = time.perf_counter()
    try:
        region = client.client.meta.region_name
        br = boto3.client("bedrock", region_name=region)
        br.list_foundation_models(maxResults=1)
        ms = (time.perf_counter() - t0) * 1000.0
        return True, ms
    except Exception:
        ms = (time.perf_counter() - t0) * 1000.0
        return False, ms


def get_pipeline(request: Request) -> CompliancePipeline:
    """FastAPI dependency: compliance pipeline from application state."""
    return request.app.state.pipeline


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000.0
        response.headers["X-Processing-Time-Ms"] = f"{ms:.2f}"
        return response


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000.0
        rid = getattr(request.state, "request_id", None)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "request_id": rid,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round(ms, 2),
        }
        logging.getLogger("http.access").info(json.dumps(payload))
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Application startup initiated")

    # -- FAISS via IndexSwapper (supports hot-swap at runtime) ---------------
    index_swapper = IndexSwapper()
    faiss_retriever: FAISSRetriever | None = None
    faiss_loaded = False
    try:
        path = os.path.abspath(INDEX_MASTER_PATH)
        index_swapper.load_initial("master", path)
        faiss_retriever = index_swapper.get_retriever("master")
        faiss_loaded = True
        logger.info("FAISS index loaded from %s", path)
    except Exception as exc:
        logger.warning("FAISS index load failed (degraded mode): %s", exc)

    # -- Bedrock client ------------------------------------------------------
    bedrock_client = get_bedrock_client()
    bedrock_ok, bedrock_ms = check_bedrock_health(bedrock_client)
    if not bedrock_ok:
        logger.warning(
            "Bedrock health check failed (degraded mode): latency_ms=%.2f", bedrock_ms
        )

    # -- Decision engine + audit + pipeline ----------------------------------
    engine = DecisionEngine(bedrock_client=bedrock_client, rag_retriever=faiss_retriever)

    audit_store = AuditStore()
    pipeline = CompliancePipeline(engine, audit_store=audit_store)

    # -- Rule engine ---------------------------------------------------------
    rule_engine = RuleEngine()

    # -- Feedback store ------------------------------------------------------
    feedback_store = FeedbackStore()

    # -- Calibration engine + store ------------------------------------------
    calibration_store = CalibrationStore()
    calibration_engine = CalibrationEngine(rule_engine)

    # -- Index watcher (background S3 poller) --------------------------------
    index_watcher = IndexWatcher(index_swapper)
    await index_watcher.start()

    # -- Store everything on app.state ---------------------------------------
    app.state.bedrock_client = bedrock_client
    app.state.faiss_retriever = faiss_retriever
    app.state.engine = engine
    app.state.pipeline = pipeline
    app.state.audit_store = audit_store
    app.state.bedrock_healthy = bedrock_ok
    app.state.bedrock_latency_ms = bedrock_ms
    app.state.faiss_index_loaded = faiss_loaded
    app.state.index_swapper = index_swapper
    app.state.index_watcher = index_watcher
    app.state.rule_engine = rule_engine
    app.state.feedback_store = feedback_store
    app.state.calibration_store = calibration_store
    app.state.calibration_engine = calibration_engine

    logging.info(
        "Application startup complete — faiss_index_loaded=%s bedrock_healthy=%s "
        "bedrock_latency_ms=%.2f",
        faiss_loaded,
        bedrock_ok,
        bedrock_ms,
    )

    yield

    logging.info("Application shutdown initiated")
    await index_watcher.stop()
    await index_swapper.close()
    await calibration_store.close()
    await feedback_store.close()
    await rule_engine.close()
    await audit_store.close()


docs_url = None if ENV == "production" else "/docs"

app = FastAPI(
    title="NBFC Compliance AI",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url=docs_url,
)

_cors_raw = os.getenv("CORS_ORIGINS", "*")
_cors_origins = (
    ["*"]
    if _cors_raw.strip() == "*"
    else [o.strip() for o in _cors_raw.split(",") if o.strip()]
)

app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "detail": exc.errors(),
            "request_id": rid,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    detail = exc.detail
    if isinstance(detail, dict):
        body = {**detail, "request_id": rid}
    else:
        body = {"detail": detail, "request_id": rid}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    logging.critical("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred",
            "request_id": rid,
        },
    )


@app.get("/health")
async def health(request: Request) -> dict:
    st = request.app.state
    bedrock_ok = getattr(st, "bedrock_healthy", False)
    faiss_ok = getattr(st, "faiss_index_loaded", False)
    overall = "healthy" if (bedrock_ok and faiss_ok) else "degraded"

    re = getattr(st, "rule_engine", None)
    rule_cache_age = (
        round(time.monotonic() - re._cache_loaded_at, 1)
        if re and getattr(re, "_cache_loaded_at", None)
        else None
    )

    iw = getattr(st, "index_watcher", None)
    ix = getattr(st, "index_swapper", None)

    cal_ece: float | None = None
    cal_status = "uncalibrated"
    cs = getattr(st, "calibration_store", None)
    if cs is not None:
        try:
            latest = await cs.get_latest_report()
            if latest is not None:
                cal_ece = latest.ece
                age = datetime.now(timezone.utc) - latest.generated_at.replace(
                    tzinfo=timezone.utc
                ) if latest.generated_at.tzinfo is None else (
                    datetime.now(timezone.utc) - latest.generated_at
                )
                cal_status = "stale" if age > timedelta(days=7) else "healthy"
        except Exception:
            pass

    return {
        "status": overall,
        "version": APP_VERSION,
        "bedrock": {
            "healthy": bedrock_ok,
            "latency_ms": float(getattr(st, "bedrock_latency_ms", 0.0)),
        },
        "faiss_index_loaded": faiss_ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "audit_store": {
            "connected": getattr(st, "audit_store", None) is not None,
        },
        "rule_engine": {
            "connected": re is not None,
            "cache_age_seconds": rule_cache_age,
            "rule_count": len(re._cache) if re and hasattr(re, "_cache") and re._cache else 0,
        },
        "index_watcher": {
            "running": (
                iw._task is not None and not iw._task.done()
                if iw and hasattr(iw, "_task") and iw._task
                else False
            ),
            "last_poll_at": None,
            "swap_count": ix._swap_count if ix and hasattr(ix, "_swap_count") else 0,
        },
        "calibration": {
            "latest_ece": cal_ece,
            "status": cal_status,
        },
    }


@app.get("/ready")
async def ready(request: Request) -> JSONResponse:
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


app.include_router(create_router(get_pipeline))
app.include_router(audit_router)
app.include_router(rule_router)
app.include_router(feedback_router)
app.include_router(calibration_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,
        log_config=None,
    )

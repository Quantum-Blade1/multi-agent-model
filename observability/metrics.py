"""
CloudWatch Embedded Metric Format (EMF) emitter for the NBFC Compliance AI system.

All metrics are written as single-line JSON to stdout.  When running on
AWS ECS with the CloudWatch Logs agent, lines that contain the ``_aws``
key are automatically parsed as EMF and published to CloudWatch Metrics —
no sidecar or SDK required.

Reference: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
SERVICE: str = "compliance-ai"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ts_ms() -> int:
    """Current UTC timestamp in epoch milliseconds (CloudWatch requirement)."""
    return int(time.time() * 1000)


def _emit(
    metrics: list[dict[str, str]],
    dimensions: list[list[str]],
    values: dict[str, Any],
) -> None:
    """Write a single EMF blob to stdout.

    Args:
        metrics: ``[{"Name": "Foo", "Unit": "Count"}, ...]``
        dimensions: ``[["Dim1", "Dim2"]]``
        values: Flat dict of dimension values **and** metric values.
    """
    payload: dict[str, Any] = {
        "_aws": {
            "Timestamp": _ts_ms(),
            "CloudWatchMetrics": [
                {
                    "Namespace": "NBFCCompliance",
                    "Dimensions": [["Environment", "Service", *d] for d in dimensions],
                    "Metrics": metrics,
                }
            ],
        },
        "Environment": ENVIRONMENT,
        "Service": SERVICE,
        **values,
    }
    sys.stdout.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Public emitters
# ---------------------------------------------------------------------------

def emit_compliance_decision(
    status: str,
    processing_ms: float,
    confidence: float,
    request_id: str,
    short_circuited: bool,
) -> None:
    """Emit metrics for a completed compliance decision.

    Published metrics:
        - **ComplianceDecision** (Count) — always 1
        - **ProcessingTime** (Milliseconds)
        - **Confidence** (None — dimensionless)

    Dimensions: ``Status``, ``ShortCircuited``
    """
    _emit(
        metrics=[
            {"Name": "ComplianceDecision", "Unit": "Count"},
            {"Name": "ProcessingTime", "Unit": "Milliseconds"},
            {"Name": "Confidence", "Unit": "None"},
        ],
        dimensions=[["Status", "ShortCircuited"]],
        values={
            "ComplianceDecision": 1,
            "ProcessingTime": processing_ms,
            "Confidence": confidence,
            "Status": status,
            "ShortCircuited": str(short_circuited),
            "RequestId": request_id,
        },
    )


def emit_agent_error(
    agent_name: str,
    error_type: str,
    recoverable: bool,
    request_id: str,
) -> None:
    """Emit a metric each time an agent records an error.

    Published metrics:
        - **AgentError** (Count) — always 1

    Dimensions: ``AgentName``, ``ErrorType``
    """
    _emit(
        metrics=[
            {"Name": "AgentError", "Unit": "Count"},
        ],
        dimensions=[["AgentName", "ErrorType"]],
        values={
            "AgentError": 1,
            "AgentName": agent_name,
            "ErrorType": error_type,
            "Recoverable": str(recoverable),
            "RequestId": request_id,
        },
    )


def emit_bedrock_call(
    latency_ms: float,
    success: bool,
    fallback_used: bool,
) -> None:
    """Emit metrics for every Bedrock LLM invocation.

    Published metrics:
        - **BedrockLatency** (Milliseconds)
        - **BedrockFailure** (Count) — emitted only on failure

    Dimensions: ``FallbackUsed``
    """
    metrics: list[dict[str, str]] = [
        {"Name": "BedrockLatency", "Unit": "Milliseconds"},
    ]
    values: dict[str, Any] = {
        "BedrockLatency": latency_ms,
        "FallbackUsed": str(fallback_used),
    }

    if not success:
        metrics.append({"Name": "BedrockFailure", "Unit": "Count"})
        values["BedrockFailure"] = 1

    _emit(
        metrics=metrics,
        dimensions=[["FallbackUsed"]],
        values=values,
    )

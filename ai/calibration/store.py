"""
DynamoDB-backed persistence for calibration reports.

Stores :class:`CalibrationReport` history so compliance officers can
review how the system's confidence calibration has evolved over time.

DynamoDB table::

    nbfc-calibration-reports
        PK: report_id (S)
        GSI-1: date-index   PK: generated_date (S, YYYY-MM-DD)
                             SK: generated_at (S, ISO-8601)
        TTL:   expires_at (N) — 7 years per RBI retention
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import aiobotocore.session
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from pydantic import BaseModel

from ai.calibration.engine import CalibrationReport
from ai.observability.logger import get_logger

log = get_logger("ai.calibration.store")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CALIBRATION_TABLE = os.getenv("CALIBRATION_REPORTS_TABLE", "nbfc-calibration-reports")
_RBI_RETENTION_SECONDS = int(7 * 365.25 * 86400)

# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def _floats_to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(item) for item in obj]
    return obj


def _decimals_to_float(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimals_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimals_to_float(item) for item in obj]
    return obj


def _report_to_dynamo(report: CalibrationReport) -> dict[str, Any]:
    data = report.model_dump(mode="json")
    prepared = _floats_to_decimal(data)
    prepared["generated_date"] = report.generated_at.strftime("%Y-%m-%d")
    prepared["expires_at"] = (
        int(report.generated_at.timestamp()) + _RBI_RETENTION_SECONDS
    )
    return {k: _serializer.serialize(v) for k, v in prepared.items()}


def _report_from_dynamo(item: dict[str, Any]) -> CalibrationReport:
    raw = {k: _deserializer.deserialize(v) for k, v in item.items()}
    data = _decimals_to_float(raw)
    data.pop("expires_at", None)
    data.pop("generated_date", None)
    return CalibrationReport.model_validate(data, strict=False)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class CalibrationStore:
    """Async DynamoDB-backed store for calibration report history.

    Usage::

        store = CalibrationStore()
        await store.save_report(report)
        latest = await store.get_latest_report()
    """

    def __init__(
        self,
        table_name: str | None = None,
        region: str | None = None,
    ) -> None:
        self._table = table_name or CALIBRATION_TABLE
        self._region = region or os.getenv("AWS_REGION", "ap-south-1")
        self._session = aiobotocore.session.get_session()
        self._client: Any = None
        self._client_ctx: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            self._client_ctx = self._session.create_client(
                "dynamodb", region_name=self._region
            )
            self._client = await self._client_ctx.__aenter__()
        return self._client

    async def close(self) -> None:
        if self._client_ctx is not None:
            await self._client_ctx.__aexit__(None, None, None)
            self._client = None
            self._client_ctx = None

    # ── Write ─────────────────────────────────────────────────────────────

    async def save_report(self, report: CalibrationReport) -> str:
        """Persist a calibration report. Returns the ``report_id``."""
        client = await self._get_client()
        item = _report_to_dynamo(report)

        await client.put_item(TableName=self._table, Item=item)

        log.info(
            "Calibration report saved",
            extra={
                "report_id": report.report_id,
                "ece": report.ece,
                "feedback_count": report.feedback_count,
                "operation": "save_report",
            },
        )
        return report.report_id

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_latest_report(self) -> CalibrationReport | None:
        """Return the most recent calibration report, or ``None``.

        Queries the ``date-index`` GSI for up to 7 recent days to find
        the latest report, since GSI PK is ``generated_date`` (YYYY-MM-DD).
        """
        client = await self._get_client()
        now = datetime.now(UTC)

        for days_back in range(7):
            date_str = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
            response = await client.query(
                TableName=self._table,
                IndexName="date-index",
                KeyConditionExpression="generated_date = :d",
                ExpressionAttributeValues={":d": {"S": date_str}},
                ScanIndexForward=False,
                Limit=1,
            )
            items = response.get("Items", [])
            if items:
                return _report_from_dynamo(items[0])

        return None

    async def list_reports(self, limit: int = 20) -> list[CalibrationReport]:
        """Return the most recent reports (up to ``limit``).

        Scans across recent days on the GSI to collect enough results.
        """
        client = await self._get_client()
        now = datetime.now(UTC)
        reports: list[CalibrationReport] = []

        for days_back in range(30):
            if len(reports) >= limit:
                break
            date_str = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
            response = await client.query(
                TableName=self._table,
                IndexName="date-index",
                KeyConditionExpression="generated_date = :d",
                ExpressionAttributeValues={":d": {"S": date_str}},
                ScanIndexForward=False,
                Limit=limit - len(reports),
            )
            for item in response.get("Items", []):
                reports.append(_report_from_dynamo(item))

        return reports[:limit]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store: CalibrationStore | None = None
_store_lock = asyncio.Lock()


async def get_calibration_store() -> CalibrationStore:
    """Return the singleton :class:`CalibrationStore`."""
    global _store
    if _store is not None:
        return _store
    async with _store_lock:
        if _store is None:
            _store = CalibrationStore()
    return _store

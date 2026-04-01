"""
Background S3 poller that detects new FAISS index builds and triggers
zero-downtime hot-swaps.

The ``IndexWatcher`` runs as an ``asyncio.Task`` inside the FastAPI process.
It periodically checks S3 for ``manifest.json`` files deposited by the
RAG ingestion pipeline (``rag_pipeline/``).  When a manifest with a newer
``built_at`` timestamp is found, it delegates to ``IndexSwapper.swap()``
to download, validate, and atomically replace the in-process retriever.

Resilience
----------
* Transient S3 errors are caught and logged; the loop never crashes.
* ``CancelledError`` is respected so the task shuts down cleanly.
* Each poll is independent — a failed swap does not block future polls.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

import aiobotocore.session
from pydantic import BaseModel, Field

from ai.compliance_loop.index_swapper import IndexSwapper
from ai.observability.logger import get_logger

log = get_logger("ai.compliance_loop.index_watcher")

INDEX_S3_BUCKET = os.getenv("INDEX_S3_BUCKET", "nbfc-compliance-indexes")
INDEX_WATCH_PREFIX = os.getenv("INDEX_WATCH_PREFIX", "indexes/")
INDEX_POLL_INTERVAL_SEC = int(os.getenv("INDEX_POLL_INTERVAL_SEC", "120"))


class IndexManifest(BaseModel):
    """Metadata deposited by the RAG pipeline when a new index is built.

    The pipeline writes this as ``{prefix}{index_type}/manifest.json`` in S3.
    """

    index_type: str = Field(description="'master' or 'updated'.")
    built_at: datetime = Field(description="UTC timestamp when the index was built.")
    vector_count: int = Field(description="Number of vectors in the index.")
    s3_faiss_key: str = Field(description="S3 key for the .faiss file.")
    s3_meta_key: str = Field(description="S3 key for the .meta.json file.")
    pipeline_run_id: str = Field(description="UUID from the pipeline run that built this index.")


class IndexWatcher:
    """Background task that polls S3 for new index manifests.

    Usage from lifespan::

        watcher = IndexWatcher(swapper, poll_interval=120)
        await watcher.start()
        # ... yield ...
        await watcher.stop()
    """

    INDEX_TYPES = ("master", "updated")

    def __init__(
        self,
        swapper: IndexSwapper,
        poll_interval: int | None = None,
    ) -> None:
        self._swapper = swapper
        self._poll_interval = poll_interval or INDEX_POLL_INTERVAL_SEC
        self._last_seen: dict[str, datetime] = {}
        self._task: asyncio.Task[None] | None = None
        self._session = aiobotocore.session.get_session()
        self._s3_client: Any = None
        self._s3_ctx: Any = None

    async def _get_s3_client(self) -> Any:
        """Return a cached async S3 client."""
        if self._s3_client is None:
            region = os.getenv("AWS_REGION", "ap-south-1")
            self._s3_ctx = self._session.create_client(
                "s3", region_name=region
            )
            self._s3_client = await self._s3_ctx.__aenter__()
        return self._s3_client

    async def _close_client(self) -> None:
        if self._s3_ctx is not None:
            await self._s3_ctx.__aexit__(None, None, None)
            self._s3_client = None
            self._s3_ctx = None

    async def start(self) -> None:
        """Spawn the background polling task."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._watch_loop(), name="index-watcher")
        log.info(
            "IndexWatcher started",
            extra={
                "poll_interval_sec": self._poll_interval,
                "operation": "start",
            },
        )

    async def stop(self) -> None:
        """Cancel the background task and release resources."""
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None
        await self._close_client()
        log.info("IndexWatcher stopped", extra={"operation": "stop"})

    async def _watch_loop(self) -> None:
        """Infinite poll loop.  Catches everything except ``CancelledError``."""
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error(
                    "IndexWatcher poll error",
                    extra={"error": str(exc), "operation": "_watch_loop"},
                )
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        """Check each index type for a newer manifest and trigger swap."""
        for index_type in self.INDEX_TYPES:
            manifest = await self._fetch_s3_manifest(index_type)
            if manifest is None:
                continue

            last = self._last_seen.get(index_type)
            if last is not None and manifest.built_at <= last:
                continue

            log.info(
                "New index detected",
                extra={
                    "index_type": index_type,
                    "built_at": manifest.built_at.isoformat(),
                    "vector_count": manifest.vector_count,
                    "pipeline_run_id": manifest.pipeline_run_id,
                    "operation": "_poll_once",
                },
            )

            result = await self._swapper.swap(manifest)
            if result.success:
                self._last_seen[index_type] = manifest.built_at
            else:
                log.warning(
                    "Index swap failed — will retry next poll",
                    extra={
                        "index_type": index_type,
                        "reason": result.reason,
                        "operation": "_poll_once",
                    },
                )

    async def _fetch_s3_manifest(self, index_type: str) -> IndexManifest | None:
        """Fetch and parse ``manifest.json`` from S3 for a given index type.

        Returns:
            The parsed manifest, or ``None`` if the object does not exist.
        """
        key = f"{INDEX_WATCH_PREFIX}{index_type}/manifest.json"
        client = await self._get_s3_client()

        try:
            resp = await client.get_object(Bucket=INDEX_S3_BUCKET, Key=key)
            body = await resp["Body"].read()
            data = json.loads(body)
            return IndexManifest.model_validate(data)
        except client.exceptions.NoSuchKey:
            return None
        except Exception as exc:
            log.warning(
                "Failed to fetch manifest",
                extra={
                    "index_type": index_type,
                    "s3_key": key,
                    "error": str(exc),
                    "operation": "_fetch_s3_manifest",
                },
            )
            return None

"""
Zero-downtime FAISS index hot-swapper.

Handles downloading new index files from S3 and atomically swapping the
in-process ``FAISSRetriever`` reference while concurrent requests continue
using the old retriever.  The old retriever is released to the garbage
collector once the swap completes.

Architecture
------------
* Downloads and loads happen **outside** the ``asyncio.Lock`` to avoid
  blocking request-serving coroutines during long I/O.
* Only the final pointer-swap is performed under the lock, making it
  effectively instantaneous.
* A validation query is run against the new retriever before committing
  the swap — if it fails, the swap is aborted and the old retriever
  remains active.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from typing import Any

import aiobotocore.session
from pydantic import BaseModel, Field

from ai.observability.logger import get_logger
from ai.rag.retriever import FAISSRetriever

log = get_logger("ai.compliance_loop.index_swapper")

INDEX_S3_BUCKET = os.getenv("INDEX_S3_BUCKET", "nbfc-compliance-indexes")
INDEX_LOCAL_CACHE_DIR = os.getenv("INDEX_LOCAL_CACHE_DIR", "/tmp/faiss_cache/")

VALIDATION_QUERY = "NBFC capital adequacy requirements"


class IndexNotLoadedError(Exception):
    """Raised when a retriever is requested but has not been loaded yet."""


class SwapResult(BaseModel):
    """Outcome of an index hot-swap attempt."""

    success: bool
    index_type: str
    old_vector_count: int | None = None
    new_vector_count: int | None = None
    duration_ms: float
    reason: str | None = None


class IndexSwapper:
    """Manages live FAISS retriever instances and performs zero-downtime swaps.

    Usage from lifespan::

        swapper = IndexSwapper()
        swapper.load_initial("master", "/path/to/master")
        app.state.index_swapper = swapper

    Usage from ``IndexWatcher``::

        result = await swapper.swap(manifest)
        if result.success:
            log.info("Swapped index: %s", result.index_type)
    """

    def __init__(self) -> None:
        self._retrievers: dict[str, FAISSRetriever] = {}
        self._lock = asyncio.Lock()
        self._swap_count: int = 0
        self._last_swap_at: dict[str, datetime] = {}
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

    async def close(self) -> None:
        """Release the aiobotocore S3 client."""
        if self._s3_ctx is not None:
            await self._s3_ctx.__aexit__(None, None, None)
            self._s3_client = None
            self._s3_ctx = None

    def load_initial(self, index_type: str, local_path: str) -> None:
        """Load a retriever from a local disk path at startup.

        This is synchronous because it runs during lifespan startup
        before the event loop is serving requests.

        Args:
            index_type: Key for this retriever, e.g. ``"master"``.
            local_path: Base path (no extension) for the ``.faiss`` + ``.meta.json`` files.
        """
        retriever = FAISSRetriever.load(local_path)
        self._retrievers[index_type] = retriever
        count = self._vector_count(retriever)
        log.info(
            "Initial index loaded",
            extra={
                "index_type": index_type,
                "vector_count": count,
                "local_path": local_path,
                "operation": "load_initial",
            },
        )

    def get_retriever(self, index_type: str = "master") -> FAISSRetriever:
        """Return the current retriever for the given index type.

        Raises:
            IndexNotLoadedError: If no retriever has been loaded for this type.
        """
        retriever = self._retrievers.get(index_type)
        if retriever is None:
            raise IndexNotLoadedError(
                f"No retriever loaded for index type '{index_type}'"
            )
        return retriever

    async def swap(self, manifest: "IndexManifest") -> SwapResult:
        """Download a new index from S3, validate it, and swap it in.

        The download and load happen outside the lock to avoid blocking
        concurrent readers.  Only the final pointer assignment is locked.

        Args:
            manifest: Describes where to find the new index files on S3.

        Returns:
            A ``SwapResult`` indicating success or failure.
        """
        t0 = time.perf_counter()
        index_type = manifest.index_type

        old_retriever = self._retrievers.get(index_type)
        old_count = self._vector_count(old_retriever) if old_retriever else None

        try:
            local_base = await self._download_from_s3(manifest)
        except Exception as exc:
            duration = (time.perf_counter() - t0) * 1000.0
            log.error(
                "Index download failed",
                extra={
                    "index_type": index_type,
                    "error": str(exc),
                    "operation": "swap",
                },
            )
            return SwapResult(
                success=False,
                index_type=index_type,
                old_vector_count=old_count,
                new_vector_count=None,
                duration_ms=duration,
                reason=f"S3 download failed: {exc}",
            )

        try:
            new_retriever = FAISSRetriever.load(local_base)
        except Exception as exc:
            duration = (time.perf_counter() - t0) * 1000.0
            log.error(
                "Index load from disk failed",
                extra={
                    "index_type": index_type,
                    "error": str(exc),
                    "operation": "swap",
                },
            )
            return SwapResult(
                success=False,
                index_type=index_type,
                old_vector_count=old_count,
                new_vector_count=None,
                duration_ms=duration,
                reason=f"FAISS load failed: {exc}",
            )

        new_count = self._vector_count(new_retriever)

        try:
            results = new_retriever.retrieve(VALIDATION_QUERY, top_k=1)
            if not results:
                raise ValueError("Validation query returned no results")
        except Exception as exc:
            duration = (time.perf_counter() - t0) * 1000.0
            log.error(
                "Index validation failed — swap aborted",
                extra={
                    "index_type": index_type,
                    "new_vector_count": new_count,
                    "error": str(exc),
                    "operation": "swap",
                },
            )
            return SwapResult(
                success=False,
                index_type=index_type,
                old_vector_count=old_count,
                new_vector_count=new_count,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                reason=f"Validation failed: {exc}",
            )

        async with self._lock:
            self._retrievers[index_type] = new_retriever

        self._swap_count += 1
        self._last_swap_at[index_type] = datetime.now(UTC)
        duration = (time.perf_counter() - t0) * 1000.0

        log.info(
            "Index hot-swapped",
            extra={
                "index_type": index_type,
                "old_vector_count": old_count,
                "new_vector_count": new_count,
                "swap_count": self._swap_count,
                "duration_ms": round(duration, 2),
                "pipeline_run_id": manifest.pipeline_run_id,
                "operation": "swap",
            },
        )

        return SwapResult(
            success=True,
            index_type=index_type,
            old_vector_count=old_count,
            new_vector_count=new_count,
            duration_ms=duration,
        )

    def status(self) -> dict[str, Any]:
        """Return current state of all loaded retrievers."""
        indexes: dict[str, Any] = {}
        for itype, retriever in self._retrievers.items():
            indexes[itype] = {
                "loaded": True,
                "vector_count": self._vector_count(retriever),
                "last_swap_at": (
                    self._last_swap_at[itype].isoformat()
                    if itype in self._last_swap_at
                    else None
                ),
            }
        return {
            "indexes": indexes,
            "total_swap_count": self._swap_count,
        }

    async def _download_from_s3(self, manifest: "IndexManifest") -> str:
        """Download ``.faiss`` and ``.meta.json`` from S3 to local cache.

        Returns:
            The local base path (without extension) suitable for
            ``FAISSRetriever.load()``.
        """
        os.makedirs(INDEX_LOCAL_CACHE_DIR, exist_ok=True)
        local_base = os.path.join(
            INDEX_LOCAL_CACHE_DIR, f"{manifest.index_type}_{manifest.pipeline_run_id}"
        )

        client = await self._get_s3_client()

        faiss_path = f"{local_base}.faiss"
        resp = await client.get_object(
            Bucket=INDEX_S3_BUCKET, Key=manifest.s3_faiss_key
        )
        body = await resp["Body"].read()
        with open(faiss_path, "wb") as f:
            f.write(body)

        meta_path = f"{local_base}.meta.json"
        resp = await client.get_object(
            Bucket=INDEX_S3_BUCKET, Key=manifest.s3_meta_key
        )
        body = await resp["Body"].read()
        with open(meta_path, "wb") as f:
            f.write(body)

        log.info(
            "Downloaded index files from S3",
            extra={
                "index_type": manifest.index_type,
                "faiss_key": manifest.s3_faiss_key,
                "meta_key": manifest.s3_meta_key,
                "local_base": local_base,
                "operation": "_download_from_s3",
            },
        )
        return local_base

    @staticmethod
    def _vector_count(retriever: FAISSRetriever) -> int:
        """Return the number of vectors in a retriever's index."""
        if retriever.indexer.index is None:
            return 0
        return retriever.indexer.index.ntotal


# Forward-import guard: IndexManifest is defined in index_watcher to avoid
# circular imports.  The type annotation above uses a string literal.
if __name__ == "__main__":
    pass

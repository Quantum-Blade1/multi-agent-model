# INDEX TYPE: IndexFlatIP (Inner Product / Cosine Similarity)
# This matches ai/rag/indexer.py which must ALSO be updated to use IndexFlatIP.
# With L2-normalized vectors, IndexFlatIP == cosine similarity.
# Do NOT use IndexFlatL2 anywhere in this pipeline.

import asyncio
import logging
import os
import time
from typing import List, Tuple

import numpy as np
from sklearn.preprocessing import normalize
from sentence_transformers import SentenceTransformer
import torch

from ingestion.config import settings

logger = logging.getLogger(__name__)


class PipelineEmbedder:
    """Embedder that wraps BGE model for chunk embedding generation."""

    def __init__(self) -> None:
        """Initialise the model once and log initialization performance."""
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        start_ts = time.time()
        self.model = SentenceTransformer(settings.BGE_MODEL_NAME, device=self.device)
        duration = time.time() - start_ts
        logger.info(
            "embedder_init | model=%s | device=%s | load_time_sec=%.3f",
            settings.BGE_MODEL_NAME,
            self.device,
            duration,
        )

    async def generate_embeddings(self, texts: List[str]) -> np.ndarray:
        """Convert text list into L2-normalized embeddings using batching."""
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)

        batch_size = int(os.getenv("EMBED_BATCH_SIZE", "32"))
        total = len(texts)
        embeddings = []

        for idx in range(0, total, batch_size):
            batch = texts[idx : idx + batch_size]
            batch_start = time.time()
            batch_emb = await asyncio.to_thread(
                self.model.encode,
                batch,
                convert_to_numpy=True,
                normalize_embeddings=False,
                show_progress_bar=False,
            )
            batch_end = time.time()

            if batch_emb.ndim != 2 or batch_emb.shape[1] != 384:
                raise ValueError(
                    f"Unexpected embedding shape {batch_emb.shape}; expected (n,384)"
                )

            embeddings.append(batch_emb)
            current_batch_num = idx // batch_size + 1
            if current_batch_num % 10 == 0 or idx + batch_size >= total:
                logger.info(
                    "embedder_batch | batch=%d | total_batches=%d | batch_size=%d | elapsed=%.2fs",
                    current_batch_num,
                    (total + batch_size - 1) // batch_size,
                    len(batch),
                    batch_end - batch_start,
                )

        result = np.vstack(embeddings).astype(np.float32)
        if result.shape[0] != total:
            raise ValueError("Embedding count mismatch with input texts")

        result = normalize(result, norm="l2", axis=1, copy=False).astype(np.float32)
        return result

    async def embed_chunks(self, chunks: List[dict]) -> Tuple[np.ndarray, List[dict]]:
        """Embed chunk list, filtering out empty or whitespace-only texts."""
        if not isinstance(chunks, list):
            raise ValueError("chunks must be a list of dicts")

        filtered = []
        texts = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            text = str(chunk.get("text", ""))
            if not text.strip():
                continue
            filtered.append(chunk)
            texts.append(text)

        embeddings = await self.generate_embeddings(texts)
        return embeddings, filtered

"""
Indexer module for the RAG pipeline.

Manages FAISS index construction, persistence, and metadata storage
for NBFC regulatory documents and compliance data.
"""

import json
import os

import faiss
import numpy as np


class FAISSIndexer:
    """Builds, saves, and loads a FAISS Flat-L2 index with associated metadata."""

    def __init__(self) -> None:
        """Initialise an empty indexer."""
        self.index: faiss.IndexFlatL2 | None = None
        self.metadata: list[dict] = []

    def build_index(self, embeddings: np.ndarray, metadata: list[dict]) -> None:
        """
        Build a flat L2 index from the given embeddings.

        Args:
            embeddings: 2-D float32 array of shape (n, dim).
            metadata: List of dicts (one per embedding) storing source info
                      such as document ID, chunk number, and S3 URL.

        Raises:
            ValueError: If embeddings are empty or metadata length mismatches.
        """
        if embeddings.size == 0:
            raise ValueError("Cannot build an index from empty embeddings.")
        if len(metadata) != embeddings.shape[0]:
            raise ValueError(
                f"Metadata length ({len(metadata)}) must match the number of "
                f"embeddings ({embeddings.shape[0]})."
            )

        embeddings = embeddings.astype(np.float32)
        dim = embeddings.shape[1]

        # Use IndexFlatIP for inner product similarity (works as cosine with normalized vectors).
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(embeddings)
        self.metadata = metadata

    def save(self, path: str) -> None:
        """
        Persist index and metadata to disk.

        Creates two files:
            - ``<path>.faiss``  — the FAISS index binary
            - ``<path>.meta.json`` — the metadata JSON

        Args:
            path: Base file path (without extension).

        Raises:
            RuntimeError: If no index has been built yet.
        """
        if self.index is None:
            raise RuntimeError("No index to save. Call build_index() first.")

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        faiss.write_index(self.index, f"{path}.faiss")
        with open(f"{path}.meta.json", "w", encoding="utf-8") as fh:
            json.dump(self.metadata, fh, ensure_ascii=False, indent=2)

    def load(self, path: str) -> None:
        """
        Load a previously saved index and its metadata from disk.

        Args:
            path: Base file path (without extension) used during save().

        Raises:
            FileNotFoundError: If either the index or metadata file is missing.
        """
        index_path = f"{path}.faiss"
        meta_path = f"{path}.meta.json"

        if not os.path.exists(index_path):
            raise FileNotFoundError(f"FAISS index file not found: {index_path}")
        if not os.path.exists(meta_path):
            raise FileNotFoundError(f"Metadata file not found: {meta_path}")

        self.index = faiss.read_index(index_path)
        with open(meta_path, "r", encoding="utf-8") as fh:
            self.metadata = json.load(fh)

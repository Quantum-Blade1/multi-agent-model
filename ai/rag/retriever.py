"""
Retriever module for the RAG pipeline.

Handles similarity search and document retrieval from the FAISS vector store
for compliance-related queries.
"""

import numpy as np

from ai.rag.embedder import BGEEmbedder
from ai.rag.indexer import FAISSIndexer


class InsufficientRegulationError(Exception):
    """Raised when FAISS retrieval returns no relevant regulatory context."""


class FAISSRetriever:
    """Retrieves the most relevant compliance chunks from a FAISS index."""

    @classmethod
    def load(cls, path: str) -> "FAISSRetriever":
        """
        Load a persisted index from disk and return a retriever.

        Args:
            path: Base path (no extension) matching ``FAISSIndexer.save`` / ``load``.
        """
        indexer = FAISSIndexer()
        indexer.load(path)
        embedder = BGEEmbedder()
        return cls(indexer=indexer, embedder=embedder)

    def __init__(self, indexer: FAISSIndexer, embedder: BGEEmbedder) -> None:
        """
        Initialise the retriever.

        Args:
            indexer: A FAISSIndexer instance with a loaded or built index.
            embedder: A BGEEmbedder instance for encoding queries.
        """
        self.indexer = indexer
        self.embedder = embedder

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Embed a query and return the top-k most relevant metadata chunks.

        Args:
            query: Natural-language compliance query.
            top_k: Number of results to return.

        Returns:
            List of dicts, each containing the original metadata fields
            plus a ``score`` key (L2 distance — lower is better).

        Raises:
            InsufficientRegulationError: If the index is missing, the search
                fails, or no results are found.
        """
        if self.indexer.index is None:
            raise InsufficientRegulationError(
                "FAISS index is not loaded. Load or build an index first."
            )

        try:
            query_embedding = self.embedder.embed([query])
            query_vector = query_embedding.astype(np.float32)

            distances, indices = self.indexer.index.search(query_vector, top_k)
        except Exception as exc:
            raise InsufficientRegulationError(
                f"FAISS search failed: {exc}"
            ) from exc

        results: list[dict] = []
        for distance, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            entry = {**self.indexer.metadata[idx], "score": float(distance)}
            results.append(entry)

        if not results:
            raise InsufficientRegulationError(
                "No relevant regulatory context found for the given query."
            )

        return results

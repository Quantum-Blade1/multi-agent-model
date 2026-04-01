"""
Query Handler module for the RAG pipeline.

Processes incoming compliance queries by loading the appropriate FAISS index,
running retrieval, and returning formatted regulatory chunks.
"""

import os

from ingestion.config import settings

from ai.rag.embedder import BGEEmbedder
from ai.rag.indexer import FAISSIndexer
from ai.rag.retriever import FAISSRetriever

INDEX_MASTER_PATH = os.getenv(
    "INDEX_MASTER_PATH",
    os.path.join(settings.INDEX_DIR, settings.MASTER_INDEX_NAME),
)
INDEX_UPDATED_PATH = os.getenv(
    "INDEX_UPDATED_PATH",
    os.path.join(settings.INDEX_DIR, settings.UPDATED_INDEX_NAME),
)

_INDEX_PATHS = {
    "master": INDEX_MASTER_PATH,
    "updated": INDEX_UPDATED_PATH,
}


class QueryHandler:
    """Orchestrates index loading, retrieval, and result formatting."""

    def __init__(self, embedder: BGEEmbedder | None = None) -> None:
        """
        Initialise the handler.

        Args:
            embedder: Optional pre-initialised BGEEmbedder.
                      A new instance is created if not provided.
        """
        self.embedder = embedder or BGEEmbedder()

    def handle(
        self,
        query: str,
        index_type: str = "updated",
        top_k: int = 5,
    ) -> list[dict]:
        """
        Load the requested FAISS index, run retrieval, and return formatted chunks.

        Args:
            query: Natural-language compliance query.
            index_type: Which index to search — ``"master"`` or ``"updated"``.
            top_k: Number of chunks to return.

        Returns:
            List of formatted result dicts with keys:
                - ``clause_id``  — regulatory clause identifier
                - ``text``       — chunk text
                - ``source``     — document source / S3 URL
                - ``score``      — L2 distance (lower is better)

        Raises:
            ValueError: If an unsupported index_type is requested.
            FileNotFoundError: If the index files are missing on disk.
        """
        if index_type not in _INDEX_PATHS:
            raise ValueError(
                f"Unknown index_type '{index_type}'. Choose from: {list(_INDEX_PATHS)}"
            )

        index_path = _INDEX_PATHS[index_type]

        indexer = FAISSIndexer()
        indexer.load(index_path)

        retriever = FAISSRetriever(indexer=indexer, embedder=self.embedder)
        raw_results = retriever.retrieve(query=query, top_k=top_k)

        return [
            {
                "clause_id": chunk.get("clause_id", ""),
                "text": chunk.get("text", ""),
                "source": chunk.get("source", ""),
                "score": chunk.get("score", 0.0),
            }
            for chunk in raw_results
        ]

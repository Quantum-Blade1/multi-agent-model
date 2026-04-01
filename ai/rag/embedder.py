"""
Embedder module for the RAG pipeline.

Handles text embedding generation for documents and queries
using the BGE embedding model via sentence-transformers.
"""

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-small-en-v1.5"


class BGEEmbedder:
    """Generates normalized embeddings using the BGE-small model."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        """
        Initialise the embedder.

        Args:
            model_name: HuggingFace model identifier for the embedding model.
        """
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        Generate L2-normalised embeddings for a list of texts.

        Args:
            texts: List of input strings to embed.

        Returns:
            np.ndarray of shape (len(texts), embedding_dim) with unit-norm rows.

        Raises:
            ValueError: If the input list is empty.
        """
        if not texts:
            raise ValueError("Cannot embed an empty list of texts.")

        embeddings: np.ndarray = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings

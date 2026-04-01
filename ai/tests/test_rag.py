"""
Tests for the RAG pipeline modules: BGEEmbedder, FAISSIndexer, and QueryHandler.
"""

import os
import tempfile

import numpy as np
import pytest

from ai.rag.embedder import BGEEmbedder
from ai.rag.indexer import FAISSIndexer
from ai.rag.retriever import InsufficientRegulationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def embedder():
    """Shared BGEEmbedder instance (model loaded once per test module)."""
    return BGEEmbedder()


@pytest.fixture()
def sample_texts():
    return [
        "The NBFC must maintain a minimum capital adequacy ratio.",
        "All KYC documents must be verified within 30 days.",
        "Suspicious transactions above 10 lakh must be reported to FIU.",
    ]


@pytest.fixture()
def indexer_with_data(embedder, sample_texts):
    """FAISSIndexer built with sample embeddings and metadata."""
    embeddings = embedder.embed(sample_texts)
    metadata = [
        {"clause_id": f"CL-{i}", "text": t, "source": f"s3://docs/doc{i}.pdf"}
        for i, t in enumerate(sample_texts)
    ]
    indexer = FAISSIndexer()
    indexer.build_index(embeddings, metadata)
    return indexer


# ---------------------------------------------------------------------------
# BGEEmbedder
# ---------------------------------------------------------------------------

class TestBGEEmbedder:
    """Tests for the BGEEmbedder class."""

    def test_embed_returns_correct_shape(self, embedder, sample_texts):
        """Embedding 3 texts should return a (3, dim) ndarray."""
        result = embedder.embed(sample_texts)
        assert isinstance(result, np.ndarray)
        assert result.shape[0] == 3
        assert result.ndim == 2

    def test_embed_returns_normalized_vectors(self, embedder, sample_texts):
        """Each row should have unit L2 norm."""
        result = embedder.embed(sample_texts)
        norms = np.linalg.norm(result, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-5)

    def test_embed_empty_raises(self, embedder):
        """Passing an empty list must raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            embedder.embed([])


# ---------------------------------------------------------------------------
# FAISSIndexer
# ---------------------------------------------------------------------------

class TestFAISSIndexer:
    """Tests for the FAISSIndexer class."""

    def test_build_index(self, indexer_with_data):
        """Index should be populated after build_index."""
        assert indexer_with_data.index is not None
        assert indexer_with_data.index.ntotal == 3

    def test_build_index_empty_raises(self):
        indexer = FAISSIndexer()
        with pytest.raises(ValueError, match="empty"):
            indexer.build_index(np.array([]), [])

    def test_build_index_metadata_mismatch_raises(self, embedder, sample_texts):
        embeddings = embedder.embed(sample_texts)
        indexer = FAISSIndexer()
        with pytest.raises(ValueError, match="Metadata length"):
            indexer.build_index(embeddings, [{"id": 1}])

    def test_save_and_load(self, indexer_with_data):
        """Save then load should produce an identical index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_index")
            indexer_with_data.save(path)

            assert os.path.exists(f"{path}.faiss")
            assert os.path.exists(f"{path}.meta.json")

            new_indexer = FAISSIndexer()
            new_indexer.load(path)

            assert new_indexer.index.ntotal == indexer_with_data.index.ntotal
            assert len(new_indexer.metadata) == len(indexer_with_data.metadata)

    def test_save_without_index_raises(self):
        indexer = FAISSIndexer()
        with pytest.raises(RuntimeError, match="No index"):
            indexer.save("/tmp/noindex")

    def test_load_missing_files_raises(self):
        indexer = FAISSIndexer()
        with pytest.raises(FileNotFoundError):
            indexer.load("/tmp/nonexistent_index_path")


# ---------------------------------------------------------------------------
# QueryHandler — error path
# ---------------------------------------------------------------------------

class TestQueryHandlerErrors:
    """QueryHandler should raise InsufficientRegulationError on bad retrieval."""

    def test_missing_index_raises(self):
        """Loading a non-existent index should bubble up as FileNotFoundError."""
        from ai.rag.query_handler import QueryHandler

        handler = QueryHandler(embedder=BGEEmbedder())
        with pytest.raises(FileNotFoundError):
            handler.handle("some query", index_type="master")

    def test_invalid_index_type_raises(self):
        from ai.rag.query_handler import QueryHandler

        handler = QueryHandler(embedder=BGEEmbedder())
        with pytest.raises(ValueError, match="Unknown index_type"):
            handler.handle("some query", index_type="nonexistent")

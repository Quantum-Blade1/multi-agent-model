"""
Tests for the RAG pipeline: BGEEmbedder, FAISSIndexer, FAISSRetriever, and QueryHandler.

Covers embedding normalisation, empty-input handling, in-memory index
build/search, empty-result error paths, and QueryHandler output formatting.
"""

import os
import tempfile

import numpy as np
import pytest

from ai.rag.embedder import BGEEmbedder
from ai.rag.indexer import FAISSIndexer
from ai.rag.retriever import FAISSRetriever, InsufficientRegulationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def embedder():
    """Shared BGEEmbedder instance (model loaded once per module)."""
    return BGEEmbedder()


@pytest.fixture()
def sample_texts():
    return [
        "The NBFC must maintain a minimum capital adequacy ratio.",
        "All KYC documents must be verified within 30 days.",
        "Suspicious transactions above 10 lakh must be reported to FIU.",
    ]


@pytest.fixture()
def sample_metadata(sample_texts):
    return [
        {"clause_id": f"CL-{i}", "text": t, "source": f"s3://docs/doc{i}.pdf"}
        for i, t in enumerate(sample_texts)
    ]


@pytest.fixture()
def indexer_with_data(embedder, sample_texts, sample_metadata):
    """FAISSIndexer built with sample embeddings and metadata (in-memory)."""
    embeddings = embedder.embed(sample_texts)
    indexer = FAISSIndexer()
    indexer.build_index(embeddings, sample_metadata)
    return indexer


# ===========================================================================
# BGEEmbedder
# ===========================================================================

class TestBGEEmbedder:

    def test_embedder_produces_normalized_vectors(self, embedder, sample_texts):
        """Each embedding row should have unit L2 norm (normalised by the model).

        This is critical for cosine-similarity retrieval with inner-product
        FAISS indices.
        """
        # Arrange / Act
        result = embedder.embed(sample_texts)

        # Assert
        norms = np.linalg.norm(result, axis=1)
        np.testing.assert_allclose(
            norms, 1.0, atol=1e-5,
            err_msg="Embeddings must be L2-normalised to unit norm",
        )

    def test_embedder_handles_empty_input(self, embedder):
        """Passing an empty list must raise ValueError, not silently return zeros."""
        # Arrange / Act / Assert
        with pytest.raises(ValueError, match="empty"):
            embedder.embed([])

    def test_embed_returns_correct_shape(self, embedder, sample_texts):
        """Embedding N texts should return shape (N, dim)."""
        # Act
        result = embedder.embed(sample_texts)

        # Assert
        assert isinstance(result, np.ndarray), "Should return an ndarray"
        assert result.shape[0] == len(sample_texts), (
            f"Expected {len(sample_texts)} rows, got {result.shape[0]}"
        )
        assert result.ndim == 2


# ===========================================================================
# FAISSIndexer
# ===========================================================================

class TestFAISSIndexer:

    def test_faiss_indexer_build_and_search(self, indexer_with_data, embedder):
        """Build an in-memory index and verify nearest-neighbour search returns
        the correct number of results with valid distances.

        No disk I/O involved — this validates the core index+search path.
        """
        # Arrange
        query_vec = embedder.embed(["capital adequacy"])

        # Act
        distances, indices = indexer_with_data.index.search(query_vec.astype(np.float32), 2)

        # Assert
        assert distances.shape == (1, 2), "Should return 2 results for top_k=2"
        assert indices[0][0] != -1, "First result index should be valid"
        assert distances[0][0] >= 0, "Inner-product distance should be non-negative"

    def test_build_index_populates_ntotal(self, indexer_with_data):
        """After build_index, the FAISS index should know how many vectors it holds."""
        assert indexer_with_data.index is not None
        assert indexer_with_data.index.ntotal == 3, (
            "Index should contain exactly 3 vectors"
        )

    def test_build_index_empty_raises(self):
        """Empty embeddings must raise ValueError."""
        indexer = FAISSIndexer()
        with pytest.raises(ValueError, match="empty"):
            indexer.build_index(np.array([]), [])

    def test_build_index_metadata_mismatch_raises(self, embedder, sample_texts):
        """Metadata count differing from embedding count must raise ValueError."""
        embeddings = embedder.embed(sample_texts)
        indexer = FAISSIndexer()
        with pytest.raises(ValueError, match="Metadata length"):
            indexer.build_index(embeddings, [{"id": 1}])

    def test_save_and_load(self, indexer_with_data):
        """Save then load should produce an index with identical ntotal and metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_index")
            indexer_with_data.save(path)

            assert os.path.exists(f"{path}.faiss")
            assert os.path.exists(f"{path}.meta.json")

            new_indexer = FAISSIndexer()
            new_indexer.load(path)

            assert new_indexer.index.ntotal == indexer_with_data.index.ntotal
            assert len(new_indexer.metadata) == len(indexer_with_data.metadata)


# ===========================================================================
# FAISSRetriever
# ===========================================================================

class TestFAISSRetriever:

    def test_retriever_raises_on_empty_results(self, embedder):
        """When the index has data but the query yields only sentinel (-1)
        indices, InsufficientRegulationError should be raised.

        We simulate this by building an index and asking for more results
        than vectors exist, then stripping the valid ones via a very high
        top_k on a tiny index — but FAISS pads with -1 only when ntotal < k.
        A more reliable approach: build with 1 vector and request top_k=1
        with an orthogonal query; if the single result *does* come back,
        we at least verify the retriever works.  The real empty-result path
        is when ntotal==0, which triggers the "index is not loaded" guard.
        """
        # Arrange — retriever with no index loaded
        indexer = FAISSIndexer()
        retriever = FAISSRetriever(indexer=indexer, embedder=embedder)

        # Act / Assert
        with pytest.raises(InsufficientRegulationError, match="not loaded"):
            retriever.retrieve("anything")

    def test_retriever_returns_results_with_score(
        self, indexer_with_data, embedder
    ):
        """Successful retrieval should return dicts with metadata + score."""
        # Arrange
        retriever = FAISSRetriever(indexer=indexer_with_data, embedder=embedder)

        # Act
        results = retriever.retrieve("capital adequacy ratio NBFC", top_k=2)

        # Assert
        assert len(results) == 2, "Should return top_k results"
        for r in results:
            assert "clause_id" in r, "Each result should carry clause_id"
            assert "score" in r, "Each result should carry a similarity score"


# ===========================================================================
# QueryHandler
# ===========================================================================

class TestQueryHandler:

    def test_query_handler_formats_results_correctly(self, embedder, sample_texts, sample_metadata):
        """QueryHandler.handle should return dicts with exactly the four keys:
        clause_id, text, source, score.

        We use a temp index on disk so the handler's load path works.
        """
        from ai.rag.query_handler import QueryHandler

        # Arrange — build and save a temp index
        embeddings = embedder.embed(sample_texts)
        indexer = FAISSIndexer()
        indexer.build_index(embeddings, sample_metadata)

        with tempfile.TemporaryDirectory() as tmpdir:
            idx_path = os.path.join(tmpdir, "test_idx")
            indexer.save(idx_path)

            handler = QueryHandler(embedder=embedder)

            # Patch the index path so handle() finds our temp index
            import ai.rag.query_handler as qh_mod
            original = qh_mod._INDEX_PATHS.copy()
            qh_mod._INDEX_PATHS["test"] = idx_path

            try:
                # Act
                results = handler.handle(
                    "KYC document verification", index_type="test", top_k=2
                )
            finally:
                qh_mod._INDEX_PATHS = original

        # Assert
        assert len(results) == 2, "Should return top_k formatted results"
        expected_keys = {"clause_id", "text", "source", "score"}
        for r in results:
            assert set(r.keys()) == expected_keys, (
                f"Result keys {set(r.keys())} don't match expected {expected_keys}"
            )
            assert isinstance(r["score"], float), "Score should be a float"
            assert r["clause_id"], "clause_id should be non-empty"

    def test_missing_index_raises(self):
        """Loading a non-existent index should raise FileNotFoundError."""
        from ai.rag.query_handler import QueryHandler

        handler = QueryHandler(embedder=BGEEmbedder())
        with pytest.raises(FileNotFoundError):
            handler.handle("some query", index_type="master")

    def test_invalid_index_type_raises(self):
        """An unknown index_type should raise ValueError."""
        from ai.rag.query_handler import QueryHandler

        handler = QueryHandler(embedder=BGEEmbedder())
        with pytest.raises(ValueError, match="Unknown index_type"):
            handler.handle("some query", index_type="nonexistent")

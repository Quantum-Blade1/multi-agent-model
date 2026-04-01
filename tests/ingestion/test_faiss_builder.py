
import os
import json
import numpy as np
import pytest
import faiss
from ingestion.faiss.builder import FAISSBuilder
from ingestion.config import settings

@pytest.fixture
def faiss_builder():
    return FAISSBuilder()

@pytest.fixture
def mock_data():
    dim = 64
    num_elements = 20
    embeddings = np.random.random((num_elements, dim)).astype('float32')
    metadata = [{"id": i, "text": f"Sample text {i}"} for i in range(num_elements)]
    return embeddings, metadata

def test_build_and_load(faiss_builder, mock_data, tmp_path):
    embeddings, metadata = mock_data
    index_name = "test_build_load"
    
    # Override settings.INDEX_DIR for testing
    original_index_dir = settings.INDEX_DIR
    settings.INDEX_DIR = str(tmp_path)
    
    try:
        # Build
        faiss_builder.build(embeddings, metadata, index_name)
        
        index_path = os.path.join(settings.INDEX_DIR, f"{index_name}.faiss")
        meta_path = os.path.join(settings.INDEX_DIR, f"{index_name}_meta.json")
        
        assert os.path.exists(index_path)
        assert os.path.exists(meta_path)
        
        # Load
        index, loaded_metadata = faiss_builder.load(index_name)
        assert index.ntotal == len(metadata)
        assert len(loaded_metadata) == len(metadata)
        assert loaded_metadata[0]["id"] == metadata[0]["id"]
        
    finally:
        settings.INDEX_DIR = original_index_dir

def test_search(faiss_builder, mock_data, tmp_path):
    embeddings, metadata = mock_data
    index_name = "test_search"
    
    original_index_dir = settings.INDEX_DIR
    settings.INDEX_DIR = str(tmp_path)
    
    try:
        faiss_builder.build(embeddings, metadata, index_name)
        index, loaded_metadata = faiss_builder.load(index_name)
        
        # Search for the first element
        query_embedding = embeddings[0]
        top_k = 5
        results = faiss_builder.search(index, loaded_metadata, query_embedding, top_k=top_k)
        
        assert len(results) == top_k
        assert "similarity_score" in results[0]
        # Should match itself best
        assert results[0]["id"] == metadata[0]["id"]
        assert results[0]["similarity_score"] > 0.99
        
    finally:
        settings.INDEX_DIR = original_index_dir

def test_build_two_indexes(faiss_builder, tmp_path):
    dim = 64
    all_chunks = [
        {"id": i, "embedding": np.random.random(dim).tolist(), "text": f"All {i}"}
        for i in range(10)
    ]
    master_chunks = [
        {"id": i, "embedding": np.random.random(dim).tolist(), "text": f"Master {i}"}
        for i in range(4)
    ]
    
    original_index_dir = settings.INDEX_DIR
    settings.INDEX_DIR = str(tmp_path)
    
    try:
        faiss_builder.build_two_indexes(all_chunks, master_chunks)
        
        assert os.path.exists(os.path.join(settings.INDEX_DIR, f"{settings.MASTER_INDEX_NAME}.faiss"))
        assert os.path.exists(os.path.join(settings.INDEX_DIR, f"{settings.UPDATED_INDEX_NAME}.faiss"))
        
        # Verify sizes
        master_index, master_meta = faiss_builder.load(settings.MASTER_INDEX_NAME)
        updated_index, updated_meta = faiss_builder.load(settings.UPDATED_INDEX_NAME)
        
        assert master_index.ntotal == 4
        assert updated_index.ntotal == 10
        
        # Check that embedding is not in metadata
        assert "embedding" not in master_meta[0]
        assert "embedding" not in updated_meta[0]
        
    finally:
        settings.INDEX_DIR = original_index_dir

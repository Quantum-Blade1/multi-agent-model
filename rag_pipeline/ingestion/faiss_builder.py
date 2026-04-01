"""
Module for building and managing the FAISS vector index.
"""
import os
import json
import logging
import faiss
import numpy as np
from rag_pipeline.config import settings

logger = logging.getLogger(__name__)

class FAISSBuilder:
    """
    Handles the creation, persistence, and searching of FAISS indices.
    """

    def build(self, embeddings: np.ndarray, metadata: list[dict], index_name: str) -> None:
        """
        Builds a FAISS IndexFlatIP (inner product, works with normalized vectors).
        Saves index to INDEX_DIR/{index_name}.faiss
        Saves metadata to INDEX_DIR/{index_name}_meta.json
        """
        if not os.path.exists(settings.INDEX_DIR):
            os.makedirs(settings.INDEX_DIR, exist_ok=True)

        # Ensure embeddings are float32 for FAISS
        embeddings = embeddings.astype("float32")
        
        dimension = embeddings.shape[1]
        index = faiss.IndexFlatIP(dimension)

        # FAISS IndexFlatIP works as cosine similarity if vectors are normalized
        faiss.normalize_L2(embeddings)
        index.add(embeddings)

        index_path = os.path.join(settings.INDEX_DIR, f"{index_name}.faiss")
        meta_path = os.path.join(settings.INDEX_DIR, f"{index_name}_meta.json")

        faiss.write_index(index, index_path)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=4)

        logger.info(f"Successfully built and saved index '{index_name}' with {len(metadata)} items.")

    def build_two_indexes(self, all_chunks: list[dict], master_chunks: list[dict]) -> None:
        """
        Calls build() twice:
          1. master_index — only master circular chunks
          2. updated_index — all chunks (master + regular circulars)
        Logs index sizes
        """
        # Master index
        if master_chunks:
            master_embeddings = np.array([c["embedding"] for c in master_chunks]).astype("float32")
            # Metadata should probably NOT include the embedding itself to save space/memory in JSON
            master_metadata = [{k: v for k, v in c.items() if k != "embedding"} for c in master_chunks]
            self.build(master_embeddings, master_metadata, settings.MASTER_INDEX_NAME)
            logger.info(f"Master index size: {len(master_chunks)}")
        else:
            logger.warning("No master chunks provided to build master_index.")

        # Updated index (all chunks)
        if all_chunks:
            all_embeddings = np.array([c["embedding"] for c in all_chunks]).astype("float32")
            all_metadata = [{k: v for k, v in c.items() if k != "embedding"} for c in all_chunks]
            self.build(all_embeddings, all_metadata, settings.UPDATED_INDEX_NAME)
            logger.info(f"Updated index size: {len(all_chunks)}")
        else:
            logger.warning("No chunks provided to build updated_index.")

    def load(self, index_name: str) -> tuple[faiss.Index, list[dict]]:
        """
        Loads index + metadata from disk.
        Returns both.
        """
        index_path = os.path.join(settings.INDEX_DIR, f"{index_name}.faiss")
        meta_path = os.path.join(settings.INDEX_DIR, f"{index_name}_meta.json")

        if not os.path.exists(index_path) or not os.path.exists(meta_path):
            raise FileNotFoundError(f"Index files for '{index_name}' not found in {settings.INDEX_DIR}")

        index = faiss.read_index(index_path)
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        return index, metadata

    def search(self, index: faiss.Index, metadata: list[dict], query_embedding: np.ndarray, top_k: int = 5) -> list[dict]:
        """
        Runs FAISS search.
        Returns top_k metadata dicts with appended similarity score.
        """
        # Ensure query_embedding is 2D and float32
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)
        query_embedding = query_embedding.astype("float32")

        # Normalize query vector for inner product (cosine similarity)
        faiss.normalize_L2(query_embedding)
        
        # Search index
        distances, indices = index.search(query_embedding, top_k)

        results = []
        for score, idx in zip(distances[0], indices[0]):
            if idx != -1:  # FAISS returns -1 if not enough neighbors are found
                meta = metadata[idx].copy()
                meta["similarity_score"] = float(score)
                results.append(meta)

        return results

"""
Main entry point to run the RAG data ingestion pipeline.
"""

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

import numpy as np

from ingestion.chunker.chunker import RegulatoryChunker
from ingestion.config import settings
from ingestion.faiss.embedder import PipelineEmbedder
from ingestion.faiss.builder import FAISSBuilder
from ingestion.scraper.cleaner import TextCleaner
from ingestion.scraper.pdf_extractor import PDFExtractor
from ingestion.scraper.rbi_scraper import scrape_rbi

logger = logging.getLogger(__name__)


class PipelineStageError(Exception):
    """Raised when a pipeline stage fails."""


def _stage_log(stage: str, level: str, message: str, **extras):
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "index_type": extras.get("index_type", "master"),
        **extras,
    }
    if level == "info":
        logger.info("%s | %s | %s", stage, message, json.dumps(data))
    elif level == "warning":
        logger.warning("%s | %s | %s", stage, message, json.dumps(data))
    elif level == "error":
        logger.error("%s | %s | %s", stage, message, json.dumps(data))
    elif level == "debug":
        logger.debug("%s | %s | %s", stage, message, json.dumps(data))


def _write_manifest(stage: str, duration: float, input_count: int, output_count: int, index_type: str):
    manifest = {
        "stage": stage,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 3),
        "input_count": input_count,
        "output_count": output_count,
        "index_type": index_type,
    }
    manifest_path = os.path.join("ingestion", "data", "pipeline_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


async def scrape_stage(force: bool, index_type: str):
    stage = "scrape"
    output_path = os.path.join(settings.RAW_DATA_DIR, "circular_links.json")
    if os.path.exists(output_path) and not force:
        _stage_log(stage, "info", "Skipping scrape stage; output exists.", index_type=index_type)
        with open(output_path, "r", encoding="utf-8") as f:
            links = json.load(f)
        _write_manifest(stage, 0.0, len(links), len(links), index_type)
        return links

    start = time.time()
    try:
        links = scrape_rbi()
        os.makedirs(settings.RAW_DATA_DIR, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(links, f, ensure_ascii=False, indent=2)
        duration = time.time() - start
        _stage_log(stage, "info", "Scrape completed", index_type=index_type, duration_ms=round(duration*1000,2))
        _write_manifest(stage, duration, len(links), len(links), index_type)
        return links
    except Exception as exc:
        _stage_log(stage, "error", "Scrape failed", index_type=index_type, error=str(exc))
        raise PipelineStageError(f"{stage} failed: {exc}")


async def extract_stage(force: bool, index_type: str):
    stage = "extract"
    raw_links_path = os.path.join(settings.RAW_DATA_DIR, "circular_links.json")
    output_path = os.path.join(settings.RAW_DATA_DIR, "processed_circulars.json")

    if os.path.exists(output_path) and not force:
        _stage_log(stage, "info", "Skipping extract stage; output exists.", index_type=index_type)
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        with open(raw_links_path, "r", encoding="utf-8") as f:
            links = json.load(f)
    except FileNotFoundError as exc:
        raise PipelineStageError(f"{stage} failed: source raw links not found: {exc}")

    extractor = PDFExtractor()
    start = time.time()
    results = extractor.process_all(links)
    os.makedirs(settings.RAW_DATA_DIR, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    duration = time.time() - start
    _stage_log(stage, "info", "Extract completed", index_type=index_type, duration_ms=round(duration*1000,2))
    _write_manifest(stage, duration, len(links), len(results), index_type)
    return results


async def clean_stage(force: bool, index_type: str):
    stage = "clean"
    processed_path = os.path.join(settings.RAW_DATA_DIR, "processed_circulars.json")
    if not os.path.exists(processed_path):
        raise PipelineStageError(f"{stage} failed: processed circulars file not found")

    cleaner = TextCleaner()
    start = time.time()
    with open(processed_path, "r", encoding="utf-8") as f:
        documents = json.load(f)

    cleaned_docs = cleaner.clean_all(documents)
    duration = time.time() - start
    _stage_log(stage, "info", "Clean completed", index_type=index_type, duration_ms=round(duration*1000,2))
    _write_manifest(stage, duration, len(documents), len(cleaned_docs), index_type)
    return cleaned_docs


async def chunk_stage(force: bool, index_type: str):
    stage = "chunk"
    output_path = os.path.join("ingestion", "data", "chunks.json")
    if os.path.exists(output_path) and not force:
        _stage_log(stage, "info", "Skipping chunk stage; output exists.", index_type=index_type)
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)

    chunker = RegulatoryChunker()
    cleaned_files = glob(os.path.join(settings.CLEANED_DATA_DIR, "*.json"))
    if not cleaned_files:
        raise PipelineStageError(f"{stage} failed: no cleaned JSON files found in {settings.CLEANED_DATA_DIR}")

    docs = []
    for path in cleaned_files:
        with open(path, "r", encoding="utf-8") as f:
            docs.append(json.load(f))

    start = time.time()
    chunks = chunker.chunk_all(docs)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    duration = time.time() - start
    _stage_log(stage, "info", "Chunk completed", index_type=index_type, duration_ms=round(duration*1000,2))
    _write_manifest(stage, duration, len(docs), len(chunks), index_type)
    return chunks


async def embed_stage(force: bool, index_type: str):
    stage = "embed"
    chunks_path = os.path.join("ingestion", "data", "chunks.json")
    embeddings_path = os.path.join("ingestion", "data", "embeddings.npy")
    chunks_out_path = os.path.join("ingestion", "data", "chunks_embedded.json")

    if os.path.exists(embeddings_path) and os.path.exists(chunks_out_path) and not force:
        _stage_log(stage, "info", "Skipping embed stage; output exists.", index_type=index_type)
        return np.load(embeddings_path), json.load(open(chunks_out_path, "r", encoding="utf-8"))

    if not os.path.exists(chunks_path):
        raise PipelineStageError(f"{stage} failed: chunks file not found")

    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    embedder = PipelineEmbedder()
    start = time.time()
    embeddings, embedded_chunks = await embedder.embed_chunks(chunks)

    os.makedirs(os.path.dirname(embeddings_path), exist_ok=True)
    np.save(embeddings_path, embeddings)

    for i, chunk in enumerate(embedded_chunks):
        chunk["embedding"] = embeddings[i].tolist()

    with open(chunks_out_path, "w", encoding="utf-8") as f:
        json.dump(embedded_chunks, f, ensure_ascii=False, indent=2)

    duration = time.time() - start
    _stage_log(stage, "info", "Embed completed", index_type=index_type, duration_ms=round(duration*1000,2))
    _write_manifest(stage, duration, len(chunks), embedded_chunks and len(embedded_chunks) or 0, index_type)
    return embeddings, embedded_chunks


async def build_index_stage(force: bool, index_type: str):
    stage = "index"
    index_path = os.path.join(settings.INDEX_DIR, f"{index_type}.faiss")
    index_meta_path = os.path.join(settings.INDEX_DIR, f"{index_type}.meta.json")

    os.makedirs(settings.INDEX_DIR, exist_ok=True)
    if os.path.exists(index_path) and os.path.exists(index_meta_path) and not force:
        _stage_log(stage, "info", "Skipping index stage; output exists.", index_type=index_type)
        return

    embeddings_path = os.path.join("ingestion", "data", "embeddings.npy")
    chunks_out_path = os.path.join("ingestion", "data", "chunks_embedded.json")

    if not os.path.exists(embeddings_path) or not os.path.exists(chunks_out_path):
        raise PipelineStageError(f"{stage} failed: embeddings or chunk metadata missing")

    import numpy as np

    embeddings = np.load(embeddings_path)
    with open(chunks_out_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    # Prepare metadata for index builder
    metadata = [{k: v for k, v in c.items() if k != "embedding"} for c in chunks]

    faiss_builder = FAISSBuilder()
    start = time.time()
    faiss_builder.build(embeddings, metadata, index_type)
    duration = time.time() - start

    _stage_log(stage, "info", "Index build completed", index_type=index_type, duration_ms=round(duration*1000,2), index_size=len(metadata))
    _write_manifest(stage, duration, len(chunks), len(metadata), index_type)


async def main():
    parser = argparse.ArgumentParser(description="RAG ingestion pipeline")
    parser.add_argument("--scrape", action="store_true")
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--chunk", action="store_true")
    parser.add_argument("--embed", action="store_true")
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--index-type", choices=["master", "updated"], default="master")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING"], default="INFO")

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

    if args.all:
        args.scrape = args.extract = args.clean = args.chunk = args.embed = args.index = True

    try:
        if args.scrape:
            await scrape_stage(args.force, args.index_type)
        if args.extract:
            await extract_stage(args.force, args.index_type)
        if args.clean:
            await clean_stage(args.force, args.index_type)
        if args.chunk:
            await chunk_stage(args.force, args.index_type)
        if args.embed:
            await embed_stage(args.force, args.index_type)
        if args.index:
            await build_index_stage(args.force, args.index_type)

        if not any([args.scrape, args.extract, args.clean, args.chunk, args.embed, args.index]):
            _stage_log("main", "warning", "No stage selected; run with --all or specific flags", index_type=args.index_type)
    except PipelineStageError as exc:
        logger.error("Pipeline failed: %s", exc)
        raise


if __name__ == "__main__":
    asyncio.run(main())

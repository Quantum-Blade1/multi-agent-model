"""
Module for chunking regulatory text into overlapping, clause-aware segments.
"""
import re
from typing import List, Dict
import tiktoken
from rag_pipeline.config import settings

class RegulatoryChunker:
    """
    Chunker specifically designed for regulatory and circular text.
    """
    def __init__(self, model_name: str = "gpt-3.5-turbo"):
        try:
            self.encoder = tiktoken.encoding_for_model(model_name)
        except Exception:
            self.encoder = tiktoken.get_encoding("cl100k_base")
        
        self.chunk_size = settings.CHUNK_SIZE
        self.chunk_overlap = settings.CHUNK_OVERLAP
        self.min_chunk_size = 100
        # Pattern for common regulatory clause headers
        self.clause_pattern = re.compile(r'^(\d+(\.\d+)*|Clause|Section|Para|Article)\.?\s+', re.I)

    def _get_token_count(self, text: str) -> int:
        """
        Returns the number of tokens in the given text.
        """
        return len(self.encoder.encode(text))

    def _slugify(self, text: str) -> str:
        """
        Simple slugifier for IDs.
        """
        return re.sub(r'\W+', '_', text.lower()).strip('_')[:30]

    def chunk(self, circular: Dict) -> List[Dict]:
        """
        Splits circular text into overlapping chunks, avoiding splits in the middle of clauses.
        """
        text = circular.get("cleaned_text", "")
        if not text:
            return []

        title = circular.get("title", "Untitled")
        title_slug = self._slugify(title)
        
        lines = text.splitlines()
        chunks = []
        current_chunk_lines = []
        current_chunk_tokens = 0
        
        for line in lines:
            line_tokens = self._get_token_count(line)
            is_clause_start = bool(self.clause_pattern.match(line))

            # If the current chunk is getting too big OR we hit a new clause start
            if (current_chunk_tokens + line_tokens > self.chunk_size) or (is_clause_start and current_chunk_tokens > self.min_chunk_size):
                if current_chunk_lines:
                    chunk_text = "\n".join(current_chunk_lines)
                    chunks.append(self._create_chunk_dict(circular, title_slug, len(chunks), chunk_text))
                    
                    # Prepare next chunk with overlap
                    # We take the last few lines to fulfill overlap (roughly)
                    overlap_tokens = 0
                    overlap_lines = []
                    for overlap_line in reversed(current_chunk_lines):
                        line_tok = self._get_token_count(overlap_line)
                        if overlap_tokens + line_tok <= self.chunk_overlap:
                            overlap_lines.insert(0, overlap_line)
                            overlap_tokens += line_tok
                        else:
                            break
                    
                    current_chunk_lines = overlap_lines
                    current_chunk_tokens = overlap_tokens

            current_chunk_lines.append(line)
            current_chunk_tokens += line_tokens

        # Add the last chunk
        if current_chunk_lines:
            chunk_text = "\n".join(current_chunk_lines)
            if self._get_token_count(chunk_text) < self.min_chunk_size and chunks:
                # Merge with previous if too small
                last_chunk = chunks[-1]
                last_chunk["text"] += "\n" + chunk_text
            else:
                chunks.append(self._create_chunk_dict(circular, title_slug, len(chunks), chunk_text))

        return chunks

    def _create_chunk_dict(self, circular: Dict, slug: str, index: int, text: str) -> Dict:
        """
        Helper to create the standardized chunk dictionary.
        """
        lines = text.splitlines()
        clause_hint = lines[0][:100] if lines else ""
        
        return {
            "chunk_id": f"{slug}_{index}",
            "text": text,
            "source": circular.get("url", ""),
            "title": circular.get("title", ""),
            "date": circular.get("date", ""),
            "category": circular.get("category", ""),
            "clause_hint": clause_hint
        }

    def chunk_all(self, circulars: List[Dict]) -> List[Dict]:
        """
        Processes a list of circulars into a flat list of chunks.
        """
        all_chunks = []
        for circ in circulars:
            all_chunks.extend(self.chunk(circ))
        
        print(f"Generated {len(all_chunks)} total chunks from {len(circulars)} circulars.")
        return all_chunks

def chunk_data(data):
    """
    Legacy stub compatibility.
    """
    chunker = RegulatoryChunker()
    if isinstance(data, list):
        return chunker.chunk_all(data)
    return chunker.chunk(data)

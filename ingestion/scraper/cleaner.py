"""
Module for cleaning and preprocessing scraped text data from RBI circulars.
"""
import os
import re
import json
import unicodedata
from typing import List, Dict
from ingestion.config import settings

class TextCleaner:
    """
    Class to handle cleaning and filtering of extracted text.
    """
    def __init__(self):
        self.cleaned_data_dir = settings.CLEANED_DATA_DIR
        os.makedirs(self.cleaned_data_dir, exist_ok=True)
        self.keywords = [
            "KYC", "NBFC", "loan disbursement", "AML", "risk", 
            "compliance", "master circular"
        ]

    def _slugify(self, text: str) -> str:
        """
        Creates a filename-friendly slug from text.
        """
        text = text.lower()
        text = re.sub(r'[^\w\s-]', '', text)
        return re.sub(r'[-\s]+', '_', text).strip('_')[:50]

    def clean(self, raw_text: str) -> str:
        """
        Applies a series of cleaning steps to the raw text.
        """
        if not raw_text:
            return ""

        # 6. Normalize unicode to ASCII where possible
        text = unicodedata.normalize('NFKD', raw_text).encode('ascii', 'ignore').decode('ascii')

        # 5. Fix broken hyphenated words across lines (re-join them)
        # Handle cases like "deci-\nsion" -> "decision"
        text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)

        lines = text.splitlines()
        cleaned_lines = []

        for line in lines:
            stripped_line = line.strip()
            
            # 1. Remove page headers/footers
            # (lines with only numbers, "RBI", "Page X of Y")
            if re.match(r'^\d+$', stripped_line): continue
            if re.match(r'^RBI$', stripped_line, re.I): continue
            if re.match(r'^Page\s+\d+(\s+of\s+\d+)?$', stripped_line, re.I): continue

            # 3. Remove special characters except: . , : ; ( ) / - % and alphanumerics
            # We keep spaces too.
            stripped_line = re.sub(r'[^a-zA-Z0-9\s.,:;()/\-%]', '', stripped_line)

            # 4. Remove lines shorter than 20 characters (likely noise)
            if len(stripped_line) < 20:
                continue

            cleaned_lines.append(stripped_line)

        # 2. Remove excessive whitespace and newlines (normalize to single newline)
        text = "\n".join(cleaned_lines)
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        
        return text.strip()

    def clean_all(self, circulars: List[Dict]) -> List[Dict]:
        """
        Cleans all circulars and saves them to individual JSON files.
        """
        updated_list = []
        for circ in circulars:
            raw_text = circ.get("raw_text", "")
            cleaned_text = self.clean(raw_text)
            
            if not cleaned_text:
                continue

            circ["cleaned_text"] = cleaned_text
            
            # Save to CLEANED_DATA_DIR/{title_slug}.json
            title = circ.get("title", "untitled")
            slug = self._slugify(title)
            save_path = os.path.join(self.cleaned_data_dir, f"{slug}.json")
            
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(circ, f, indent=4)
            
            updated_list.append(circ)
            
        print(f"Cleaned and saved {len(updated_list)} circulars to {self.cleaned_data_dir}")
        return updated_list

    def filter_relevant(self, circulars: List[Dict]) -> List[Dict]:
        """
        Keeps only circulars containing specified keywords.
        """
        relevant_circulars = []
        filtered_out_titles = []

        for circ in circulars:
            text = circ.get("cleaned_text", "").lower()
            if any(kw.lower() in text for kw in self.keywords):
                relevant_circulars.append(circ)
            else:
                filtered_out_titles.append(circ.get("title", "Unknown Title"))

        if filtered_out_titles:
            print(f"Filtered out {len(filtered_out_titles)} irrelevant circulars:")
            for title in filtered_out_titles:
                print(f" - {title}")
        
        return relevant_circulars

def clean_text(text):
    """
    Legacy stub compatibility.
    """
    cleaner = TextCleaner()
    return cleaner.clean(text)

"""
Module for downloading and extracting text from RBI PDF circulars.
"""
import os
import json
import re
import requests
import pdfplumber
from PyPDF2 import PdfReader
from typing import List, Dict, Optional
from rag_pipeline.config import settings

class PDFExtractor:
    """
    Class to handle downloading and text extraction from PDF files.
    """
    def __init__(self):
        self.raw_data_dir = settings.RAW_DATA_DIR
        os.makedirs(self.raw_data_dir, exist_ok=True)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def _sanitize_filename(self, title: str) -> str:
        """
        Sanitizes a string to be used as a filename.
        """
        # Remove non-alphanumeric characters and replace spaces with underscores
        title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
        return title[:100] + ".pdf"  # Limit length

    def download_pdf(self, url: str, title: str) -> Optional[str]:
        """
        Downloads PDF from URL, saves it locally, and returns the file path.
        """
        if not url.endswith(".pdf"):
            # Some RBI links might not directly end with .pdf, but we can try to download
            # and verify the content type. For now, assume it's a PDF if it's from the circular table.
            pass

        filename = self._sanitize_filename(title)
        save_path = os.path.join(self.raw_data_dir, filename)

        if os.path.exists(save_path):
            print(f"Skipping download, file exists: {filename}")
            return save_path

        try:
            print(f"Downloading PDF from: {url}")
            response = requests.get(url, headers=self.headers, stream=True, timeout=30)
            response.raise_for_status()
            
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return save_path
        except Exception as e:
            print(f"Failed to download PDF from {url}: {e}")
            return None

    def extract_text(self, pdf_path: str) -> str:
        """
        Extracts full text from a PDF using pdfplumber with PyPDF2 as fallback.
        """
        text = ""
        try:
            # Primary extraction using pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            
            if text.strip():
                return text
        except Exception as e:
            print(f"pdfplumber failed for {pdf_path}: {e}")

        # Fallback to PyPDF2
        try:
            print(f"Attempting fallback extraction with PyPDF2 for {pdf_path}")
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            return text
        except Exception as e:
            print(f"PyPDF2 also failed for {pdf_path}: {e}")
            return ""

    def process_circular(self, circular: Dict) -> Optional[Dict]:
        """
        Downloads the PDF and extracts text for a single circular.
        """
        url = circular.get("url")
        title = circular.get("title")
        
        if not url:
            return None

        pdf_path = self.download_pdf(url, title)
        if not pdf_path:
            return None

        raw_text = self.extract_text(pdf_path)
        if not raw_text.strip():
            print(f"Warning: No text extracted from {pdf_path}")
            return None

        processed_circular = circular.copy()
        processed_circular.update({
            "raw_text": raw_text,
            "pdf_path": pdf_path
        })
        return processed_circular

    def process_all(self, circulars: List[Dict]) -> List[Dict]:
        """
        Processes a list of circulars, logs failures, and returns successes.
        """
        processed_list = []
        failed_list = []

        for circ in circulars:
            result = self.process_circular(circ)
            if result:
                processed_list.append(result)
            else:
                failed_list.append(circ)

        if failed_list:
            failed_path = os.path.join(self.raw_data_dir, "failed.json")
            with open(failed_path, "w", encoding="utf-8") as f:
                json.dump(failed_list, f, indent=4)
            print(f"Logged {len(failed_list)} failures to {failed_path}")

        return processed_list

def extract_text_from_pdf(file_path):
    """
    Legacy stub compatibility.
    """
    extractor = PDFExtractor()
    return extractor.extract_text(file_path)

"""
Configuration settings for the RAG pipeline.
"""
import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    """
    Application settings using pydantic-settings.
    """
    # URLs for RBI circulars
    RBI_CIRCULAR_BASE_URL: str = "https://www.rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx"
    RBI_MASTER_CIRCULAR_URL: str = "https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx"

    # Data directory paths
    RAW_DATA_DIR: str = "rag_pipeline/data/raw/"
    CLEANED_DATA_DIR: str = "rag_pipeline/data/cleaned/"
    INDEX_DIR: str = "rag_pipeline/data/indexes/"

    # Index names
    MASTER_INDEX_NAME: str = "master_index"
    UPDATED_INDEX_NAME: str = "updated_index"

    # Chunking settings
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64

    # Embedding model settings
    BGE_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"

    # Target categories for classification/filtering
    TARGET_CATEGORIES: List[str] = ["KYC", "NBFC", "Loan", "AML", "Compliance"]

    # Sensitive AWS Credentials (loaded from .env)
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")

    # Pydantic configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate settings
settings = Settings()

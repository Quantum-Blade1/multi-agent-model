from datetime import datetime, UTC
from enum import Enum
from typing import Any, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ComplianceStatus(Enum):
    """Enumeration for compliance decision outcomes."""
    APPROVED = "approved"
    REJECTED = "rejected"
    REVIEW = "review"


class AgentErrorType(Enum):
    """Enumeration for types of errors that can occur in agents."""
    VALIDATION = "validation"
    LLM = "llm"
    RETRIEVAL = "retrieval"
    TIMEOUT = "timeout"
    S3 = "s3"
    SANCTIONS = "sanctions"
    UNKNOWN = "unknown"


class ShortCircuitReason(Enum):
    """Enumeration for reasons why the compliance process might short-circuit."""
    DOCUMENT_MISSING = "document_missing"
    SANCTIONS_HIT = "sanctions_hit"
    CRITICAL_AGENT_FAILURE = "critical_agent_failure"


class AgentError(BaseModel):
    """Represents an error encountered by an agent during processing."""
    model_config = ConfigDict(strict=True)

    agent: str = Field(description="The name of the agent that encountered the error.")
    error_type: AgentErrorType = Field(description="The type of error that occurred.")
    message: str = Field(description="A descriptive message about the error.")
    recoverable: bool = Field(description="Whether the error is recoverable and processing can continue.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="The UTC timestamp when the error occurred.")


class RagChunk(BaseModel):
    """Represents a chunk of text retrieved from the RAG system."""
    model_config = ConfigDict(strict=True)

    text: str = Field(description="The text content of the chunk.")
    source: str = Field(description="The source document or location of the chunk.")
    score: float = Field(ge=0.0, le=1.0, description="The relevance score of the chunk, ranging from 0.0 to 1.0.")
    chunk_index: int = Field(description="The index of the chunk within its source.")


class ComplianceInput(BaseModel):
    """Input data for the compliance processing pipeline."""
    model_config = ConfigDict(strict=True)

    request_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique identifier for the request, auto-generated as UUID4 if not provided.")
    user_data: dict[str, Any] = Field(description="Dictionary containing user-specific data for compliance checking.")
    documents: list[dict[str, Any]] = Field(description="List of documents provided for compliance verification.")
    query: str = Field(min_length=10, description="The compliance query string, must be at least 10 characters long.")
    correlation_id: str | None = Field(default=None, description="Optional identifier for distributed tracing across services.")

    @field_validator("request_id", mode="before")
    @classmethod
    def generate_request_id(cls, v: str) -> str:
        """Auto-generate a UUID4 request_id if an empty string is provided."""
        return str(uuid4()) if v == "" else v

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        """Strip whitespace from query and raise ValueError if blank after stripping."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Query cannot be blank after stripping whitespace.")
        return stripped


class ComplianceOutput(BaseModel):
    """Output data from the compliance processing pipeline."""
    model_config = ConfigDict(strict=True)

    request_id: str = Field(description="Unique identifier for the request, matching the input.")
    correlation_id: str | None = Field(default=None, description="Optional identifier for distributed tracing, matching the input.")
    status: ComplianceStatus = Field(description="The final compliance status decision.")
    reason: str = Field(description="A human-readable explanation for the compliance decision.")
    clauses: list[str] = Field(description="List of relevant compliance clauses or rules triggered.")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score of the compliance decision, ranging from 0.0 to 1.0.")
    rules_used: list[str] = Field(description="List of rules or policies applied during processing.")
    agent_errors: list[AgentError] = Field(description="List of errors encountered by agents during processing.")
    short_circuit_reason: ShortCircuitReason | None = Field(default=None, description="Reason for short-circuiting the process, if applicable.")
    processing_ms: float | None = Field(default=None, description="Total processing time in milliseconds, if available.")
    confidence_adjustment: Any | None = Field(default=None, description="Breakdown of confidence adjustments applied by calibration system.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="The UTC timestamp when the output was generated.")

    @model_validator(mode="after")
    def cap_confidence_on_errors(self) -> "ComplianceOutput":
        """Cap confidence at 0.6 if there are any non-recoverable agent errors."""
        if self.agent_errors and any(not error.recoverable for error in self.agent_errors):
            self.confidence = min(self.confidence, 0.6)
        return self


class AgentState(TypedDict):
    """TypedDict representing the state passed between agents in the LangGraph workflow."""
    
    # Input fields
    request_id: str
    correlation_id: str | None
    user_data: dict[str, Any]
    documents: list[dict[str, Any]]
    query: str
    
    # document_agent outputs
    doc_check_passed: bool
    missing_docs: list[str]
    
    # rag_agent outputs (concatenated clause text for LLM prompts)
    rag_context: str

    # Per-agent structured outputs for the decision agent
    agent_outputs: dict[str, Any]

    # transaction_agent outputs
    foir_value: float
    foir_passed: bool
    emi_breakdown: dict[str, float]  # principal, interest, total_emi
    
    # sanctions_agent outputs
    sanctions_hit: bool
    matched_entity: str | None
    sanctions_score: float  # 0.0–1.0 fuzzy match score
    
    # temporal_agent outputs
    expired_docs: list[str]
    temporal_passed: bool
    days_to_expiry: dict[str, int]  # doc_type → days remaining
    
    # decision_agent outputs
    compliance_output: ComplianceOutput | None
    
    # Graph control fields
    agent_errors: list[AgentError]  # append-only across all agents
    short_circuit_reason: str | None
    graph_start_time: float  # time.monotonic() at graph entry


__all__ = [
    "ComplianceStatus",
    "AgentErrorType",
    "ShortCircuitReason",
    "AgentError",
    "RagChunk",
    "ComplianceInput",
    "ComplianceOutput",
    "AgentState",
]

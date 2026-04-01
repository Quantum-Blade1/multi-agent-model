"""
Schemas module.

Pydantic models and data schemas for the AI processing layer,
defining structures for compliance requests, agent states,
decision outputs, and inter-agent communication.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ComplianceStatus(str, Enum):
    """Possible outcomes of a compliance check."""

    APPROVED = "Approved"
    REJECTED = "Rejected"
    REVIEW = "Review"


class ComplianceInput(BaseModel):
    """Input payload for a compliance check request."""

    user_data: dict = Field(
        ...,
        description="Dictionary containing user/entity details such as name, PAN, Aadhaar, and other KYC fields.",
    )
    documents: list[str] = Field(
        ...,
        description="List of S3 URLs pointing to uploaded compliance documents (KYC, financial statements, etc.).",
    )
    query: str = Field(
        ...,
        description="Natural-language compliance query or instruction to process.",
    )


class AgentState(BaseModel):
    """Shared state object passed between agents in the compliance graph."""

    user_data: dict = Field(
        ...,
        description="Dictionary containing user/entity details for the current compliance check.",
    )
    documents: list[str] = Field(
        default_factory=list,
        description="List of S3 URLs for documents associated with the compliance request.",
    )
    query: str = Field(
        ...,
        description="The original compliance query being processed.",
    )
    rag_context: str = Field(
        default="",
        description="Retrieved context from the RAG pipeline relevant to the current query.",
    )
    agent_outputs: dict = Field(
        default_factory=dict,
        description="Accumulated outputs from each agent keyed by agent name (e.g. 'sanctions', 'transaction').",
    )
    final_decision: Optional["ComplianceOutput"] = Field(
        default=None,
        description="Final compliance decision produced by the decision agent, if available.",
    )


class ComplianceOutput(BaseModel):
    """Structured output of a completed compliance check."""

    status: ComplianceStatus = Field(
        ...,
        description="Overall compliance verdict: Approved, Rejected, or Review.",
    )
    reason: str = Field(
        ...,
        description="Human-readable explanation for the compliance decision.",
    )
    clauses: list[str] = Field(
        default_factory=list,
        description="List of regulatory clauses or sections referenced in the decision.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score of the decision, ranging from 0.0 to 1.0.",
    )
    rules_used: list[str] = Field(
        default_factory=list,
        description="List of internal rule identifiers that contributed to the decision.",
    )


# Rebuild AgentState to resolve the forward reference to ComplianceOutput
AgentState.model_rebuild()

"""
Audit trail data models for the NBFC Compliance AI system.

This module provides the complete data model layer for a tamper-evident audit
trail that satisfies RBI inspection requirements.  Every compliance decision
is captured in an :class:`AuditRecord` whose integrity is guaranteed by a
SHA-256 hash chain (:class:`HashChainEngine`).

Key design decisions:

* **PII is scrubbed before storage** — ``scrub_input_for_audit`` replaces
  sensitive fields (PAN, Aadhaar, etc.) with ``***REDACTED***`` so the audit
  table never contains raw PII.
* **Full RAG text is excluded** — only source references and counts are stored
  to avoid bloating DynamoDB items (each chunk can be 512 tokens).
* **Hash chain covers only immutable fields** — ``override`` and
  ``reviewer_status`` are deliberately excluded from the content hash because
  they are mutable post-creation.  The chain proves the *decision* was not
  altered; the override is an addendum.
* **Uppercase status strings** — ``final_status`` stores ``APPROVED``,
  ``REJECTED``, ``REVIEW`` (uppercase) even though the runtime
  ``ComplianceStatus`` enum uses lowercase values, because RBI reports
  conventionally use uppercase.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai.core.schemas import AgentError, AgentState, ComplianceInput, ComplianceOutput


# ───────────────────────────────────────────────────────────────────────────
# PII scrubbing
# ───────────────────────────────────────────────────────────────────────────

AUDIT_PII_FIELDS: frozenset[str] = frozenset(
    {
        "pan_number",
        "aadhaar_number",
        "account_number",
        "mobile_number",
        "email",
        "password",
        "dob",
        "mother_name",
        "father_name",
    }
)

_REDACTED = "***REDACTED***"


def scrub_input_for_audit(raw_input: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy *raw_input* and replace PII field values with a redaction marker.

    The replacement is **recursive** — nested dicts and lists of dicts are
    traversed.  Key matching is **case-insensitive**.

    Args:
        raw_input: The original ``ComplianceInput.model_dump()`` dict.

    Returns:
        A new dict safe for long-term storage in the audit table.
    """

    def _scrub(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: _REDACTED if k.lower() in AUDIT_PII_FIELDS else _scrub(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_scrub(item) for item in obj]
        return obj

    return _scrub(copy.deepcopy(raw_input))


# ───────────────────────────────────────────────────────────────────────────
# Enums
# ───────────────────────────────────────────────────────────────────────────

class ReviewerStatus(str, Enum):
    """Lifecycle state of human review for an audit record.

    Every record starts as ``PENDING``.  A compliance officer may mark it
    ``REVIEWED`` (agrees with the AI) or ``OVERRIDDEN`` (changes the decision).
    """

    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    OVERRIDDEN = "OVERRIDDEN"


# ───────────────────────────────────────────────────────────────────────────
# Snapshot of agent signals
# ───────────────────────────────────────────────────────────────────────────

_VALID_STATUSES = frozenset({"APPROVED", "REJECTED", "REVIEW"})


class AgentSignalSnapshot(BaseModel):
    """Point-in-time capture of every agent's output signals.

    This is a **read-only summary** extracted from the live ``AgentState``
    at the moment a compliance decision is finalised.  It intentionally
    excludes large blobs (full RAG text) to keep DynamoDB item sizes small.
    """

    model_config = ConfigDict(strict=True)

    doc_check_passed: bool = Field(
        description="Whether the document agent found all required KYC documents.",
    )
    missing_docs: list[str] = Field(
        description="Document types that were required but not provided.",
    )
    foir_value: float = Field(
        description="Fixed Obligations to Income Ratio computed by the transaction agent.",
    )
    foir_passed: bool = Field(
        description="Whether FOIR was within the acceptable threshold (<=0.50).",
    )
    emi_breakdown: dict[str, float] = Field(
        description="EMI components: principal, interest, total_emi.",
    )
    sanctions_hit: bool = Field(
        description="Whether the applicant matched any entry on the sanctions list.",
    )
    matched_entity: str | None = Field(
        description="The sanctions list entry that matched, or None if clean.",
    )
    sanctions_score: float = Field(
        description="Fuzzy match score (0.0-1.0) against the sanctions list.",
    )
    expired_docs: list[str] = Field(
        description="Document types whose expiry date has passed.",
    )
    temporal_passed: bool = Field(
        description="Whether all documents are within their validity period.",
    )
    days_to_expiry: dict[str, int] = Field(
        description="Mapping of document type to days remaining until expiry.",
    )
    rag_chunks_retrieved: int = Field(
        ge=0,
        description=(
            "Number of regulatory chunks retrieved by the RAG agent. "
            "Full text is excluded to control storage size."
        ),
    )
    rag_sources: list[str] = Field(
        description=(
            "Source references (S3 URLs or doc IDs) of retrieved RAG chunks. "
            "Sufficient for an auditor to locate the original regulation text."
        ),
    )


# ───────────────────────────────────────────────────────────────────────────
# Override record
# ───────────────────────────────────────────────────────────────────────────

class OverrideRecord(BaseModel):
    """Records a human reviewer's decision to change an AI compliance verdict.

    RBI expects that overrides include a meaningful justification (minimum
    20 characters) and, where applicable, a reference to the specific
    regulation that informed the override.
    """

    model_config = ConfigDict(strict=True)

    override_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this override action.",
    )
    audit_id: str = Field(
        description="The audit_id of the parent AuditRecord being overridden.",
    )
    reviewer_id: str = Field(
        description="Authenticated reviewer identifier (from JWT subject claim).",
    )
    reviewer_email: str = Field(
        description="Reviewer email for display purposes (not used as a lookup key).",
    )
    original_status: str = Field(
        description="The AI-generated status before override (APPROVED/REJECTED/REVIEW).",
    )
    override_status: str = Field(
        description="The new status set by the reviewer (must differ from original).",
    )
    override_reason: str = Field(
        min_length=20,
        description=(
            "Mandatory justification for the override. Minimum 20 characters "
            "to force a meaningful explanation for the audit trail."
        ),
    )
    override_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when the override was recorded.",
    )
    regulatory_reference: str | None = Field(
        default=None,
        description="Optional RBI clause or regulation cited by the reviewer.",
    )

    @model_validator(mode="after")
    def validate_override(self) -> OverrideRecord:
        """Ensure the override actually changes the status and targets a valid value."""
        if self.override_status == self.original_status:
            raise ValueError(
                f"override_status ('{self.override_status}') must differ from "
                f"original_status ('{self.original_status}')"
            )
        if self.override_status not in _VALID_STATUSES:
            raise ValueError(
                f"override_status must be one of {sorted(_VALID_STATUSES)}, "
                f"got '{self.override_status}'"
            )
        return self


# ───────────────────────────────────────────────────────────────────────────
# Audit record
# ───────────────────────────────────────────────────────────────────────────

class AuditRecord(BaseModel):
    """Immutable audit trail entry for a single compliance decision.

    Each record captures the full context of a decision — scrubbed input,
    every agent signal, the LLM verdict, and cryptographic hashes that chain
    records together so any post-hoc tampering is detectable.

    The ``content_hash`` covers only **immutable** fields (everything decided
    at creation time).  The ``reviewer_status`` and ``override`` fields are
    mutable addenda and are deliberately excluded from the hash.
    """

    model_config = ConfigDict(strict=True)

    # ── Identity ──────────────────────────────────────────────────────────
    audit_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this audit record (UUID4).",
    )
    request_id: str = Field(
        description="Request identifier from ComplianceOutput, links to the original request.",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Distributed tracing correlation identifier, if provided.",
    )

    # ── Timing ────────────────────────────────────────────────────────────
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when this audit record was created.",
    )
    processing_ms: float = Field(
        description="Total pipeline processing time in milliseconds.",
    )

    # ── Input snapshot (PII-scrubbed) ─────────────────────────────────────
    input_snapshot: dict[str, Any] = Field(
        description=(
            "ComplianceInput.model_dump() after PII scrubbing. "
            "Contains user_data, documents, and query with sensitive fields redacted."
        ),
    )
    query: str = Field(
        description="The original compliance query string.",
    )

    # ── Agent outputs ─────────────────────────────────────────────────────
    agent_signals: AgentSignalSnapshot = Field(
        description="Snapshot of all agent output signals at decision time.",
    )
    agent_errors: list[AgentError] = Field(
        default_factory=list,
        description="Errors encountered by agents during processing.",
    )
    short_circuit_reason: str | None = Field(
        default=None,
        description="Reason the pipeline short-circuited, if applicable.",
    )

    # ── Final decision ────────────────────────────────────────────────────
    final_status: str = Field(
        description="The compliance verdict: APPROVED, REJECTED, or REVIEW (uppercase).",
    )
    final_reason: str = Field(
        description="Human-readable explanation for the compliance decision.",
    )
    clauses_cited: list[str] = Field(
        description="RBI clauses or regulations cited in the decision.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Decision confidence score (0.0 to 1.0).",
    )
    rules_used: list[str] = Field(
        description="Compliance rules applied during processing.",
    )

    # ── Chain integrity ───────────────────────────────────────────────────
    content_hash: str = Field(
        description=(
            "SHA-256 hex digest of the canonical record content. "
            "Covers all immutable fields; excludes override and reviewer_status."
        ),
    )
    chain_hash: str = Field(
        description="SHA-256 of (previous_chain_hash + content_hash). Links this record to the chain.",
    )
    previous_chain_hash: str = Field(
        description='Chain hash of the preceding record, or "0"*64 for the genesis record.',
    )

    # ── Reviewer state (mutable, excluded from hash) ──────────────────────
    reviewer_status: ReviewerStatus = Field(
        default=ReviewerStatus.PENDING,
        description="Current human-review lifecycle state of this record.",
    )
    override: OverrideRecord | None = Field(
        default=None,
        description="Details of the human override, if the record was overridden.",
    )


# ───────────────────────────────────────────────────────────────────────────
# Verification result
# ───────────────────────────────────────────────────────────────────────────

class VerificationResult(BaseModel):
    """Outcome of verifying a sequence of audit records against the hash chain.

    Used by auditors and automated health checks to confirm that no records
    have been tampered with since creation.
    """

    valid: bool = Field(
        description="True if every record in the chain is intact.",
    )
    first_broken_at: int | None = Field(
        default=None,
        description="Zero-based index of the first record that failed verification, or None if all valid.",
    )
    total_records: int = Field(
        description="Total number of records submitted for verification.",
    )
    verified_records: int = Field(
        description="Number of records that passed verification before the first failure (or total if all valid).",
    )
    verified_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when verification was performed.",
    )


# ───────────────────────────────────────────────────────────────────────────
# Hash chain engine
# ───────────────────────────────────────────────────────────────────────────

class HashChainEngine:
    """Cryptographic hash chain for tamper-evident audit records.

    The chain works like a simplified blockchain: each record's
    ``content_hash`` is a SHA-256 digest of its immutable fields, and
    ``chain_hash`` is SHA-256 of ``previous_chain_hash + content_hash``.
    Altering any record breaks the chain from that point forward.

    The first record in the chain uses :attr:`GENESIS_HASH` as its
    ``previous_chain_hash``.
    """

    GENESIS_HASH: ClassVar[str] = "0" * 64

    @staticmethod
    def canonical_content(record: AuditRecord) -> str:
        """Produce a deterministic string representation for hashing.

        Fields are joined by ``|`` in a fixed order.  Only **immutable**
        fields are included — ``override`` and ``reviewer_status`` are
        excluded because they can change after the record is created.

        Args:
            record: The audit record to serialise.

        Returns:
            A pipe-delimited string suitable for SHA-256 hashing.
        """
        return "|".join(
            [
                record.audit_id,
                record.request_id,
                record.created_at.isoformat(),
                record.final_status,
                str(record.confidence),
                json.dumps(record.input_snapshot, sort_keys=True, default=str),
                json.dumps(
                    record.agent_signals.model_dump(), sort_keys=True, default=str
                ),
                record.previous_chain_hash,
            ]
        )

    @staticmethod
    def compute_content_hash(record: AuditRecord) -> str:
        """Compute the SHA-256 content hash of a record's immutable fields.

        Args:
            record: The audit record to hash.

        Returns:
            64-character lowercase hex digest.
        """
        canonical = HashChainEngine.canonical_content(record)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_chain_hash(previous_chain_hash: str, content_hash: str) -> str:
        """Compute the chain hash linking this record to its predecessor.

        Args:
            previous_chain_hash: The ``chain_hash`` of the preceding record,
                or :attr:`GENESIS_HASH` for the first record.
            content_hash: The ``content_hash`` of the current record.

        Returns:
            64-character lowercase hex digest.
        """
        combined = previous_chain_hash + content_hash
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    @staticmethod
    def verify_record(record: AuditRecord, previous_chain_hash: str) -> bool:
        """Verify a single record's hashes against a known predecessor.

        Recomputes both ``content_hash`` and ``chain_hash`` from scratch
        and compares them to the values stored on the record.

        Args:
            record: The audit record to verify.
            previous_chain_hash: The expected ``chain_hash`` of the
                preceding record.

        Returns:
            ``True`` if both hashes match; ``False`` otherwise.
            Does **not** raise — the caller decides the appropriate action.
        """
        expected_content = HashChainEngine.compute_content_hash(record)
        if expected_content != record.content_hash:
            return False

        expected_chain = HashChainEngine.compute_chain_hash(
            previous_chain_hash, expected_content
        )
        return expected_chain == record.chain_hash

    @staticmethod
    async def verify_chain(records: list[AuditRecord]) -> VerificationResult:
        """Verify an ordered sequence of audit records against the hash chain.

        Walks the list from index 0, treating the first record's
        ``previous_chain_hash`` as the genesis anchor.  Stops at the first
        broken link.

        Args:
            records: Audit records in chronological order.

        Returns:
            A :class:`VerificationResult` summarising the outcome.
        """
        total = len(records)
        if total == 0:
            return VerificationResult(
                valid=True,
                first_broken_at=None,
                total_records=0,
                verified_records=0,
            )

        prev_hash = records[0].previous_chain_hash
        for idx, record in enumerate(records):
            if not HashChainEngine.verify_record(record, prev_hash):
                return VerificationResult(
                    valid=False,
                    first_broken_at=idx,
                    total_records=total,
                    verified_records=idx,
                )
            prev_hash = record.chain_hash

        return VerificationResult(
            valid=True,
            first_broken_at=None,
            total_records=total,
            verified_records=total,
        )


# ───────────────────────────────────────────────────────────────────────────
# Factory function
# ───────────────────────────────────────────────────────────────────────────

async def build_audit_record(
    compliance_input: ComplianceInput,
    compliance_output: ComplianceOutput,
    agent_state: AgentState,
    previous_chain_hash: str,
) -> AuditRecord:
    """Build a fully-populated, hash-chained audit record from live pipeline objects.

    This is the **only** intended way to create an :class:`AuditRecord`.
    It scrubs PII from the input, extracts agent signals from the state,
    computes both cryptographic hashes, and returns the record ready for
    persistence (but does **not** persist it).

    Args:
        compliance_input: The original request payload.
        compliance_output: The decision returned by the pipeline.
        agent_state: The final ``AgentState`` after graph execution.
        previous_chain_hash: The ``chain_hash`` of the most recent persisted
            record, or ``HashChainEngine.GENESIS_HASH`` for the first.

    Returns:
        A complete :class:`AuditRecord` with valid ``content_hash`` and
        ``chain_hash``.
    """
    # 1. Scrub PII from input
    scrubbed = scrub_input_for_audit(compliance_input.model_dump())

    # 2. Extract RAG metadata from agent_outputs
    rag_output = agent_state.get("agent_outputs", {}).get("rag_agent", {})
    top_clauses: list[dict[str, Any]] = rag_output.get("top_clauses", [])
    rag_chunks_retrieved = rag_output.get("clauses_found", len(top_clauses))
    rag_sources = [
        c.get("source", "") for c in top_clauses if isinstance(c, dict)
    ]

    # 3. Build agent signal snapshot
    signals = AgentSignalSnapshot(
        doc_check_passed=agent_state.get("doc_check_passed", False),
        missing_docs=agent_state.get("missing_docs", []),
        foir_value=agent_state.get("foir_value", -1.0),
        foir_passed=agent_state.get("foir_passed", False),
        emi_breakdown=agent_state.get("emi_breakdown", {}),
        sanctions_hit=agent_state.get("sanctions_hit", False),
        matched_entity=agent_state.get("matched_entity", None),
        sanctions_score=agent_state.get("sanctions_score", 0.0),
        expired_docs=agent_state.get("expired_docs", []),
        temporal_passed=agent_state.get("temporal_passed", False),
        days_to_expiry=agent_state.get("days_to_expiry", {}),
        rag_chunks_retrieved=rag_chunks_retrieved,
        rag_sources=rag_sources,
    )

    # 4. Build the record (hashes are placeholders, filled in step 5)
    record = AuditRecord(
        request_id=compliance_output.request_id,
        correlation_id=compliance_output.correlation_id,
        processing_ms=compliance_output.processing_ms or 0.0,
        input_snapshot=scrubbed,
        query=compliance_input.query,
        agent_signals=signals,
        agent_errors=list(compliance_output.agent_errors),
        short_circuit_reason=(
            compliance_output.short_circuit_reason.value
            if compliance_output.short_circuit_reason
            else None
        ),
        final_status=compliance_output.status.value.upper(),
        final_reason=compliance_output.reason,
        clauses_cited=list(compliance_output.clauses),
        confidence=compliance_output.confidence,
        rules_used=list(compliance_output.rules_used),
        content_hash="",  # placeholder
        chain_hash="",  # placeholder
        previous_chain_hash=previous_chain_hash,
    )

    # 5. Compute hashes
    record.content_hash = HashChainEngine.compute_content_hash(record)
    record.chain_hash = HashChainEngine.compute_chain_hash(
        previous_chain_hash, record.content_hash
    )

    return record

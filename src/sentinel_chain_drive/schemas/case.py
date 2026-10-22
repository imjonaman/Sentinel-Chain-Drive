"""Pydantic schemas and contracts for Phase 9 Case Management and Dossiers."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinel_chain_drive.db.models.case import (
    CaseCategory,
    CasePriority,
    CaseStatus,
    EvidenceType,
)

DANGEROUS_PATH_PATTERNS = [
    r"\.\./",
    r"\.\\",
    r"\.exe$",
    r"\.bat$",
    r"\.sh$",
    r"\.cmd$",
    r"<script",
    r"javascript:",
]

PROHIBITED_PAYLOAD_KEYS = {
    "raw_pan",
    "pan",
    "card_number",
    "private_key",
    "access_token",
    "secret",
    "password",
    "cvv",
    "pin",
}


class CaseCreateRequest(BaseModel):
    """Payload to open a new investigation case."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Concise description of the suspicious pattern or investigation trigger",
    )
    description: str | None = Field(
        default=None,
        description="Detailed background narrative or notes",
    )
    category: CaseCategory = Field(
        default=CaseCategory.MANUAL,
        description="Category: FRAUD_ALERT, POLICY_VIOLATION, SUSPICIOUS_TRANSACTION, MANUAL",
    )
    priority: CasePriority = Field(
        default=CasePriority.MEDIUM,
        description="Priority/severity level",
    )
    risk_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Initial risk score (0-100)",
    )
    assigned_analyst_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional assigned analyst identifier",
    )
    assigned_role: str | None = Field(
        default=None,
        max_length=64,
        description="Optional assigned analyst role tier",
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional correlation identifier linking to originating transaction/alert",
    )
    source_type: str = Field(
        default="MANUAL",
        max_length=32,
        description="FRAUD_ALERT, POLICY_EVALUATION, TRANSACTION, MANUAL",
    )
    source_id: str | None = Field(
        default=None,
        max_length=128,
        description="External source record ID for deduplication and idempotency",
    )
    transaction_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Initial transactions associated with this case",
    )
    alert_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Initial fraud alerts associated with this case",
    )
    account_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Initial accounts under investigation in this case",
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive structured metadata",
    )


class CaseAssignRequest(BaseModel):
    """Payload to assign or reassign an investigator to a case."""

    model_config = ConfigDict(extra="forbid")

    assigned_analyst_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Identifier of authorized investigator",
    )
    assigned_role: str | None = Field(
        default="INVESTIGATOR",
        max_length=64,
        description="Role: INVESTIGATOR, SENIOR_ANALYST, SUPERVISOR",
    )
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="Assignment notes or instructions",
    )


class CaseStatusTransitionRequest(BaseModel):
    """Payload to trigger an explicit state transition in the case workflow."""

    model_config = ConfigDict(extra="forbid")

    target_status: CaseStatus = Field(
        ...,
        description="Desired new case status",
    )
    reason: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Mandatory justification for this state change",
    )
    resolution_category: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Mandatory when closing case: "
            "CONFIRMED_FRAUD, FALSE_POSITIVE, POLICY_EXCUSED, INCONCLUSIVE"
        ),
    )

    resolution_notes: str | None = Field(
        default=None,
        description="Mandatory closure findings narrative when resolving or closing",
    )
    reopen_reason: str | None = Field(
        default=None,
        description="Mandatory supervisory rationale when reopening a closed case",
    )


class CasePriorityUpdateRequest(BaseModel):
    """Payload to escalate or modify case priority."""

    model_config = ConfigDict(extra="forbid")

    priority: CasePriority = Field(
        ...,
        description="New priority level: LOW, MEDIUM, HIGH, CRITICAL",
    )
    reason: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Mandatory rationale for priority escalation/adjustment",
    )


class CaseNoteCreateRequest(BaseModel):
    """Payload to append an investigation note to a case."""

    model_config = ConfigDict(extra="forbid")

    note_text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Investigation commentary or update",
    )
    author_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional author identifier",
    )


class CaseEvidenceCreateRequest(BaseModel):
    """Payload to attach an evidentiary item to an investigation."""

    model_config = ConfigDict(extra="forbid")

    evidence_type: EvidenceType = Field(
        ...,
        description="Evidence type: TRANSACTION_RECORD, GRAPH_SUBGRAPH, AGENT_SIGNATURE, etc.",
    )
    title: str = Field(
        ...,
        min_length=2,
        max_length=128,
        description="Concise evidence title",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Contextual explanation of evidence significance",
    )
    reference_uri: str | None = Field(
        default=None,
        max_length=256,
        description="Safe reference URI or system identifier",
    )
    payload_json: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured non-sensitive evidence attributes",
    )

    @field_validator("reference_uri")
    @classmethod
    def validate_reference_uri(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v_clean = v.strip()
        for pattern in DANGEROUS_PATH_PATTERNS:
            if re.search(pattern, v_clean, re.IGNORECASE):
                raise ValueError(
                    f"Evidence reference_uri contains dangerous or executable pattern: {pattern}"
                )
        return v_clean

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        for pattern in [r"<script", r"javascript:"]:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError("Evidence title contains disallowed scripting characters.")
        return v

    @field_validator("payload_json")
    @classmethod
    def validate_payload(cls, v: dict[str, Any]) -> dict[str, Any]:
        for k in v:
            k_lower = k.lower().replace("-", "_")
            if k_lower in PROHIBITED_PAYLOAD_KEYS or any(
                p in k_lower for p in ["private_key", "password", "access_token", "raw_pan"]
            ):
                raise ValueError(f"Evidence payload contains prohibited sensitive key: {k}")
        return v


class CaseEvidenceResponse(BaseModel):
    """Evidentiary record attached to an investigation case."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    evidence_type: EvidenceType
    title: str
    description: str | None = None
    reference_uri: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    checksum_sha256: str | None = None
    added_by: str
    created_at: datetime


class CaseStatusHistoryResponse(BaseModel):
    """Lifecycle transition entry in case history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    actor: str
    from_status: str
    to_status: str
    transition_type: str
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CaseResponse(BaseModel):
    """Case representation for investigation workflows."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_number: str
    institution_id: uuid.UUID
    category: CaseCategory
    source_type: str
    source_id: str
    status: CaseStatus
    priority: CasePriority
    risk_score: int
    summary: str
    description: str | None = None
    assigned_analyst_id: str | None = None
    assigned_role: str | None = None
    correlation_id: str | None = None
    resolution_category: str | None = None
    resolution_notes: str | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    reopened_at: datetime | None = None
    reopened_by: str | None = None
    reopen_reason: str | None = None
    notes_log: list[dict[str, Any]] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    associated_transaction_ids: list[uuid.UUID] = Field(default_factory=list)
    associated_alert_ids: list[uuid.UUID] = Field(default_factory=list)
    associated_account_ids: list[uuid.UUID] = Field(default_factory=list)
    evidence_count: int = 0


class CaseListResponse(BaseModel):
    """Paginated list of investigation cases."""

    model_config = ConfigDict(from_attributes=True)

    items: list[CaseResponse]
    total: int
    page: int
    page_size: int


class CaseDossierResponse(BaseModel):
    """Compiled evidentiary audit package with tamper-evident checksum."""

    model_config = ConfigDict(from_attributes=True)

    case_id: uuid.UUID
    case_number: str
    institution_id: uuid.UUID
    dossier_hash_sha256: str
    is_tamper_evident: bool = True
    compiled_at: datetime
    compiled_by: str
    case_summary: dict[str, Any]
    transactions: list[dict[str, Any]] = Field(default_factory=list)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    accounts: list[dict[str, Any]] = Field(default_factory=list)
    policy_evaluations: list[dict[str, Any]] = Field(default_factory=list)
    agent_authorizations: list[dict[str, Any]] = Field(default_factory=list)
    ledger_attestations: list[dict[str, Any]] = Field(default_factory=list)
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)
    status_history: list[dict[str, Any]] = Field(default_factory=list)

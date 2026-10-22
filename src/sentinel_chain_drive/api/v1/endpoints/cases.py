"""API endpoints for Investigation Case Management and Dossiers (Phase 9 Feature 9.2 & 9.3)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, status

from sentinel_chain_drive.api.deps import get_case_service, get_recovery_service
from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.db.models.case import (
    CaseCategory,
    CasePriority,
    CaseStatus,
)
from sentinel_chain_drive.schemas.case import (
    CaseAssignRequest,
    CaseCreateRequest,
    CaseDossierResponse,
    CaseEvidenceCreateRequest,
    CaseEvidenceResponse,
    CaseListResponse,
    CaseNoteCreateRequest,
    CasePriorityUpdateRequest,
    CaseResponse,
    CaseStatusHistoryResponse,
    CaseStatusTransitionRequest,
)
from sentinel_chain_drive.schemas.recovery import (
    RecoveryListResponse,
    RecoveryRequestCreate,
    RecoveryResponse,
)
from sentinel_chain_drive.services.case_service import CaseService
from sentinel_chain_drive.services.recovery_service import RecoveryService

router = APIRouter(prefix="/cases", tags=["Investigation Case Management"])


def _require_institution_id(x_institution_id: uuid.UUID | None) -> uuid.UUID:
    """Validate that the caller provided an authorized institution tenant context."""
    if x_institution_id is None:
        raise AppException(
            message="Header X-Institution-ID is required for tenant isolation.",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="MISSING_INSTITUTION_CONTEXT",
        )
    return x_institution_id


def _to_case_response(c: Any) -> CaseResponse:
    tx_ids = [ct.transaction_id for ct in getattr(c, "case_transactions", [])]
    al_ids = [ca.alert_id for ca in getattr(c, "case_alerts", [])]
    ac_ids = [ca.account_id for ca in getattr(c, "case_accounts", [])]
    return CaseResponse(
        id=c.id,
        case_number=c.case_number,
        institution_id=c.institution_id,
        category=c.category,
        source_type=c.source_type,
        source_id=c.source_id,
        status=c.status,
        priority=c.priority,
        risk_score=c.risk_score,
        summary=c.summary,
        description=c.description,
        assigned_analyst_id=c.assigned_analyst_id,
        assigned_role=c.assigned_role,
        correlation_id=c.correlation_id,
        resolution_category=c.resolution_category,
        resolution_notes=c.resolution_notes,
        closed_at=c.closed_at,
        closed_by=c.closed_by,
        reopened_at=c.reopened_at,
        reopened_by=c.reopened_by,
        reopen_reason=c.reopen_reason,
        notes_log=c.notes_log,
        metadata_json=c.metadata_json,
        created_at=c.created_at,
        updated_at=c.updated_at,
        associated_transaction_ids=tx_ids,
        associated_alert_ids=al_ids,
        associated_account_ids=ac_ids,
        evidence_count=len(getattr(c, "evidence_items", [])),
    )


@router.post(
    "",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new investigation case",
    description=("Opens an auditable case, associating initial transactions/alerts idempotently."),
)
async def create_case(
    payload: CaseCreateRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
    service: CaseService = Depends(get_case_service),
) -> CaseResponse:
    institution_id = _require_institution_id(x_institution_id)
    actor = x_actor_id or "system_analyst"

    case = await service.create_case(
        institution_id=institution_id,
        payload=payload,
        actor=actor,
        actor_role=x_actor_role,
    )
    return _to_case_response(case)


@router.get(
    "",
    response_model=CaseListResponse,
    status_code=status.HTTP_200_OK,
    summary="List investigation cases",
    description=("Retrieve paginated cases with status/priority/analyst filters scoped to tenant."),
)
async def list_cases(
    case_status: CaseStatus | None = Query(
        default=None, alias="status", description="Filter by status"
    ),
    priority: CasePriority | None = Query(default=None, description="Filter by priority"),
    category: CaseCategory | None = Query(default=None, description="Filter by category"),
    assigned_analyst_id: str | None = Query(default=None, description="Filter by assigned analyst"),
    limit: int = Query(default=50, ge=1, le=100, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    service: CaseService = Depends(get_case_service),
) -> CaseListResponse:
    institution_id = _require_institution_id(x_institution_id)

    items, total = await service.list_cases(
        institution_id=institution_id,
        limit=limit,
        offset=offset,
        status=case_status,
        priority=priority,
        category=category,
        assigned_analyst_id=assigned_analyst_id,
    )

    page_number = (offset // limit) + 1 if limit > 0 else 1
    return CaseListResponse(
        items=items,
        total=total,
        page=page_number,
        page_size=limit,
    )


@router.get(
    "/{case_id}",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Get case details by ID",
    description=(
        "Retrieve full case details, associated accounts, transactions, and evidence count."
    ),
)
async def get_case(
    case_id: uuid.UUID,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    service: CaseService = Depends(get_case_service),
) -> CaseResponse:
    institution_id = _require_institution_id(x_institution_id)

    case = await service.get_case(case_id=case_id, institution_id=institution_id)
    if case is None:
        raise AppException(
            message=f"Case {case_id} not found in authorized institution scope.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="CASE_NOT_FOUND",
        )
    return _to_case_response(case)


@router.patch(
    "/{case_id}/assign",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign or reassign an investigator",
    description=("Assigns case to an analyst, advancing status from OPEN to UNDER_INVESTIGATION."),
)
async def assign_case(
    case_id: uuid.UUID,
    payload: CaseAssignRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    service: CaseService = Depends(get_case_service),
) -> CaseResponse:
    institution_id = _require_institution_id(x_institution_id)
    actor = x_actor_id or "system_supervisor"

    case = await service.assign_case(
        case_id=case_id,
        institution_id=institution_id,
        payload=payload,
        actor=actor,
    )
    return _to_case_response(case)


@router.patch(
    "/{case_id}/status",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute lifecycle state transition",
    description="Transitions case status following the strict validated state machine.",
)
async def transition_case_status(
    case_id: uuid.UUID,
    payload: CaseStatusTransitionRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
    service: CaseService = Depends(get_case_service),
) -> CaseResponse:
    institution_id = _require_institution_id(x_institution_id)
    actor = x_actor_id or "system_analyst"

    case = await service.transition_status(
        case_id=case_id,
        institution_id=institution_id,
        payload=payload,
        actor=actor,
        actor_role=x_actor_role,
    )
    return _to_case_response(case)


@router.patch(
    "/{case_id}/priority",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Update case priority",
    description="Escalates or modifies case priority with mandatory rationale.",
)
async def update_case_priority(
    case_id: uuid.UUID,
    payload: CasePriorityUpdateRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    service: CaseService = Depends(get_case_service),
) -> CaseResponse:
    institution_id = _require_institution_id(x_institution_id)
    actor = x_actor_id or "system_analyst"

    case = await service.update_priority(
        case_id=case_id,
        institution_id=institution_id,
        payload=payload,
        actor=actor,
    )
    return _to_case_response(case)


@router.post(
    "/{case_id}/notes",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add investigation note",
    description="Appends an analyst note to the case chronological history.",
)
async def add_case_note(
    case_id: uuid.UUID,
    payload: CaseNoteCreateRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    service: CaseService = Depends(get_case_service),
) -> CaseResponse:
    institution_id = _require_institution_id(x_institution_id)
    author = payload.author_id or x_actor_id or "analyst"

    case = await service.add_note(
        case_id=case_id,
        institution_id=institution_id,
        note_text=payload.note_text,
        author=author,
    )
    return _to_case_response(case)


@router.post(
    "/{case_id}/evidence",
    response_model=CaseEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach evidentiary reference",
    description="Attaches verified evidence to the case with SHA-256 integrity checksum.",
)
async def add_case_evidence(
    case_id: uuid.UUID,
    payload: CaseEvidenceCreateRequest,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    service: CaseService = Depends(get_case_service),
) -> CaseEvidenceResponse:
    institution_id = _require_institution_id(x_institution_id)
    author = x_actor_id or "system_analyst"

    evidence = await service.add_evidence(
        case_id=case_id,
        institution_id=institution_id,
        payload=payload,
        author=author,
    )
    return CaseEvidenceResponse.model_validate(evidence)


@router.get(
    "/{case_id}/evidence",
    response_model=list[CaseEvidenceResponse],
    status_code=status.HTTP_200_OK,
    summary="List case evidence items",
    description="Retrieve all evidentiary records and checksums attached to this case.",
)
async def list_case_evidence(
    case_id: uuid.UUID,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    service: CaseService = Depends(get_case_service),
) -> list[CaseEvidenceResponse]:
    institution_id = _require_institution_id(x_institution_id)

    case = await service.get_case(case_id=case_id, institution_id=institution_id)
    if case is None:
        raise AppException(
            message=f"Case {case_id} not found in authorized institution scope.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="CASE_NOT_FOUND",
        )

    evidence_items = await service.case_repo.get_case_evidence(case_id=case_id)
    return [CaseEvidenceResponse.model_validate(ev) for ev in evidence_items]


@router.get(
    "/{case_id}/history",
    response_model=list[CaseStatusHistoryResponse],
    status_code=status.HTTP_200_OK,
    summary="Get case lifecycle transition history",
    description="Retrieve immutable chronological audit trail of state changes and justifications.",
)
async def get_case_history(
    case_id: uuid.UUID,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    service: CaseService = Depends(get_case_service),
) -> list[CaseStatusHistoryResponse]:
    institution_id = _require_institution_id(x_institution_id)

    case = await service.get_case(case_id=case_id, institution_id=institution_id)
    if case is None:
        raise AppException(
            message=f"Case {case_id} not found in authorized institution scope.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="CASE_NOT_FOUND",
        )

    history = await service.case_repo.get_case_history(case_id=case_id)
    return [CaseStatusHistoryResponse.model_validate(hr) for hr in history]


@router.get(
    "/{case_id}/dossier",
    response_model=CaseDossierResponse,
    status_code=status.HTTP_200_OK,
    summary="Compile evidentiary audit dossier",
    description=(
        "Compiles transactions, graph metrics, signatures, ledger proofs, and SHA-256 checksum."
    ),
)
async def get_case_dossier(
    case_id: uuid.UUID,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    service: CaseService = Depends(get_case_service),
) -> CaseDossierResponse:
    institution_id = _require_institution_id(x_institution_id)
    actor = x_actor_id or "audit_analyst"

    return await service.compile_dossier(
        case_id=case_id,
        institution_id=institution_id,
        compiled_by=actor,
    )


@router.post(
    "/{case_id}/recovery-requests",
    response_model=RecoveryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate a recovery request for this case",
    description=(
        "Drafts an inter-bank recovery request under dual control (PENDING_APPROVAL status)."
    ),
)
async def create_case_recovery_request(
    case_id: uuid.UUID,
    payload: RecoveryRequestCreate,
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> RecoveryResponse:
    institution_id = _require_institution_id(x_institution_id)
    requester_id = x_actor_id or "investigator_user"
    requester_role = x_actor_role or "INVESTIGATOR"

    recovery_req = await service.create_recovery_request(
        case_id=case_id,
        institution_id=institution_id,
        payload=payload,
        requester_id=requester_id,
        requester_role=requester_role,
    )
    return RecoveryResponse.model_validate(recovery_req)


@router.get(
    "/{case_id}/recovery-requests",
    response_model=RecoveryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List recovery requests for this case",
    description="Retrieve all recovery requests linked to this investigation case.",
)
async def list_case_recovery_requests(
    case_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_institution_id: Annotated[uuid.UUID | None, Header(alias="X-Institution-ID")] = None,
    service: RecoveryService = Depends(get_recovery_service),
) -> RecoveryListResponse:
    institution_id = _require_institution_id(x_institution_id)

    items, total = await service.list_by_case(
        case_id=case_id,
        institution_id=institution_id,
        limit=limit,
        offset=offset,
    )
    page_number = (offset // limit) + 1 if limit > 0 else 1
    return RecoveryListResponse(
        items=[RecoveryResponse.model_validate(r) for r in items],
        total=total,
        page=page_number,
        page_size=limit,
    )

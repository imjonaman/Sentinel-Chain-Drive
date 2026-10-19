"""API endpoints for Deterministic Policy Engine evaluation, step-up approvals,
holds, and policy governance.
"""

import uuid

from fastapi import APIRouter, Depends, Header, Query, status

from sentinel_chain_drive.api.deps import get_policy_service
from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.schemas.policy import (
    HoldResolutionRequest,
    PolicyCreate,
    PolicyDecisionResponse,
    PolicyEvaluationDetailResponse,
    PolicyEvaluationRequest,
    PolicyListResponse,
    PolicyResponse,
    StepUpChallengeResponse,
    StepUpCompletionRequest,
    TransactionHoldResponse,
)
from sentinel_chain_drive.services.policy_service import PolicyService

router = APIRouter(prefix="/policies", tags=["Policy Engine"])


def _check_institution_boundary(
    path_or_req_institution_id: uuid.UUID | None, header_institution_id: uuid.UUID | None
) -> None:
    """Enforce multi-tenant isolation header."""
    if (
        header_institution_id is not None
        and path_or_req_institution_id is not None
        and header_institution_id != path_or_req_institution_id
    ):
        raise AppException(
            message="Header X-Institution-ID does not match institution ID in request.",
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="CROSS_INSTITUTION_ACCESS_FORBIDDEN",
        )


# -----------------------------------------------------------------------------
# Policy Evaluation
# -----------------------------------------------------------------------------


@router.post(
    "/evaluate",
    response_model=PolicyDecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate transaction authorization request",
    description=(
        "Executes the deterministic policy evaluation pipeline across security credentials, "
        "account restrictions, capability limits, and institutional policies, returning "
        "exactly one outcome: ALLOW, STEP_UP, HOLD, or DECLINE."
    ),
)
async def evaluate_transaction_policy(
    data: PolicyEvaluationRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyDecisionResponse:
    _check_institution_boundary(data.institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "policy_client"
    return await policy_service.evaluate_transaction_policy(
        req=data,
        actor=actor,
        correlation_id=x_correlation_id,
    )


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=PolicyDecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get policy evaluation decision",
    description="Retrieve a previously recorded policy decision by internal reference ID.",
)
async def get_evaluation_decision(
    evaluation_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyDecisionResponse:
    return await policy_service.get_evaluation_decision(
        evaluation_id=evaluation_id,
        institution_id=x_institution_id,
    )


@router.get(
    "/evaluations/{evaluation_id}/detail",
    response_model=PolicyEvaluationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full evaluation diagnostic evidence",
    description=(
        "Retrieve full internal audit evidence, triggered rule identifiers, and threshold "
        "parameters for authorized compliance and fraud investigators."
    ),
)
async def get_evaluation_detail(
    evaluation_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyEvaluationDetailResponse:
    return await policy_service.get_evaluation_detail(
        evaluation_id=evaluation_id,
        institution_id=x_institution_id,
    )


# -----------------------------------------------------------------------------
# Step-Up Verification Workflow
# -----------------------------------------------------------------------------


@router.get(
    "/step-up/{challenge_id}",
    response_model=StepUpChallengeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get step-up challenge details",
    description="Retrieve status and requirements for a pending step-up verification challenge.",
)
async def get_step_up_challenge(
    challenge_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> StepUpChallengeResponse:
    return await policy_service.get_step_up_challenge(
        challenge_id=challenge_id,
        institution_id=x_institution_id,
    )


@router.post(
    "/step-up/{challenge_id}/complete",
    response_model=StepUpChallengeResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete step-up challenge",
    description=(
        "Submit supervisor or dual-control decision (APPROVED or REJECTED) to resolve a "
        "step-up verification challenge. Enforces separation of duties and intent binding."
    ),
)
async def complete_step_up_challenge(
    challenge_id: uuid.UUID,
    data: StepUpCompletionRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> StepUpChallengeResponse:
    actor = f"institution_{x_institution_id}" if x_institution_id else "supervisor"
    return await policy_service.complete_step_up(
        challenge_id=challenge_id,
        data=data,
        institution_id=x_institution_id,
        actor=actor,
    )


# -----------------------------------------------------------------------------
# Transaction Hold Workflow
# -----------------------------------------------------------------------------


@router.get(
    "/holds/{hold_id}",
    response_model=TransactionHoldResponse,
    status_code=status.HTTP_200_OK,
    summary="Get transaction hold details",
    description="Retrieve details for an active review hold.",
)
async def get_transaction_hold(
    hold_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> TransactionHoldResponse:
    return await policy_service.get_transaction_hold(
        hold_id=hold_id,
        institution_id=x_institution_id,
    )


@router.post(
    "/holds/{hold_id}/resolve",
    response_model=TransactionHoldResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve transaction hold",
    description=(
        "Resolve a transaction hold (RELEASE or CONFIRM_DECLINE) with authorized "
        "analyst case notes."
    ),
)
async def resolve_transaction_hold(
    hold_id: uuid.UUID,
    data: HoldResolutionRequest,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> TransactionHoldResponse:
    actor = f"institution_{x_institution_id}" if x_institution_id else "fraud_analyst"
    return await policy_service.resolve_transaction_hold(
        hold_id=hold_id,
        data=data,
        institution_id=x_institution_id,
        actor=actor,
    )


# -----------------------------------------------------------------------------
# Policy Configuration Governance
# -----------------------------------------------------------------------------


@router.post(
    "",
    response_model=PolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create and activate a versioned policy",
    description=(
        "Register a new versioned authorization policy. If an active policy exists for the same "
        "policy code and institution, it is superseded and automatically deactivated."
    ),
)
async def create_policy(
    data: PolicyCreate,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyResponse:
    _check_institution_boundary(data.institution_id, x_institution_id)
    actor = f"institution_{x_institution_id}" if x_institution_id else "security_admin"
    return await policy_service.create_policy(data=data, actor=actor)


@router.get(
    "",
    response_model=PolicyListResponse,
    status_code=status.HTTP_200_OK,
    summary="List versioned policies",
    description="Retrieve a paginated list of active and archived policies.",
)
async def list_policies(
    institution_id: uuid.UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyListResponse:
    effective_inst = x_institution_id if x_institution_id is not None else institution_id
    return await policy_service.list_policies(
        limit=limit,
        offset=offset,
        institution_id=effective_inst,
        is_active=is_active,
    )


@router.get(
    "/{policy_id}",
    response_model=PolicyResponse,
    status_code=status.HTTP_200_OK,
    summary="Get policy metadata and rules",
    description="Retrieve exact configuration for a policy version by ID.",
)
async def get_policy(
    policy_id: uuid.UUID,
    x_institution_id: uuid.UUID | None = Header(default=None, alias="X-Institution-ID"),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyResponse:
    pol = await policy_service.get_policy(policy_id)
    _check_institution_boundary(pol.institution_id, x_institution_id)
    return pol

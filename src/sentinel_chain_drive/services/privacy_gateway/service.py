"""Privacy Gateway Service orchestration.

Coordinates outbound indicator publication, sanitized alert sharing,
anti-enumeration query processing, pseudonym handling, inbound indicator validation,
and comprehensive privacy audit logging.
"""

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.privacy import compute_mesh_id
from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    DetectorType,
)
from sentinel_chain_drive.db.models.drunix_outbox import DrunixEventType
from sentinel_chain_drive.db.models.privacy_audit import (
    PrivacyAction,
    PrivacyOutcome,
)
from sentinel_chain_drive.db.models.shared_indicator import (
    IndicatorSeverity,
    IndicatorStatus,
    IndicatorType,
    SharedIndicator,
)
from sentinel_chain_drive.repositories.account_repository import AccountRepository
from sentinel_chain_drive.repositories.alert_repository import AlertRepository
from sentinel_chain_drive.repositories.drunix_outbox_repository import DrunixOutboxRepository
from sentinel_chain_drive.repositories.institution_repository import (
    InstitutionRepository,
)
from sentinel_chain_drive.repositories.privacy_repository import (
    PrivacyAuditRepository,
    SharedIndicatorRepository,
)
from sentinel_chain_drive.schemas.privacy import (
    IndicatorRevocationRequest,
    MeshIDQueryRequest,
    PrivacyAuditEventResponse,
    PrivacyAuditSummaryResponse,
    SharedIndicatorListResponse,
    SharedIndicatorPublishFromAlertRequest,
    SharedIndicatorPublishRequest,
    SharedIndicatorResponse,
)
from sentinel_chain_drive.services.privacy_gateway.disclosure import DataDisclosurePolicy
from sentinel_chain_drive.services.privacy_gateway.inbound_validator import (
    InboundIndicatorValidator,
)
from sentinel_chain_drive.services.privacy_gateway.rate_limiter import (
    PrivacyQueryRateLimiter,
)

logger = logging.getLogger(__name__)


# Global singleton rate limiter across requests
default_privacy_rate_limiter = PrivacyQueryRateLimiter()


class PrivacyGatewayService:
    """Orchestrates cross-institution privacy-preserving intelligence sharing."""

    def __init__(
        self,
        session: AsyncSession,
        indicator_repo: SharedIndicatorRepository | None = None,
        audit_repo: PrivacyAuditRepository | None = None,
        alert_repo: AlertRepository | None = None,
        institution_repo: InstitutionRepository | None = None,
        account_repo: AccountRepository | None = None,
        rate_limiter: PrivacyQueryRateLimiter | None = None,
    ) -> None:
        self.session = session
        self.indicator_repo = indicator_repo or SharedIndicatorRepository(session)
        self.audit_repo = audit_repo or PrivacyAuditRepository(session)
        self.alert_repo = alert_repo or AlertRepository(session)
        self.institution_repo = institution_repo or InstitutionRepository(session)
        self.account_repo = account_repo or AccountRepository(session)
        self.rate_limiter = rate_limiter or default_privacy_rate_limiter

    async def publish_indicator(
        self,
        request: SharedIndicatorPublishRequest,
        caller_institution_id: uuid.UUID,
        actor: str = "SIMULATED_INSTITUTION",
        correlation_id: str | None = None,
    ) -> SharedIndicatorResponse:
        """Publish a pre-sanitized fraud indicator directly.

        Enforces:
        - Inbound validation rules (schema, MeshID format, confidence, allowlist).
        - Idempotent database persistence.
        - Privacy audit record creation.
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=request.validity_hours)

        # Inbound validation
        try:
            InboundIndicatorValidator.validate_inbound_indicator(
                pseudonymous_mesh_id=request.pseudonymous_mesh_id,
                indicator_type=request.indicator_type,
                severity=request.severity,
                confidence_score=request.confidence_score,
                pattern_category=request.pattern_category,
                evidence_summary=request.evidence_summary,
                expires_at=expires_at,
                schema_version="v1.0",
                now=now,
            )
        except ValueError as e:
            await self.audit_repo.record_event(
                institution_id=caller_institution_id,
                actor=actor,
                action=PrivacyAction.REJECT,
                outcome=PrivacyOutcome.VALIDATION_FAILED,
                pseudonymous_mesh_id=request.pseudonymous_mesh_id,
                details={"validation_error": str(e)},
                correlation_id=correlation_id,
            )
            await self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Indicator validation failed: {e}",
            ) from e

        # Stamp verified caller identity into provenance to prevent origin forging
        provenance_data = dict(request.provenance)
        provenance_data["originating_institution_id"] = str(caller_institution_id)
        provenance_data["submitter_actor"] = actor
        provenance_data["submission_timestamp"] = now.isoformat()

        # Generate unique indicator code
        code_suffix = uuid.uuid4().hex[:12].upper()
        date_str = now.strftime("%Y%m%d")
        indicator_code = f"IND-{date_str}-{code_suffix}"

        indicator = SharedIndicator(
            indicator_code=indicator_code,
            schema_version="v1.0",
            pseudonymous_mesh_id=request.pseudonymous_mesh_id,
            originating_institution_id=caller_institution_id,
            target_institution_id=request.target_institution_id,
            indicator_type=request.indicator_type,
            severity=request.severity,
            confidence_score=request.confidence_score,
            pattern_category=request.pattern_category,
            evidence_summary=request.evidence_summary,
            provenance=provenance_data,
            sharing_policy_version=request.sharing_policy_version,
            status=IndicatorStatus.ACTIVE,
            expires_at=expires_at,
        )

        try:
            persisted, is_new = await self.indicator_repo.publish_idempotent(indicator)

            await self.audit_repo.record_event(
                institution_id=caller_institution_id,
                actor=actor,
                action=PrivacyAction.PUBLISH,
                outcome=PrivacyOutcome.SUCCESS,
                pseudonymous_mesh_id=request.pseudonymous_mesh_id,
                indicator_id=persisted.id,
                details={
                    "is_created": is_new,
                    "indicator_type": persisted.indicator_type.value,
                    "severity": persisted.severity.value,
                    "target_institution_id": (
                        str(request.target_institution_id)
                        if request.target_institution_id
                        else None
                    ),
                },
                correlation_id=correlation_id,
            )
            if is_new:
                outbox_repo = DrunixOutboxRepository(self.session)
                outbox_payload = {
                    "indicator_id": str(persisted.id),
                    "indicator_code": persisted.indicator_code,
                    "pseudonymous_mesh_id": persisted.pseudonymous_mesh_id,
                    "indicator_type": persisted.indicator_type.value,
                    "severity": persisted.severity.value,
                    "originating_institution_id": str(caller_institution_id),
                }
                commitment_hash = hashlib.sha256(
                    f"{persisted.id}:{persisted.pseudonymous_mesh_id}:{persisted.indicator_type.value}".encode()
                ).hexdigest()
                await outbox_repo.create_event(
                    institution_id=caller_institution_id,
                    event_type=DrunixEventType.FRAUD_INDICATOR,
                    aggregate_type="SHARED_INDICATOR",
                    aggregate_id=persisted.id,
                    idempotency_key=f"drunix:indicator:{persisted.id}",
                    commitment_hash=commitment_hash,
                    payload=outbox_payload,
                    correlation_id=correlation_id,
                )

            await self.session.commit()
            return SharedIndicatorResponse.model_validate(persisted)

        except ValueError as val_err:
            await self.session.rollback()
            await self.audit_repo.record_event(
                institution_id=caller_institution_id,
                actor=actor,
                action=PrivacyAction.PUBLISH,
                outcome=PrivacyOutcome.DENIED,
                pseudonymous_mesh_id=request.pseudonymous_mesh_id,
                details={"conflict_error": str(val_err)},
                correlation_id=correlation_id,
            )
            await self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(val_err),
            ) from val_err
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to persist shared indicator: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error during indicator publication",
            ) from e

    async def publish_from_alert(
        self,
        request: SharedIndicatorPublishFromAlertRequest,
        caller_institution_id: uuid.UUID,
        actor: str = "SIMULATED_INSTITUTION",
        correlation_id: str | None = None,
    ) -> SharedIndicatorResponse:
        """Sanitize an internal MuleChain alert and publish as a SharedIndicator."""
        alert = await self.alert_repo.get_by_id_scoped(
            alert_id=request.alert_id,
            institution_id=caller_institution_id,
        )

        if not alert:
            await self.audit_repo.record_event(
                institution_id=caller_institution_id,
                actor=actor,
                action=PrivacyAction.REJECT,
                outcome=PrivacyOutcome.DENIED,
                details={"reason": "MuleChain alert not found or access denied"},
                correlation_id=correlation_id,
            )
            await self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Referenced MuleChain alert not found within institution scope",
            )

        # Validate account ownership if associated with the alert
        inst_code = "UNKNOWN_BANK"
        if alert.primary_account_id:
            account = await self.account_repo.get_by_id(alert.primary_account_id)
            if account:
                if account.account_number != request.account_number:
                    await self.audit_repo.record_event(
                        institution_id=caller_institution_id,
                        actor=actor,
                        action=PrivacyAction.REJECT,
                        outcome=PrivacyOutcome.VALIDATION_FAILED,
                        details={
                            "reason": ("Account number does not match primary account on alert")
                        },
                        correlation_id=correlation_id,
                    )
                    await self.session.commit()
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Account number does not match primary account associated with alert"
                        ),
                    )
                acct_inst = await self.institution_repo.get_by_id(account.institution_id)
                if acct_inst:
                    inst_code = acct_inst.institution_code

        if inst_code == "UNKNOWN_BANK":
            # Retrieve caller institution to get institution_code for MeshID
            inst = await self.institution_repo.get_by_id(caller_institution_id)
            inst_code = inst.institution_code if inst else "UNKNOWN_BANK"

        # Deterministically compute MeshID for purpose FRAUD_SHARING
        mesh_id = compute_mesh_id(
            institution_code=inst_code,
            account_number=request.account_number,
            purpose="FRAUD_SHARING",
        )

        # Sanitize evidence using field-level disclosure policy
        sanitized_evidence = DataDisclosurePolicy.sanitize_mulechain_alert(alert)

        # Map detector to indicator type
        detector_type_map = {
            DetectorType.FAN_IN: IndicatorType.MULE_BURST_INGRESS,
            DetectorType.FAN_OUT: IndicatorType.MULE_FAN_OUT,
            DetectorType.RAPID_PASSTHROUGH: IndicatorType.MULE_RAPID_PASSTHROUGH,
            DetectorType.CIRCULAR_LAYERING: IndicatorType.MULE_CIRCULAR_LAYERING,
        }

        indicator_type = detector_type_map.get(
            alert.detector_type, IndicatorType.SUSPICIOUS_MULE_ACCOUNT
        )

        # Map alert severity to indicator severity
        severity_map = {
            AlertSeverity.LOW: IndicatorSeverity.LOW,
            AlertSeverity.MEDIUM: IndicatorSeverity.MEDIUM,
            AlertSeverity.HIGH: IndicatorSeverity.HIGH,
            AlertSeverity.CRITICAL: IndicatorSeverity.CRITICAL,
        }
        indicator_severity = severity_map.get(alert.severity, IndicatorSeverity.MEDIUM)

        confidence_score = round(float(alert.risk_score) / 100.0, 2)

        provenance = {
            "source_type": "MULECHAIN_DETECTOR",
            "detector_type": alert.detector_type.value,
            "scoring_model_version": alert.scoring_model_version,
            "detection_rule_version": alert.detection_rule_version,
            "origin_timestamp": alert.created_at.isoformat(),
        }

        publish_req = SharedIndicatorPublishRequest(
            pseudonymous_mesh_id=mesh_id,
            indicator_type=indicator_type,
            severity=indicator_severity,
            confidence_score=confidence_score,
            pattern_category=f"TOPOLOGICAL_{alert.detector_type.value}",
            evidence_summary=sanitized_evidence,
            provenance=provenance,
            target_institution_id=request.target_institution_id,
            validity_hours=request.validity_hours,
            sharing_policy_version="v1.0",
        )

        return await self.publish_indicator(
            request=publish_req,
            caller_institution_id=caller_institution_id,
            actor=actor,
            correlation_id=correlation_id,
        )

    async def query_by_mesh_id(
        self,
        request: MeshIDQueryRequest,
        caller_institution_id: uuid.UUID,
        actor: str = "SIMULATED_INSTITUTION",
        correlation_id: str | None = None,
    ) -> SharedIndicatorListResponse:
        """Query indicators by specific MeshID with anti-enumeration protection."""
        # Anti-enumeration rate limit check
        inst_str = str(caller_institution_id)
        is_allowed, remaining = self.rate_limiter.is_allowed(inst_str)
        if not is_allowed:
            await self.audit_repo.record_event(
                institution_id=caller_institution_id,
                actor=actor,
                action=PrivacyAction.QUERY,
                outcome=PrivacyOutcome.DENIED,
                pseudonymous_mesh_id=request.pseudonymous_mesh_id,
                details={"reason": "Anti-enumeration query rate limit exceeded"},
                correlation_id=correlation_id,
            )
            await self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Anti-enumeration query rate limit exceeded for institution",
            )

        try:
            indicators, total = await self.indicator_repo.query_by_mesh_id(
                pseudonymous_mesh_id=request.pseudonymous_mesh_id,
                caller_institution_id=caller_institution_id,
                limit=request.limit,
                offset=request.offset,
            )

            await self.audit_repo.record_event(
                institution_id=caller_institution_id,
                actor=actor,
                action=PrivacyAction.QUERY,
                outcome=PrivacyOutcome.SUCCESS,
                pseudonymous_mesh_id=request.pseudonymous_mesh_id,
                details={
                    "results_returned": len(indicators),
                    "total_matched": total,
                    "purpose": request.purpose,
                    "remaining_quota": remaining,
                },
                correlation_id=correlation_id,
            )
            await self.session.commit()

            items = [SharedIndicatorResponse.model_validate(ind) for ind in indicators]
            return SharedIndicatorListResponse(
                items=items,
                total=total,
                limit=request.limit,
                offset=request.offset,
            )
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to execute mesh_id query: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error during indicator query",
            ) from e

    async def revoke_indicator(
        self,
        indicator_id: uuid.UUID,
        request: IndicatorRevocationRequest,
        caller_institution_id: uuid.UUID,
        actor: str = "SIMULATED_INSTITUTION",
        correlation_id: str | None = None,
    ) -> SharedIndicatorResponse:
        """Revoke a previously published indicator.

        Only the originating institution can revoke an indicator.
        """
        indicator = await self.indicator_repo.get_by_id_scoped(
            indicator_id=indicator_id,
            caller_institution_id=caller_institution_id,
        )

        if not indicator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Indicator not found or access denied",
            )

        if indicator.originating_institution_id != caller_institution_id:
            await self.audit_repo.record_event(
                institution_id=caller_institution_id,
                actor=actor,
                action=PrivacyAction.REVOKE,
                outcome=PrivacyOutcome.DENIED,
                indicator_id=indicator_id,
                details={"reason": "Cannot revoke indicator originating from another institution"},
                correlation_id=correlation_id,
            )
            await self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the originating institution may revoke this indicator",
            )

        try:
            revoked = await self.indicator_repo.revoke_indicator(
                indicator_id=indicator_id,
                originating_institution_id=caller_institution_id,
                reason=request.reason,
            )

            if not revoked:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Indicator could not be revoked",
                )

            await self.audit_repo.record_event(
                institution_id=caller_institution_id,
                actor=actor,
                action=PrivacyAction.REVOKE,
                outcome=PrivacyOutcome.SUCCESS,
                indicator_id=indicator.id,
                pseudonymous_mesh_id=indicator.pseudonymous_mesh_id,
                details={"revocation_reason": request.reason},
                correlation_id=correlation_id,
            )
            await self.session.commit()

            return SharedIndicatorResponse.model_validate(revoked)
        except HTTPException:
            await self.session.rollback()
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to revoke shared indicator: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error during indicator revocation",
            ) from e

    async def get_indicator(
        self,
        indicator_id: uuid.UUID,
        caller_institution_id: uuid.UUID,
    ) -> SharedIndicatorResponse:
        """Retrieve a specific shared indicator if authorized for caller."""
        indicator = await self.indicator_repo.get_by_id_scoped(
            indicator_id=indicator_id,
            caller_institution_id=caller_institution_id,
        )

        if not indicator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Indicator not found or access denied",
            )

        return SharedIndicatorResponse.model_validate(indicator)

    async def get_audit_summary(
        self,
        institution_id: uuid.UUID,
    ) -> PrivacyAuditSummaryResponse:
        """Retrieve audit event counts and recent audit logs for an institution."""
        counts = await self.audit_repo.get_summary_counts(institution_id)
        recent_logs, _ = await self.audit_repo.list_for_institution(
            institution_id=institution_id,
            limit=20,
        )

        events = [PrivacyAuditEventResponse.model_validate(log) for log in recent_logs]

        return PrivacyAuditSummaryResponse(
            institution_id=institution_id,
            published_count=counts.get("published_count", 0),
            queried_count=counts.get("queried_count", 0),
            revoked_count=counts.get("revoked_count", 0),
            recent_events=events,
        )

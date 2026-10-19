"""Deterministic policy evaluation engine.

Implements explicit rule precedence without non-deterministic side-effects or external LLMs.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sentinel_chain_drive.db.models.account import Account, AccountStatus
from sentinel_chain_drive.db.models.agent import Agent, AgentStatus
from sentinel_chain_drive.db.models.capability import Capability
from sentinel_chain_drive.db.models.institution import Institution, InstitutionStatus
from sentinel_chain_drive.db.models.policy import Policy
from sentinel_chain_drive.db.models.policy_evaluation import PolicyOutcome
from sentinel_chain_drive.schemas.credential import TransactionIntent
from sentinel_chain_drive.schemas.policy import RiskSignals


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Normalize datetime to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass
class PolicyEvaluationResult:
    """Deterministic evaluation outcome, triggered rules, and diagnostic evidence."""

    outcome: PolicyOutcome
    reason_codes: list[str]
    applicable_rule_ids: list[str]
    evidence: dict[str, Any] = field(default_factory=dict)
    step_up_required: bool = False
    step_up_reason: str | None = None
    step_up_role: str = "SUPERVISOR"
    verification_type: str = "SUPERVISOR_APPROVAL"
    hold_required: bool = False
    hold_reason: str | None = None
    hold_workflow: str = "FRAUD_INVESTIGATION"
    matched_capability_id: str | None = None


class DeterministicPolicyEngine:
    """Evaluates transaction authorization requests against configured policies and rules."""

    def evaluate(
        self,
        policy: Policy,
        agent: Agent,
        capabilities: list[Capability],
        transaction: TransactionIntent,
        origin_institution: Institution | None,
        origin_account: Account | None,
        destination_account: Account | None,
        spend_24h: Decimal,
        active_reservations_amount: Decimal,
        risk_signals: RiskSignals,
        evaluation_time: datetime,
        credential_check_passed: bool,
        credential_reasons: list[str],
    ) -> PolicyEvaluationResult:
        """Evaluate authorization inputs deterministically.

        Precedence Hierarchy:
        1. Hard Security Violations (credential / signature / agent status) -> DECLINE
        2. Account and Institution Restrictions (frozen, closed, inactive)  -> DECLINE
        3. Capability Envelope Limits (amount, 24h spend, window, whitelist) -> DECLINE
        4. Institutional Policy Caps (max cap, disallowed currency/purpose) -> DECLINE
        5. Hold Triggers (high risk score, velocity anomaly, manual review) -> HOLD
        6. Step-Up Triggers (dual-control threshold, medium risk score)     -> STEP_UP
        7. Default Rule (all conditions satisfied)                         -> ALLOW
        """
        now = ensure_utc(evaluation_time) or datetime.now(UTC)
        evidence: dict[str, Any] = {
            "policy_id": str(policy.id),
            "policy_code": policy.policy_code,
            "policy_version": policy.version,
            "agent_id": str(agent.id),
            "agent_status": agent.status.value,
            "amount": str(transaction.amount),
            "currency": transaction.currency,
            "spend_24h": str(spend_24h),
            "active_reservations": str(active_reservations_amount),
            "risk_score": risk_signals.risk_score,
            "evaluated_at": now.isoformat(),
        }

        # ---------------------------------------------------------------------
        # Priority 1: Security & Credential Verification
        # ---------------------------------------------------------------------
        if not credential_check_passed:
            rule_id = "RULE_SEC_001_CREDENTIAL_VERIFICATION"
            evidence["rejection_stage"] = "CREDENTIAL_VERIFICATION"
            evidence["credential_reasons"] = credential_reasons
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=credential_reasons or ["CREDENTIAL_VERIFICATION_FAILED"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        if agent.status != AgentStatus.ACTIVE:
            rule_id = "RULE_SEC_002_AGENT_STATUS"
            evidence["rejection_stage"] = "AGENT_INACTIVE"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=[f"AGENT_NOT_ACTIVE_{agent.status.value}"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        # ---------------------------------------------------------------------
        # Priority 2: Account and Institution Status Restrictions
        # ---------------------------------------------------------------------
        if origin_institution is None or origin_institution.status != InstitutionStatus.ACTIVE:
            rule_id = "RULE_ACC_001_INSTITUTION_STATUS"
            status_desc = origin_institution.status.value if origin_institution else "NOT_FOUND"
            evidence["rejection_stage"] = "INSTITUTION_INACTIVE"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=[f"ORIGIN_INSTITUTION_NOT_ACTIVE_{status_desc}"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        if origin_account is None:
            rule_id = "RULE_ACC_002_ACCOUNT_RESTRICTION"
            evidence["rejection_stage"] = "ORIGIN_ACCOUNT_NOT_FOUND"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=["ORIGIN_ACCOUNT_NOT_FOUND"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        if origin_account.status in (AccountStatus.FROZEN, AccountStatus.CLOSED):
            rule_id = "RULE_ACC_002_ACCOUNT_RESTRICTION"
            evidence["rejection_stage"] = f"ORIGIN_ACCOUNT_{origin_account.status.value}"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=[f"ORIGIN_ACCOUNT_{origin_account.status.value}"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        if origin_account.currency != transaction.currency:
            rule_id = "RULE_ACC_002_ACCOUNT_RESTRICTION"
            evidence["rejection_stage"] = "ORIGIN_ACCOUNT_CURRENCY_MISMATCH"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=["ORIGIN_ACCOUNT_CURRENCY_MISMATCH"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        if destination_account is not None:
            if destination_account.status in (AccountStatus.FROZEN, AccountStatus.CLOSED):
                rule_id = "RULE_ACC_002_ACCOUNT_RESTRICTION"
                evidence["rejection_stage"] = (
                    f"DESTINATION_ACCOUNT_{destination_account.status.value}"
                )
                return PolicyEvaluationResult(
                    outcome=PolicyOutcome.DECLINE,
                    reason_codes=[f"DESTINATION_ACCOUNT_{destination_account.status.value}"],
                    applicable_rule_ids=[rule_id],
                    evidence=evidence,
                )
            if destination_account.currency != transaction.currency:
                rule_id = "RULE_ACC_002_ACCOUNT_RESTRICTION"
                evidence["rejection_stage"] = "DESTINATION_ACCOUNT_CURRENCY_MISMATCH"
                return PolicyEvaluationResult(
                    outcome=PolicyOutcome.DECLINE,
                    reason_codes=["DESTINATION_ACCOUNT_CURRENCY_MISMATCH"],
                    applicable_rule_ids=[rule_id],
                    evidence=evidence,
                )

        # ---------------------------------------------------------------------
        # Priority 3: Capability Envelope Evaluation
        # ---------------------------------------------------------------------
        if not capabilities:
            rule_id = "RULE_CAP_001_ACTIVE_CAPABILITIES"
            evidence["rejection_stage"] = "NO_ACTIVE_CAPABILITIES"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=["NO_ACTIVE_CAPABILITIES"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        total_velocity = spend_24h + active_reservations_amount + transaction.amount
        evidence["projected_total_velocity"] = str(total_velocity)

        matched_cap: Capability | None = None
        cap_violations: list[str] = []

        for cap in capabilities:
            cap_from = ensure_utc(cap.valid_from) or now
            cap_until = ensure_utc(cap.valid_until) or now
            if now < cap_from or now > cap_until:
                cap_violations.append(f"CAPABILITY_EXPIRED: '{cap.name}'")
                continue

            if cap.operating_start_hour_utc is not None and cap.operating_end_hour_utc is not None:
                current_hour = now.hour
                if not (cap.operating_start_hour_utc <= current_hour <= cap.operating_end_hour_utc):
                    cap_violations.append(
                        f"OPERATING_WINDOW_OUT_OF_BOUNDS: hour {current_hour} outside "
                        f"[{cap.operating_start_hour_utc}, {cap.operating_end_hour_utc}]"
                    )
                    continue

            if transaction.transaction_type not in cap.permitted_transaction_types:
                cap_violations.append(
                    f"DISALLOWED_TRANSACTION_TYPE: '{transaction.transaction_type}'"
                )
                continue

            if transaction.currency not in cap.permitted_currencies:
                cap_violations.append(f"DISALLOWED_CURRENCY: '{transaction.currency}'")
                continue

            if transaction.amount > cap.max_amount_per_transaction:
                cap_violations.append(
                    f"AMOUNT_EXCEEDS_SINGLE_LIMIT: amount {transaction.amount} "
                    f"> {cap.max_amount_per_transaction}"
                )
                continue

            if total_velocity > cap.max_daily_cumulative_amount:
                cap_violations.append(
                    f"CAPABILITY_DAILY_LIMIT_EXCEEDED: projected {total_velocity} "
                    f"> {cap.max_daily_cumulative_amount}"
                )
                continue

            if cap.allowed_origin_accounts is not None and (
                transaction.origin_account_number not in cap.allowed_origin_accounts
            ):
                cap_violations.append(
                    f"ORIGIN_ACCOUNT_NOT_WHITELISTED: '{transaction.origin_account_number}'"
                )
                continue

            if cap.allowed_destination_accounts is not None and (
                transaction.destination_account_number not in cap.allowed_destination_accounts
            ):
                cap_violations.append(
                    f"DESTINATION_ACCOUNT_NOT_WHITELISTED: "
                    f"'{transaction.destination_account_number}'"
                )
                continue

            if (
                cap.purpose_codes is not None
                and transaction.purpose_code is not None
                and transaction.purpose_code not in cap.purpose_codes
            ):
                cap_violations.append(f"PURPOSE_CODE_NOT_PERMITTED: '{transaction.purpose_code}'")
                continue

            # Satisfies all capability constraints
            matched_cap = cap
            break

        if matched_cap is None:
            rule_id = "RULE_CAP_002_ENVELOPE_BREACH"
            evidence["rejection_stage"] = "CAPABILITY_LIMITS_EXCEEDED"
            evidence["capability_violations"] = cap_violations
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=cap_violations or ["CAPABILITY_LIMITS_EXCEEDED"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        evidence["matched_capability_id"] = str(matched_cap.id)

        # ---------------------------------------------------------------------
        # Priority 4: Institutional Policy Hard Limits
        # ---------------------------------------------------------------------
        policy_rules = policy.rules or {}
        max_tx_amount = policy_rules.get("max_transaction_amount")
        if max_tx_amount is not None:
            max_limit = Decimal(str(max_tx_amount))
            if transaction.amount > max_limit:
                rule_id = "RULE_POL_001_MAX_TRANSACTION_CAP"
                evidence["rejection_stage"] = "POLICY_MAX_TRANSACTION_CAP"
                evidence["policy_max_amount"] = str(max_limit)
                return PolicyEvaluationResult(
                    outcome=PolicyOutcome.DECLINE,
                    reason_codes=["POLICY_MAX_TRANSACTION_AMOUNT_EXCEEDED"],
                    applicable_rule_ids=[rule_id],
                    evidence=evidence,
                )

        pol_currencies = policy_rules.get("allowed_currencies")
        if pol_currencies and transaction.currency not in pol_currencies:
            rule_id = "RULE_POL_002_CURRENCY_RESTRICTION"
            evidence["rejection_stage"] = "POLICY_CURRENCY_DISALLOWED"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=["POLICY_CURRENCY_NOT_PERMITTED"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        pol_purposes = policy_rules.get("allowed_purpose_codes")
        if (
            pol_purposes
            and transaction.purpose_code
            and transaction.purpose_code not in pol_purposes
        ):
            rule_id = "RULE_POL_003_PURPOSE_RESTRICTION"
            evidence["rejection_stage"] = "POLICY_PURPOSE_DISALLOWED"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.DECLINE,
                reason_codes=["POLICY_PURPOSE_NOT_PERMITTED"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
            )

        # ---------------------------------------------------------------------
        # Priority 5: Hold Triggers (Manual Investigation)
        # ---------------------------------------------------------------------
        hold_risk_threshold = float(policy_rules.get("hold_risk_threshold", 0.85))
        if risk_signals.risk_score is not None and risk_signals.risk_score >= hold_risk_threshold:
            rule_id = "RULE_RISK_001_HIGH_RISK_HOLD"
            evidence["hold_stage"] = "HIGH_RISK_SCORE"
            evidence["hold_risk_threshold"] = hold_risk_threshold
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.HOLD,
                reason_codes=["HOLD_HIGH_RISK_SCORE"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
                hold_required=True,
                hold_reason=(
                    f"Risk score {risk_signals.risk_score} >= threshold {hold_risk_threshold}"
                ),
                hold_workflow="FRAUD_INVESTIGATION",
                matched_capability_id=str(matched_cap.id),
            )

        if risk_signals.velocity_warning:
            rule_id = "RULE_RISK_002_VELOCITY_ANOMALY_HOLD"
            evidence["hold_stage"] = "VELOCITY_ANOMALY"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.HOLD,
                reason_codes=["HOLD_VELOCITY_ANOMALY"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
                hold_required=True,
                hold_reason="Rapid transaction velocity anomaly detected",
                hold_workflow="FRAUD_INVESTIGATION",
                matched_capability_id=str(matched_cap.id),
            )

        if risk_signals.manual_review_flag:
            rule_id = "RULE_RISK_003_MANUAL_REVIEW_HOLD"
            evidence["hold_stage"] = "MANUAL_REVIEW_FLAG"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.HOLD,
                reason_codes=["HOLD_MANUAL_REVIEW_REQUESTED"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
                hold_required=True,
                hold_reason="Explicit manual review flag attached to request",
                hold_workflow="COMPLIANCE_REVIEW",
                matched_capability_id=str(matched_cap.id),
            )

        # ---------------------------------------------------------------------
        # Priority 6: Step-Up Triggers (Dual-Control / Approval Required)
        # ---------------------------------------------------------------------
        step_up_threshold = policy_rules.get("step_up_threshold_amount")
        if step_up_threshold is not None:
            step_up_amount = Decimal(str(step_up_threshold))
            if transaction.amount >= step_up_amount:
                rule_id = "RULE_POL_004_DUAL_CONTROL_THRESHOLD"
                evidence["step_up_stage"] = "AMOUNT_THRESHOLD_REACHED"
                evidence["step_up_amount_threshold"] = str(step_up_amount)
                dual_roles = policy_rules.get("dual_control_roles", ["SUPERVISOR"])
                role = dual_roles[0] if dual_roles else "SUPERVISOR"
                return PolicyEvaluationResult(
                    outcome=PolicyOutcome.STEP_UP,
                    reason_codes=["STEP_UP_AMOUNT_THRESHOLD_REACHED"],
                    applicable_rule_ids=[rule_id],
                    evidence=evidence,
                    step_up_required=True,
                    step_up_reason=(
                        f"Transaction amount {transaction.amount} >= {step_up_amount} "
                        "requires dual control"
                    ),
                    step_up_role=role,
                    verification_type="SUPERVISOR_APPROVAL",
                    matched_capability_id=str(matched_cap.id),
                )

        step_up_risk_threshold = float(policy_rules.get("step_up_risk_threshold", 0.50))
        if (
            risk_signals.risk_score is not None
            and risk_signals.risk_score >= step_up_risk_threshold
        ):
            rule_id = "RULE_RISK_004_MEDIUM_RISK_STEP_UP"
            evidence["step_up_stage"] = "MEDIUM_RISK_SCORE"
            evidence["step_up_risk_threshold"] = step_up_risk_threshold
            dual_roles = policy_rules.get("dual_control_roles", ["SUPERVISOR"])
            role = dual_roles[0] if dual_roles else "SUPERVISOR"
            return PolicyEvaluationResult(
                outcome=PolicyOutcome.STEP_UP,
                reason_codes=["STEP_UP_MEDIUM_RISK_SCORE"],
                applicable_rule_ids=[rule_id],
                evidence=evidence,
                step_up_required=True,
                step_up_reason=(
                    f"Risk score {risk_signals.risk_score} >= {step_up_risk_threshold} "
                    "requires supervisor approval"
                ),
                step_up_role=role,
                verification_type="SUPERVISOR_APPROVAL",
                matched_capability_id=str(matched_cap.id),
            )

        # ---------------------------------------------------------------------
        # Priority 7: Default Permissive Rule (ALLOW)
        # ---------------------------------------------------------------------
        rule_id = "RULE_DEFAULT_ALLOW"
        evidence["evaluation_stage"] = "COMPLETED_PERMITTED"
        return PolicyEvaluationResult(
            outcome=PolicyOutcome.ALLOW,
            reason_codes=["POLICY_EVALUATION_PASSED"],
            applicable_rule_ids=[rule_id],
            evidence=evidence,
            matched_capability_id=str(matched_cap.id),
        )

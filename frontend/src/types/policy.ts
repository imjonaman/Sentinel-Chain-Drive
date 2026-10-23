export type PolicyOutcome = 'ALLOW' | 'STEP_UP' | 'HOLD' | 'DECLINE';

export interface PolicyRule {
  id: string;
  name: string;
  rule_type: string;
  parameters: Record<string, unknown>;
  priority: number;
  outcome_on_match: PolicyOutcome;
  is_active: boolean;
}

export interface Policy {
  id: string;
  institution_id?: string;
  policy_name: string;
  version: number;
  is_active: boolean;
  rules: PolicyRule[];
  created_at: string;
}

export interface StepUpChallenge {
  id: string;
  transaction_id: string;
  institution_id: string;
  initiating_agent_id?: string;
  transaction_intent_hash: string;
  challenge_reason: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED';
  expires_at: string;
  reviewed_by?: string;
  reviewed_at?: string;
  reviewer_notes?: string;
  created_at: string;
}

export interface TransactionHold {
  id: string;
  transaction_id: string;
  institution_id: string;
  hold_reason: string;
  status: 'ACTIVE' | 'RELEASED' | 'CONFIRMED_DECLINE';
  release_notes?: string;
  resolved_by?: string;
  resolved_at?: string;
  created_at: string;
}

export interface PolicyEvaluationResponse {
  decision_id: string;
  outcome: PolicyOutcome;
  reason_code: string;
  evaluation_timestamp: string;
  challenge_id?: string;
  hold_id?: string;
}

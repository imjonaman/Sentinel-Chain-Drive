export type CaseStatus = 
  | 'OPEN'
  | 'IN_REVIEW'
  | 'PENDING_RECOVERY'
  | 'CLOSED_FRAUD'
  | 'CLOSED_BENIGN'
  | 'REOPENED';

export type CaseSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export interface FraudCase {
  id: string;
  case_number: string;
  title: string;
  description?: string;
  severity: CaseSeverity;
  status: CaseStatus;
  primary_institution_id: string;
  assigned_investigator?: string;
  resolution_category?: string;
  resolution_notes?: string;
  created_at: string;
  updated_at: string;
}

export interface RecoveryRequest {
  id: string;
  case_id: string;
  request_code: string;
  origin_institution_id: string;
  counterparty_institution_id: string;
  action_type: 'ACCOUNT_FREEZE_REQUEST' | 'FUNDS_RECALL' | 'TRANSACTION_DISPUTE' | 'INFORMATION_REQUEST';
  status: 'INITIATED' | 'PENDING_APPROVAL' | 'ACKNOWLEDGED' | 'SUBMITTED' | 'RECALL_REQUESTED' | 'SETTLED' | 'REJECTED' | 'TIMED_OUT' | 'RECONCILED';
  requester_id: string;
  approver_id?: string;
  requested_amount?: string;
  currency: string;
  is_simulated: boolean;
  created_at: string;
  updated_at: string;
}

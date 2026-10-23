export type DetectorType = 
  | 'FAN_IN_SMURFING'
  | 'FAN_OUT_DISPERSAL'
  | 'RAPID_PASS_THROUGH'
  | 'CIRCULAR_LAYERING';

export type AlertSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type AlertStatus = 'NEW' | 'TRIAGED' | 'ESCALATED' | 'DISMISSED';

export interface FraudAlert {
  id: string;
  alert_code: string;
  detector_type: DetectorType;
  primary_account_id: string;
  primary_institution_id: string;
  currency: string;
  risk_score: number;
  severity: AlertSeverity;
  status: AlertStatus;
  evidence_data: Record<string, unknown>;
  involved_account_ids: string[];
  involved_transaction_ids: string[];
  analysis_window_start: string;
  analysis_window_end: string;
  created_at: string;
  updated_at: string;
}

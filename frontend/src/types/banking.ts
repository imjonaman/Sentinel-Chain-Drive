export interface Institution {
  id: string;
  institution_code: string;
  name: string;
  routing_identifier: string;
  country_code: string;
  status: 'ACTIVE' | 'SUSPENDED' | 'INACTIVE';
  settings?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Account {
  id: string;
  institution_id: string;
  account_number: string;
  account_type: 'CHECKING' | 'SAVINGS' | 'OPERATIONAL' | 'SETTLEMENT';
  currency: string;
  balance: string;
  status: 'ACTIVE' | 'FROZEN' | 'CLOSED';
  created_at: string;
  updated_at: string;
}

export type TransactionStatus = 
  | 'SUBMITTED'
  | 'PENDING_AUTHORIZATION'
  | 'AUTHORIZED'
  | 'HELD'
  | 'SETTLED'
  | 'REJECTED'
  | 'CANCELLED';

export interface Transaction {
  id: string;
  idempotency_key: string;
  origin_institution_id: string;
  origin_account_id: string;
  destination_institution_id: string;
  destination_account_id: string;
  amount: string;
  currency: string;
  transaction_type: string;
  purpose_code?: string;
  status: TransactionStatus;
  rejection_reason?: string;
  settled_at?: string;
  created_at: string;
  updated_at: string;
}

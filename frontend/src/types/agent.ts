export type AgentStatus = 'PENDING_APPROVAL' | 'ACTIVE' | 'SUSPENDED' | 'REVOKED' | 'EXPIRED';

export interface Agent {
  id: string;
  institution_id: string;
  name: string;
  description?: string;
  ed25519_public_key: string;
  key_version: number;
  status: AgentStatus;
  created_at: string;
  updated_at: string;
}

export interface CapabilityEnvelope {
  id: string;
  institution_id: string;
  agent_id: string;
  name?: string;
  description?: string;
  max_amount_per_transaction: string;
  max_daily_cumulative_amount: string;
  permitted_currencies?: string[];
  destination_account_whitelist?: string[];
  allowed_destination_accounts?: string[];
  operating_start_hour_utc: number;
  operating_end_hour_utc: number;
  is_active: boolean;
  version?: number;
  created_at?: string;
  updated_at?: string;
}


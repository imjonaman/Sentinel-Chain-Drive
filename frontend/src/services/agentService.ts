import { apiClient } from './api';
import { Agent, CapabilityEnvelope } from '../types/agent';

export const agentService = {
  getAgents: (institutionId: string) => {
    return apiClient<{ items: Agent[]; total: number }>(`/api/v1/institutions/${institutionId}/agents`, {
      institutionId,
    });
  },

  registerAgent: (institutionId: string, payload: {
    name: string;
    description?: string;
    ed25519_public_key: string;
    public_key?: string;
    owner_contact?: string;
  }) => {
    return apiClient<Agent>(`/api/v1/institutions/${institutionId}/agents`, {
      method: 'POST',
      institutionId,
      body: JSON.stringify({
        institution_id: institutionId,
        name: payload.name,
        description: payload.description,
        owner_contact: payload.owner_contact || 'security-admin@bank.internal',
        agent_type: 'AUTONOMOUS_PAYMENT_AGENT',
        public_key: payload.public_key || payload.ed25519_public_key,
        ed25519_public_key: payload.ed25519_public_key,
      }),
    });
  },

  updateAgentStatus: (institutionId: string, agentId: string, status: string, reason?: string) => {
    return apiClient<Agent>(`/api/v1/institutions/${institutionId}/agents/${agentId}/status`, {
      method: 'POST',
      institutionId,
      body: JSON.stringify({ status, reason: reason || 'Operator UI status change' }),
    });
  },

  rotateKey: (institutionId: string, agentId: string, newPublicKey: string) => {
    return apiClient<Agent>(`/api/v1/institutions/${institutionId}/agents/${agentId}/rotate-key`, {
      method: 'POST',
      institutionId,
      body: JSON.stringify({
        new_public_key: newPublicKey,
        new_ed25519_public_key: newPublicKey,
      }),
    });
  },

  getCapabilities: (institutionId: string, agentId?: string) => {
    const query = agentId ? `?agent_id=${agentId}` : '';
    return apiClient<{ items: CapabilityEnvelope[]; total: number }>(
      `/api/v1/institutions/${institutionId}/capabilities${query}`,
      { institutionId }
    );
  },

  assignCapability: (institutionId: string, payload: {
    agent_id: string;
    name?: string;
    max_amount_per_transaction: string;
    max_daily_cumulative_amount: string;
    permitted_currencies: string[];
    destination_account_whitelist?: string[];
    operating_start_hour_utc: number;
    operating_end_hour_utc: number;
  }) => {
    return apiClient<CapabilityEnvelope>(`/api/v1/institutions/${institutionId}/capabilities`, {
      method: 'POST',
      institutionId,
      body: JSON.stringify({
        agent_id: payload.agent_id,
        name: payload.name || 'Autonomous Envelope Limits',
        permitted_transaction_types: ['DOMESTIC_TRANSFER', 'INTERBANK_PAYMENT'],
        permitted_currencies: payload.permitted_currencies || ['USD'],
        max_amount_per_transaction: payload.max_amount_per_transaction,
        max_daily_cumulative_amount: payload.max_daily_cumulative_amount,
        allowed_destination_accounts: payload.destination_account_whitelist || [],
        operating_start_hour_utc: payload.operating_start_hour_utc,
        operating_end_hour_utc: payload.operating_end_hour_utc,
      }),
    });
  },

  updateCapability: (
    institutionId: string,
    capabilityId: string,
    payload: {
      max_amount_per_transaction?: string;
      max_daily_cumulative_amount?: string;
      operating_start_hour_utc?: number;
      operating_end_hour_utc?: number;
      is_active?: boolean;
      approved_by?: string;
    }
  ) => {
    return apiClient<CapabilityEnvelope>(`/api/v1/institutions/${institutionId}/capabilities/${capabilityId}`, {
      method: 'PATCH',
      institutionId,
      body: JSON.stringify({
        ...payload,
        approved_by: payload.approved_by || 'Security Administrator',
      }),
    });
  },
};

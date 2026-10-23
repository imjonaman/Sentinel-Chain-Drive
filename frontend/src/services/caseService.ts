import { apiClient } from './api';
import { FraudCase, RecoveryRequest } from '../types/case';

export const caseService = {
  getCases: () => {
    return apiClient<{ items: FraudCase[]; total: number }>('/api/v1/cases');
  },

  getCase: (caseId: string) => {
    return apiClient<FraudCase>(`/api/v1/cases/${caseId}`);
  },

  createCase: (payload: {
    title: string;
    description?: string;
    severity?: string;
    alert_ids?: string[];
  }) => {
    return apiClient<FraudCase>('/api/v1/cases', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  updateCaseStatus: (caseId: string, status: string, notes?: string, resolutionCategory?: string) => {
    return apiClient<FraudCase>(`/api/v1/cases/${caseId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({
        status,
        resolution_notes: notes,
        resolution_category: resolutionCategory,
      }),
    });
  },

  compileDossier: (caseId: string) => {
    return apiClient<{
      case_id: string;
      dossier_hash: string;
      compiled_at: string;
      evidence_package: Record<string, unknown>;
    }>(`/api/v1/cases/${caseId}/dossier`);
  },

  getRecoveryRequests: () => {
    return apiClient<{ items: RecoveryRequest[]; total: number }>('/api/v1/recovery-requests');
  },

  createRecoveryRequest: (payload: {
    case_id: string;
    counterparty_institution_id: string;
    action_type: string;
    requested_amount?: string;
    currency?: string;
    target_account_id?: string;
  }) => {
    return apiClient<RecoveryRequest>('/api/v1/recovery-requests', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  approveRecoveryRequest: (requestId: string, notes?: string) => {
    return apiClient<RecoveryRequest>(`/api/v1/recovery-requests/${requestId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ notes: notes || 'Approved via Operator UI' }),
    });
  },
};

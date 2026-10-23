import { apiClient } from './api';
import { Policy, PolicyEvaluationResponse, StepUpChallenge, TransactionHold } from '../types/policy';

export const policyService = {
  getPolicies: (institutionId?: string) => {
    const query = institutionId ? `?institution_id=${institutionId}` : '';
    return apiClient<{ items: Policy[]; total: number }>(`/api/v1/policies${query}`);
  },

  evaluatePolicy: (payload: {
    transaction_id: string;
    agent_id?: string;
    origin_account_id: string;
    destination_account_id: string;
    amount: string;
    currency: string;
    transaction_intent_hash?: string;
    institution_id?: string;
  }) => {
    return apiClient<PolicyEvaluationResponse>('/api/v1/policies/evaluate', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  completeStepUp: (challengeId: string, decision: 'APPROVE' | 'REJECT', notes?: string) => {
    return apiClient<StepUpChallenge>(`/api/v1/policies/step-up/${challengeId}/complete`, {
      method: 'POST',
      body: JSON.stringify({ decision, notes }),
    });
  },

  resolveHold: (holdId: string, action: 'RELEASE' | 'CONFIRM_DECLINE', notes?: string) => {
    return apiClient<TransactionHold>(`/api/v1/policies/holds/${holdId}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ action, notes }),
    });
  },
};

import { apiClient } from './api';
import { Institution, Account, Transaction } from '../types/banking';

export const bankingService = {
  getInstitutions: () => 
    apiClient<{ items: Institution[]; total: number }>('/api/v1/institutions'),

  getAccounts: (institutionId?: string) => {
    const query = institutionId ? `?institution_id=${institutionId}` : '';
    return apiClient<{ items: Account[]; total: number }>(`/api/v1/accounts${query}`);
  },

  getTransactions: (institutionId?: string) => {
    const query = institutionId ? `?institution_id=${institutionId}&limit=100` : '?limit=100';
    return apiClient<{ items: Transaction[]; total: number }>(`/api/v1/transactions${query}`);
  },

  submitTransaction: (payload: {
    idempotency_key: string;
    origin_institution_id: string;
    origin_account_id: string;
    destination_institution_id: string;
    destination_account_id: string;
    amount: string;
    currency: string;
    transaction_type?: string;
    purpose_code?: string;
  }) => {
    return apiClient<Transaction>('/api/v1/transactions', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  simulateAction: (transactionId: string, action: 'HOLD' | 'REJECT' | 'CANCEL' | 'SETTLE', reason?: string) => {
    return apiClient<Transaction>(`/api/v1/transactions/${transactionId}/simulate-action`, {
      method: 'POST',
      body: JSON.stringify({ action, reason: reason || 'Operator UI simulated action' }),
    });
  },

  updateInstitutionStatus: (institutionId: string, status: 'ACTIVE' | 'SUSPENDED' | 'INACTIVE', reason?: string) => {
    return apiClient<Institution>(`/api/v1/institutions/${institutionId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status, reason: reason || 'Operator UI status change' }),
    });
  },
};

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TransactionsQueuePage } from '../pages/operator/TransactionsQueuePage';
import { TenantProvider } from '../context/TenantContext';
import { bankingService } from '../services/bankingService';
import { Transaction, Account } from '../types/banking';

vi.mock('../services/bankingService', () => ({
  bankingService: {
    getTransactions: vi.fn(),
    getAccounts: vi.fn(),
    simulateAction: vi.fn(),
    submitTransaction: vi.fn(),
  },
}));

describe('TransactionsQueuePage Component', () => {
  const mockTransactions: Transaction[] = [
    {
      id: 'tx-001',
      idempotency_key: 'idem-tx-001',
      origin_institution_id: '10000000-0000-0000-0000-000000000001',
      origin_account_id: 'acc-001',
      destination_institution_id: '10000000-0000-0000-0000-000000000001',
      destination_account_id: 'acc-002',
      amount: '500.0000',
      currency: 'USD',
      transaction_type: 'DOMESTIC_TRANSFER',
      status: 'PENDING_AUTHORIZATION',
      purpose_code: 'INVOICE_PAYMENT',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    {
      id: 'tx-002',
      idempotency_key: 'idem-tx-002',
      origin_institution_id: '10000000-0000-0000-0000-000000000001',
      origin_account_id: 'acc-001',
      destination_institution_id: '10000000-0000-0000-0000-000000000001',
      destination_account_id: 'acc-002',
      amount: '1200.0000',
      currency: 'USD',
      transaction_type: 'DOMESTIC_TRANSFER',
      status: 'HELD',
      purpose_code: 'PAYROLL',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ];

  const mockAccounts: Account[] = [
    {
      id: 'acc-001',
      institution_id: '10000000-0000-0000-0000-000000000001',
      account_number: '1234567890',
      account_type: 'CHECKING',
      currency: 'USD',
      balance: '50000.0000',
      status: 'ACTIVE',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ];

  beforeEach(() => {
    vi.mocked(bankingService.getTransactions).mockResolvedValue({
      items: mockTransactions,
      total: 2,
    });
    vi.mocked(bankingService.getAccounts).mockResolvedValue({
      items: mockAccounts,
      total: 1,
    });
  });

  it('renders queue table and filters transactions by status', async () => {
    render(
      <TenantProvider>
        <TransactionsQueuePage />
      </TenantProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('idem-tx-001')).toBeInTheDocument();
      expect(screen.getByText('idem-tx-002')).toBeInTheDocument();
    });

    // Filter by HELD
    const heldFilterButton = screen.getByRole('button', { name: /^HELD/i });
    fireEvent.click(heldFilterButton);

    expect(screen.queryByText('idem-tx-001')).not.toBeInTheDocument();
    expect(screen.getByText('idem-tx-002')).toBeInTheDocument();
  });

  it('opens submit payment modal and submits transaction', async () => {
    vi.mocked(bankingService.submitTransaction).mockResolvedValueOnce({
      ...mockTransactions[0],
      id: 'tx-new-001',
      status: 'SETTLED',
    });

    render(
      <TenantProvider>
        <TransactionsQueuePage />
      </TenantProvider>
    );

    // Open modal
    const submitPaymentButton = screen.getByText('Submit Transaction');
    fireEvent.click(submitPaymentButton);

    expect(screen.getByText('Submit Simulated Banking Transaction')).toBeInTheDocument();

    // Submit form
    const submitBtns = screen.getAllByRole('button', { name: /Submit Transaction/i });
    fireEvent.click(submitBtns[submitBtns.length - 1]);

    await waitFor(() => {
      expect(bankingService.submitTransaction).toHaveBeenCalled();
    });
  });
});

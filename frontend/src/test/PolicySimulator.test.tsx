import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PolicySimulator } from '../components/forms/PolicySimulator';
import { TenantProvider } from '../context/TenantContext';
import { policyService } from '../services/policyService';

vi.mock('../services/policyService', () => ({
  policyService: {
    evaluatePolicy: vi.fn(),
  },
}));

describe('PolicySimulator Interactive Component', () => {
  it('renders input fields, simulates evaluation, and displays deterministic ALLOW decision', async () => {
    vi.mocked(policyService.evaluatePolicy).mockResolvedValueOnce({
      decision_id: 'dec-allow-001',
      outcome: 'ALLOW',
      reason_code: 'ALL_POLICIES_PASSED',
      evaluation_timestamp: new Date().toISOString(),
    });

    render(
      <TenantProvider>
        <PolicySimulator />
      </TenantProvider>
    );

    // Verify fields render
    const amountInput = screen.getByLabelText(/Transaction Amount/i);
    expect(amountInput).toBeInTheDocument();
    expect(screen.getByText(/Execute Policy Evaluation/i)).toBeInTheDocument();

    // Change amount
    fireEvent.change(amountInput, { target: { value: '250.0000' } });

    // Execute evaluation
    fireEvent.click(screen.getByText(/Execute Policy Evaluation/i));

    await waitFor(() => {
      expect(screen.getByText('ALLOW')).toBeInTheDocument();
      expect(screen.getByText('ALL_POLICIES_PASSED')).toBeInTheDocument();
      expect(screen.getByText('dec-allow-001')).toBeInTheDocument();
    });
  });

  it('displays STEP_UP decision badge when dual-control threshold is triggered', async () => {
    vi.mocked(policyService.evaluatePolicy).mockResolvedValueOnce({
      decision_id: 'dec-stepup-002',
      outcome: 'STEP_UP',
      reason_code: 'DUAL_CONTROL_THRESHOLD_EXCEEDED',
      evaluation_timestamp: new Date().toISOString(),
      challenge_id: 'ch-stepup-999',
    });

    render(
      <TenantProvider>
        <PolicySimulator />
      </TenantProvider>
    );

    fireEvent.click(screen.getByText(/Execute Policy Evaluation/i));

    await waitFor(() => {
      expect(screen.getByText(/STEP_UP \(Dual-Control Required\)/i)).toBeInTheDocument();
      expect(screen.getByText('ch-stepup-999')).toBeInTheDocument();
    });
  });
});

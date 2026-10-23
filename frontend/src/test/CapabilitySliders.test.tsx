import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CapabilitySliders } from '../components/forms/CapabilitySliders';
import { CapabilityEnvelope } from '../types/agent';

describe('CapabilitySliders Interactive Component', () => {
  const mockCapability: CapabilityEnvelope = {
    id: 'cap-001',
    institution_id: '10000000-0000-0000-0000-000000000001',
    agent_id: 'ag-001',
    max_amount_per_transaction: '1500.0000',
    max_daily_cumulative_amount: '10000.0000',
    permitted_currencies: ['USD'],
    destination_account_whitelist: [],
    operating_start_hour_utc: 8,
    operating_end_hour_utc: 18,
    is_active: true,
    version: 1,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  it('renders slider limits and displays formatted amounts', () => {
    render(<CapabilitySliders capability={mockCapability} />);

    expect(screen.getByText('Single Transaction Cap')).toBeInTheDocument();
    expect(screen.getByText('24h Daily Cumulative Cap')).toBeInTheDocument();
    expect(screen.getByText('$1,500')).toBeInTheDocument();
    expect(screen.getByText('$10,000')).toBeInTheDocument();
    expect(screen.getByText('08:00 – 18:00 UTC')).toBeInTheDocument();
  });

  it('triggers onSave with updated limit parameters', async () => {
    const onSaveMock = vi.fn().mockResolvedValue(undefined);

    render(<CapabilitySliders capability={mockCapability} onSave={onSaveMock} />);

    const updateButton = screen.getByText('Update Envelope');
    fireEvent.click(updateButton);

    await waitFor(() => {
      expect(onSaveMock).toHaveBeenCalledWith({
        max_amount_per_transaction: '1500.0000',
        max_daily_cumulative_amount: '10000.0000',
        operating_start_hour_utc: 8,
        operating_end_hour_utc: 18,
      });
      expect(screen.getByText('Saved!')).toBeInTheDocument();
    });
  });

  it('prevents saving when single limit exceeds daily cumulative cap', async () => {
    const onSaveMock = vi.fn();
    const badCapability: CapabilityEnvelope = {
      ...mockCapability,
      max_amount_per_transaction: '20000.0000',
      max_daily_cumulative_amount: '5000.0000',
    };

    render(<CapabilitySliders capability={badCapability} onSave={onSaveMock} />);

    fireEvent.click(screen.getByText('Update Envelope'));

    await waitFor(() => {
      expect(screen.getByText('Single transaction limit cannot exceed 24h cumulative limit')).toBeInTheDocument();
      expect(onSaveMock).not.toHaveBeenCalled();
    });
  });
});

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TransactionGraphView } from '../components/graph/TransactionGraphView';
import { CytoscapeElement } from '../types/graph';

// Mock cytoscape core constructor
vi.mock('cytoscape', () => {
  return {
    default: vi.fn(() => ({
      on: vi.fn(),
      zoom: vi.fn(),
      fit: vi.fn(),
      destroy: vi.fn(),
    })),
  };
});

describe('TransactionGraphView Component', () => {
  const mockElements: CytoscapeElement[] = [
    {
      group: 'nodes',
      data: {
        id: 'acc-001',
        label: 'CHECKING ···1234',
        institution_id: 'inst-001',
        currency: 'USD',
        risk_status: 'NORMAL',
        alert_count: 0,
      },
    },
    {
      group: 'nodes',
      data: {
        id: 'acc-002',
        label: 'SAVINGS ···5678',
        institution_id: 'inst-001',
        currency: 'USD',
        risk_status: 'CRITICAL',
        alert_count: 2,
      },
    },
    {
      group: 'edges',
      data: {
        id: 'tx-001',
        source: 'acc-001',
        target: 'acc-002',
        amount: '1500.0000',
        currency: 'USD',
        timestamp: new Date().toISOString(),
        status: 'SETTLED',
        pattern_type: 'PASS_THROUGH',
      },
    },
  ];

  it('renders graph explorer header, controls, and canvas container', () => {
    render(<TransactionGraphView elements={mockElements} />);

    expect(screen.getByText('MuleChain Topological Explorer')).toBeInTheDocument();
    expect(screen.getByText('Topology Legend')).toBeInTheDocument();
    expect(screen.getByText('Clean Account')).toBeInTheDocument();
    expect(screen.getByText('High Risk / Mule Node')).toBeInTheDocument();
  });
});

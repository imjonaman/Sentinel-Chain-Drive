import { describe, it, expect } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { AuthProvider, useAuth, ROLE_CONFIGS } from '../context/AuthContext';

const TestComponent = () => {
  const { user, setRole, roleConfig } = useAuth();
  return (
    <div>
      <span data-testid="user-role">{user.role}</span>
      <span data-testid="role-label">{roleConfig.label}</span>
      <button onClick={() => setRole('FRAUD_ANALYST')}>Switch to Fraud Analyst</button>
      <button onClick={() => setRole('SECURITY_ADMINISTRATOR')}>Switch to Sec Admin</button>
      <button onClick={() => setRole('AUDITOR')}>Switch to Auditor</button>
    </div>
  );
};

describe('Role-Aware Access and Context', () => {
  it('initializes with default Bank Operator role and correct permissions', () => {
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    expect(screen.getByTestId('user-role').textContent).toBe('BANK_OPERATOR');
    expect(screen.getByTestId('role-label').textContent).toBe('Bank Operator');
    expect(ROLE_CONFIGS.BANK_OPERATOR.permissions).toContain('step_up:approve');
  });

  it('updates role and configuration dynamically upon role switch', () => {
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    act(() => {
      screen.getByText('Switch to Fraud Analyst').click();
    });

    expect(screen.getByTestId('user-role').textContent).toBe('FRAUD_ANALYST');
    expect(screen.getByTestId('role-label').textContent).toBe('Fraud Analyst');
  });
});

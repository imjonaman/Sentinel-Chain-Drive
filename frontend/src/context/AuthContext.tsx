import React, { createContext, useContext, useState, useEffect } from 'react';
import { UserRole, UserProfile, RoleConfig } from '../types/auth';

export const ROLE_CONFIGS: Record<UserRole, RoleConfig> = {
  BANK_OPERATOR: {
    label: 'Bank Operator',
    description: 'Transaction authorization queue, dual-control step-up approvals, and hold reviews.',
    color: 'emerald',
    badgeClass: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    permissions: ['transactions:read', 'transactions:write', 'step_up:approve', 'holds:resolve'],
  },
  SECURITY_ADMINISTRATOR: {
    label: 'Security Administrator',
    description: 'Autonomous AgentID lifecycle, Ed25519 key rotation, and capability limits.',
    color: 'indigo',
    badgeClass: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30',
    permissions: ['agents:manage', 'capabilities:manage', 'policies:manage', 'keys:rotate'],
  },
  FRAUD_ANALYST: {
    label: 'Fraud Analyst',
    description: 'MuleChain graph topological intelligence, alert triage, case management, and recovery.',
    color: 'rose',
    badgeClass: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
    permissions: ['mulechain:analyze', 'alerts:triage', 'cases:manage', 'recovery:orchestrate', 'graph:explore'],
  },
  AUDITOR: {
    label: 'Compliance Auditor',
    description: 'Tamper-evident hash validation, DRUNIX outbox inspection, and immutable audit logs.',
    color: 'amber',
    badgeClass: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    permissions: ['audit:read', 'drunix:read', 'dossier:verify'],
  },
};

interface AuthContextType {
  user: UserProfile;
  setRole: (role: UserRole) => void;
  hasPermission: (permission: string) => void;
  roleConfig: RoleConfig;
}

const DEFAULT_USER: UserProfile = {
  id: 'usr-demo-001',
  username: 'operator@apexbank.internal',
  displayName: 'Alex Vance',
  email: 'alex.vance@apexbank.internal',
  role: 'BANK_OPERATOR',
  institutionId: '10000000-0000-0000-0000-000000000001',
  institutionCode: 'APEX_BANK',
  token: 'mock-jwt-token-sentinel-2026',
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile>(() => {
    const saved = localStorage.getItem('sentinel_user');
    return saved ? JSON.parse(saved) : DEFAULT_USER;
  });

  useEffect(() => {
    localStorage.setItem('sentinel_user', JSON.stringify(user));
  }, [user]);

  const setRole = (newRole: UserRole) => {
    setUser((prev) => ({
      ...prev,
      role: newRole,
      displayName: 
        newRole === 'BANK_OPERATOR' ? 'Alex Vance (Operator)' :
        newRole === 'SECURITY_ADMINISTRATOR' ? 'Elena Rostova (SecOps)' :
        newRole === 'FRAUD_ANALYST' ? 'Marcus Brody (Fraud Lead)' :
        'Sophia Chen (Senior Auditor)',
    }));
  };

  const hasPermission = (permission: string) => {
    return ROLE_CONFIGS[user.role].permissions.includes(permission);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        setRole,
        hasPermission,
        roleConfig: ROLE_CONFIGS[user.role],
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

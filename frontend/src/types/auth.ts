export type UserRole = 
  | 'BANK_OPERATOR'
  | 'SECURITY_ADMINISTRATOR'
  | 'FRAUD_ANALYST'
  | 'AUDITOR';

export interface UserProfile {
  id: string;
  username: string;
  displayName: string;
  email: string;
  role: UserRole;
  institutionId: string;
  institutionCode: string;
  token: string;
}

export interface RoleConfig {
  label: string;
  description: string;
  color: string;
  badgeClass: string;
  permissions: string[];
}

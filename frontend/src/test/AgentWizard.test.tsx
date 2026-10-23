import { describe, it, expect } from 'vitest';
import { agentRegistrationSchema } from '../components/forms/AgentRegistrationWizard';

describe('Agent Registration Zod Validation Schema', () => {
  it('accepts valid Ed25519 public key and capability limits', () => {
    const validData = {
      name: 'Sentinel-Autonomous-Agent-01',
      description: 'Test autonomous bot',
      ed25519_public_key: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
      max_amount_per_transaction: '1000.00',
      max_daily_cumulative_amount: '5000.00',
      currency: 'USD',
      operating_start_hour: 8,
      operating_end_hour: 18,
    };

    const result = agentRegistrationSchema.safeParse(validData);
    expect(result.success).toBe(true);
  });

  it('rejects malformed Ed25519 public keys with non-hex or invalid length', () => {
    const invalidKeyData = {
      name: 'Sentinel-Agent-BadKey',
      ed25519_public_key: 'short_key_1234',
      max_amount_per_transaction: '1000.00',
      max_daily_cumulative_amount: '5000.00',
      currency: 'USD',
      operating_start_hour: 8,
      operating_end_hour: 18,
    };

    const result = agentRegistrationSchema.safeParse(invalidKeyData);
    expect(result.success).toBe(false);
    if (!result.success) {
      const fieldErrors = result.error.flatten().fieldErrors;
      expect(fieldErrors.ed25519_public_key).toBeDefined();
    }
  });

  it('rejects when daily cumulative limit is less than single transaction cap', () => {
    const invalidLimitsData = {
      name: 'Sentinel-Agent-BadLimits',
      ed25519_public_key: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
      max_amount_per_transaction: '10000.00',
      max_daily_cumulative_amount: '2000.00', // Invalid: daily < single
      currency: 'USD',
      operating_start_hour: 8,
      operating_end_hour: 18,
    };

    const result = agentRegistrationSchema.safeParse(invalidLimitsData);
    expect(result.success).toBe(false);
  });
});

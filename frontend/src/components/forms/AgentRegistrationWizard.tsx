import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import {
  Bot,
  Key,
  Sliders,
  CheckCircle2,
  AlertCircle,
  ArrowRight,
  ArrowLeft,
  Sparkles,
  ShieldCheck,
} from 'lucide-react';
import { agentService } from '../../services/agentService';
import { useTenant } from '../../context/TenantContext';

// Zod Schema for Agent Registration and Initial Capability Envelope
export const agentRegistrationSchema = z.object({
  name: z.string().min(3, 'Agent name must be at least 3 characters').max(64),
  description: z.string().max(255).optional(),
  ed25519_public_key: z
    .string()
    .length(64, 'Ed25519 public key must be exactly 64 hexadecimal characters')
    .regex(/^[0-9a-fA-F]{64}$/, 'Must be a valid hex-encoded Ed25519 public key'),
  max_amount_per_transaction: z.string().refine((val) => parseFloat(val) > 0, {
    message: 'Single limit must be greater than 0',
  }),
  max_daily_cumulative_amount: z.string().refine((val) => parseFloat(val) > 0, {
    message: 'Daily limit must be greater than 0',
  }),
  currency: z.string().default('USD'),
  operating_start_hour: z.number().min(0).max(23),
  operating_end_hour: z.number().min(1).max(23),
}).refine(
  (data) => parseFloat(data.max_daily_cumulative_amount) >= parseFloat(data.max_amount_per_transaction),
  {
    message: 'Daily cumulative limit cannot be less than single transaction limit',
    path: ['max_daily_cumulative_amount'],
  }
).refine(
  (data) => data.operating_end_hour > data.operating_start_hour,
  {
    message: 'Operating end hour must be after start hour',
    path: ['operating_end_hour'],
  }
);

export type AgentRegistrationFormData = z.infer<typeof agentRegistrationSchema>;

interface AgentRegistrationWizardProps {
  onSuccess?: () => void;
  onCancel?: () => void;
}

export const AgentRegistrationWizard: React.FC<AgentRegistrationWizardProps> = ({
  onSuccess,
  onCancel,
}) => {
  const { activeInstitutionId, setActiveInstitutionId, currentInstitution, institutions } = useTenant();
  const [step, setStep] = useState<number>(1);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  const isCurrentActive = currentInstitution?.status === 'ACTIVE';
  const activeInstitutions = institutions.filter((i) => i.status === 'ACTIVE');

  const {
    register,
    handleSubmit,
    trigger,
    setValue,
    watch,
    formState: { errors },
  } = useForm<AgentRegistrationFormData>({
    resolver: zodResolver(agentRegistrationSchema),
    defaultValues: {
      name: '',
      description: '',
      ed25519_public_key: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
      max_amount_per_transaction: '5000.00',
      max_daily_cumulative_amount: '25000.00',
      currency: 'USD',
      operating_start_hour: 8,
      operating_end_hour: 18,
    },
    mode: 'onChange',
  });

  const formValues = watch();

  const handleGenerateKey = () => {
    const chars = '0123456789abcdef';
    let key = '';
    for (let i = 0; i < 64; i++) {
      key += chars[Math.floor(Math.random() * chars.length)];
    }
    setValue('ed25519_public_key', key, { shouldValidate: true });
  };

  const applyPresetLimits = (single: string, daily: string, start: number, end: number) => {
    setValue('max_amount_per_transaction', single, { shouldValidate: true });
    setValue('max_daily_cumulative_amount', daily, { shouldValidate: true });
    setValue('operating_start_hour', start, { shouldValidate: true });
    setValue('operating_end_hour', end, { shouldValidate: true });
  };

  const nextStep = async () => {
    let fieldsToValidate: (keyof AgentRegistrationFormData)[] = [];
    if (step === 1) fieldsToValidate = ['name', 'description'];
    if (step === 2) fieldsToValidate = ['ed25519_public_key'];

    const isValid = await trigger(fieldsToValidate);
    if (isValid) {
      setStep((s) => Math.min(s + 1, 3));
    }
  };

  const prevStep = () => setStep((s) => Math.max(s - 1, 1));

  const onSubmit = async (data: AgentRegistrationFormData) => {
    // PREVENT PREMATURE SUBMISSION: If user is on Step 1 or 2, advance step instead of submitting
    if (step < 3) {
      await nextStep();
      return;
    }

    if (currentInstitution && currentInstitution.status !== 'ACTIVE') {
      setSubmissionError(
        `Target institution "${currentInstitution.name}" is ${currentInstitution.status}. Please select an ACTIVE institution to register an agent.`
      );
      return;
    }

    setIsSubmitting(true);
    setSubmissionError(null);
    try {
      // 1. Register Agent
      const agent = await agentService.registerAgent(activeInstitutionId, {
        name: data.name,
        description: data.description,
        ed25519_public_key: data.ed25519_public_key,
      });

      // 2. Activate agent immediately
      try {
        await agentService.updateAgentStatus(activeInstitutionId, agent.id, 'ACTIVE', 'Initial security registration approval');
      } catch {
        // Non-blocking if already active
      }

      // 3. Assign Capability Envelope with the user's chosen limits
      await agentService.assignCapability(activeInstitutionId, {
        agent_id: agent.id,
        name: `${data.name} Envelope`,
        max_amount_per_transaction: data.max_amount_per_transaction,
        max_daily_cumulative_amount: data.max_daily_cumulative_amount,
        permitted_currencies: [data.currency],
        destination_account_whitelist: [],
        operating_start_hour_utc: data.operating_start_hour,
        operating_end_hour_utc: data.operating_end_hour,
      });

      if (onSuccess) onSuccess();
    } catch (err: unknown) {
      setSubmissionError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLFormElement>) => {
    // Intercept Enter key press on inputs so form does not submit prematurely before step 3
    if (e.key === 'Enter' && (e.target as HTMLElement).tagName !== 'TEXTAREA') {
      e.preventDefault();
      if (step < 3) {
        nextStep();
      }
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl max-w-xl mx-auto">
      {/* Wizard Header & Stepper */}
      <div className="mb-6">
        <h3 className="text-lg font-semibold text-white flex items-center space-x-2">
          <Bot className="w-5 h-5 text-indigo-400" />
          <span>Autonomous Agent Registration Wizard</span>
        </h3>
        <p className="text-xs text-slate-400 mt-1">
          Issue cryptographic credentials and bind capability boundaries to an autonomous banking agent.
        </p>

        {/* Interactive Stepper Navigation */}
        <div className="grid grid-cols-3 gap-2 mt-4 text-xs font-medium">
          <button
            type="button"
            onClick={() => setStep(1)}
            className={`flex items-center justify-center space-x-1.5 py-2 px-3 rounded-xl border transition ${
              step === 1
                ? 'bg-indigo-600/20 border-indigo-500 text-indigo-300 font-bold'
                : step > 1
                ? 'bg-slate-800/80 border-slate-700 text-slate-300 hover:bg-slate-800'
                : 'bg-slate-900/50 border-slate-800 text-slate-500'
            }`}
          >
            <Bot className="w-3.5 h-3.5" />
            <span>1. Identity</span>
          </button>

          <button
            type="button"
            onClick={async () => {
              const valid = await trigger(['name', 'description']);
              if (valid) setStep(2);
            }}
            className={`flex items-center justify-center space-x-1.5 py-2 px-3 rounded-xl border transition ${
              step === 2
                ? 'bg-cyan-600/20 border-cyan-500 text-cyan-300 font-bold'
                : step > 2
                ? 'bg-slate-800/80 border-slate-700 text-slate-300 hover:bg-slate-800'
                : 'bg-slate-900/50 border-slate-800 text-slate-500'
            }`}
          >
            <Key className="w-3.5 h-3.5" />
            <span>2. Key</span>
          </button>

          <button
            type="button"
            onClick={async () => {
              const valid = await trigger(['name', 'description', 'ed25519_public_key']);
              if (valid) setStep(3);
            }}
            className={`flex items-center justify-center space-x-1.5 py-2 px-3 rounded-xl border transition ${
              step === 3
                ? 'bg-emerald-600/20 border-emerald-500 text-emerald-300 font-bold'
                : 'bg-slate-900/50 border-slate-800 text-slate-500'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>3. Limits</span>
          </button>
        </div>

        {/* Target Institution Selector */}
        <div className="mt-4 p-3 rounded-xl bg-slate-800/80 border border-slate-700/80 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-slate-300">Target Institution:</span>
            <span
              className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold ${
                isCurrentActive
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                  : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
              }`}
            >
              {currentInstitution?.status || 'UNKNOWN'}
            </span>
          </div>

          <select
            value={activeInstitutionId}
            onChange={(e) => setActiveInstitutionId(e.target.value)}
            className="w-full px-3 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-xs font-sans text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            {institutions.map((inst) => (
              <option key={inst.id} value={inst.id}>
                {inst.name} ({inst.routing_identifier}) — {inst.status}
              </option>
            ))}
          </select>

          {!isCurrentActive && (
            <div className="text-[11px] text-amber-300/90 flex items-start space-x-1.5 pt-1">
              <AlertCircle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
              <span>
                <strong>Warning:</strong> Agents cannot be registered under a suspended or inactive institution.
                {activeInstitutions.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setActiveInstitutionId(activeInstitutions[0].id)}
                    className="ml-1 text-cyan-400 hover:text-cyan-300 underline font-semibold"
                  >
                    Switch to {activeInstitutions[0].name}
                  </button>
                )}
              </span>
            </div>
          )}
        </div>
      </div>

      {submissionError && (
        <div className="mb-4 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{submissionError}</span>
        </div>
      )}

      <form onSubmit={handleSubmit(onSubmit)} onKeyDown={handleKeyDown} className="space-y-4">
        {/* Step 1: Agent Profile */}
        {step === 1 && (
          <div className="space-y-4 animate-fadeIn">
            <div>
              <label htmlFor="agent-name-input" className="block text-xs font-medium text-slate-300 mb-1">
                Agent Identifier Name <span className="text-rose-400">*</span>
              </label>
              <input
                id="agent-name-input"
                {...register('name')}
                placeholder="e.g. Treasury-Rebalancer-Bot-01"
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-indigo-500"
              />
              {errors.name && <p className="text-[11px] text-rose-400 mt-1">{errors.name.message}</p>}
            </div>

            <div>
              <label htmlFor="agent-desc-input" className="block text-xs font-medium text-slate-300 mb-1">
                Operational Mandate & Description
              </label>
              <textarea
                id="agent-desc-input"
                {...register('description')}
                placeholder="Describe the agent's autonomous mandate, purpose, and scope..."
                rows={3}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-indigo-500"
              />
              {errors.description && <p className="text-[11px] text-rose-400 mt-1">{errors.description.message}</p>}
            </div>

            <div className="p-3 bg-slate-800/40 rounded-xl border border-slate-700/60 text-xs text-slate-400">
              <span className="font-semibold text-slate-300">Next Step:</span> Configure the agent&apos;s cryptographic Ed25519 signing key in Step 2, and customize transaction and daily velocity limits in Step 3.
            </div>
          </div>
        )}

        {/* Step 2: Ed25519 Public Key */}
        {step === 2 && (
          <div className="space-y-4 animate-fadeIn">
            <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-xs text-indigo-300 flex items-start space-x-2">
              <Key className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">RFC 8032 Cryptographic Identity:</span>
                <p className="text-[11px] text-indigo-300/80 mt-0.5">
                  Transactions initiated by this agent must be cryptographically signed using the corresponding private Ed25519 key.
                </p>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label htmlFor="agent-ed25519-key-input" className="block text-xs font-medium text-slate-300">
                  Ed25519 Public Key (64-Hex String) <span className="text-rose-400">*</span>
                </label>
                <button
                  type="button"
                  onClick={handleGenerateKey}
                  className="text-xs text-cyan-400 hover:text-cyan-300 underline font-medium"
                >
                  Generate Test Key
                </button>
              </div>
              <input
                id="agent-ed25519-key-input"
                {...register('ed25519_public_key')}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-cyan-300 focus:outline-none focus:border-indigo-500"
              />
              {errors.ed25519_public_key && (
                <p className="text-[11px] text-rose-400 mt-1">{errors.ed25519_public_key.message}</p>
              )}
            </div>
          </div>
        )}

        {/* Step 3: Capability Limits */}
        {step === 3 && (
          <div className="space-y-4 animate-fadeIn">
            <div className="flex items-center justify-between text-xs text-indigo-400 font-semibold mb-1">
              <div className="flex items-center space-x-2">
                <Sliders className="w-4 h-4" />
                <span>Deterministic Capability Envelope Limits</span>
              </div>
              <span className="text-[10px] text-slate-400 font-normal">Step 3 of 3</span>
            </div>

            {/* Presets */}
            <div className="flex items-center space-x-2 p-2 rounded-xl bg-slate-800/50 border border-slate-700/60 text-[11px]">
              <span className="text-slate-400 flex items-center space-x-1 shrink-0 font-medium">
                <Sparkles className="w-3 h-3 text-cyan-400" />
                <span>Presets:</span>
              </span>
              <button
                type="button"
                onClick={() => applyPresetLimits('1000.00', '5000.00', 9, 17)}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
              >
                Micro ($1k / $5k)
              </button>
              <button
                type="button"
                onClick={() => applyPresetLimits('5000.00', '25000.00', 8, 18)}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
              >
                Standard ($5k / $25k)
              </button>
              <button
                type="button"
                onClick={() => applyPresetLimits('25000.00', '100000.00', 6, 22)}
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
              >
                Treasury ($25k / $100k)
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="max-single-amount-input" className="block text-xs text-slate-300 mb-1">
                  Max Single Tx ($) <span className="text-rose-400">*</span>
                </label>
                <input
                  id="max-single-amount-input"
                  {...register('max_amount_per_transaction')}
                  type="number"
                  step="100"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white focus:outline-none focus:border-indigo-500"
                />
                {errors.max_amount_per_transaction && (
                  <p className="text-[10px] text-rose-400 mt-1">{errors.max_amount_per_transaction.message}</p>
                )}
              </div>

              <div>
                <label htmlFor="max-daily-amount-input" className="block text-xs text-slate-300 mb-1">
                  Max 24h Cumulative ($) <span className="text-rose-400">*</span>
                </label>
                <input
                  id="max-daily-amount-input"
                  {...register('max_daily_cumulative_amount')}
                  type="number"
                  step="500"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white focus:outline-none focus:border-indigo-500"
                />
                {errors.max_daily_cumulative_amount && (
                  <p className="text-[10px] text-rose-400 mt-1">{errors.max_daily_cumulative_amount.message}</p>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="operating-start-hour-input" className="block text-xs text-slate-300 mb-1">
                  UTC Window Start (0–23)
                </label>
                <input
                  id="operating-start-hour-input"
                  {...register('operating_start_hour', { valueAsNumber: true })}
                  type="number"
                  min="0"
                  max="23"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label htmlFor="operating-end-hour-input" className="block text-xs text-slate-300 mb-1">
                  UTC Window End (1–23)
                </label>
                <input
                  id="operating-end-hour-input"
                  {...register('operating_end_hour', { valueAsNumber: true })}
                  type="number"
                  min="1"
                  max="23"
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>
            {errors.operating_end_hour && (
              <p className="text-[10px] text-rose-400">{errors.operating_end_hour.message}</p>
            )}

            {/* Summary Confirmation Card */}
            <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-xs space-y-1 text-slate-300">
              <div className="font-semibold text-white flex items-center space-x-1.5">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>Ready to Authorize:</span>
              </div>
              <div className="grid grid-cols-2 gap-1 text-[11px] pt-1 font-mono">
                <div>Agent: <span className="text-white">{formValues.name || 'Unnamed Agent'}</span></div>
                <div>Institution: <span className="text-cyan-300">{currentInstitution?.name}</span></div>
                <div>Single Cap: <span className="text-indigo-300">${formValues.max_amount_per_transaction}</span></div>
                <div>Daily Cap: <span className="text-cyan-300">${formValues.max_daily_cumulative_amount}</span></div>
                <div className="col-span-2">
                  Operating Window: <span className="text-amber-300">{formValues.operating_start_hour}:00 – {formValues.operating_end_hour}:00 UTC</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Wizard Navigation Buttons */}
        <div className="flex items-center justify-between pt-4 border-t border-slate-800">
          {step > 1 ? (
            <button
              type="button"
              onClick={prevStep}
              className="px-4 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition flex items-center space-x-1"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition"
            >
              Cancel
            </button>
          )}

          {step < 3 ? (
            <button
              type="button"
              onClick={nextStep}
              className="px-5 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition flex items-center space-x-1.5 shadow-lg shadow-indigo-600/30"
            >
              <span>Next: {step === 1 ? 'Configure Key' : 'Set Limits'}</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={isSubmitting || !isCurrentActive}
              className="px-5 py-2.5 rounded-xl text-xs font-bold bg-gradient-to-r from-indigo-600 to-cyan-500 hover:opacity-95 text-white transition flex items-center space-x-1.5 shadow-lg shadow-indigo-500/25 disabled:opacity-50"
            >
              {isSubmitting ? (
                <span>Registering Agent & Limits...</span>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4 text-emerald-300" />
                  <span>Register & Apply Limits</span>
                </>
              )}
            </button>
          )}
        </div>
      </form>
    </div>
  );
};

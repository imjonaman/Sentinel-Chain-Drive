import React, { useState } from 'react';
import { policyService } from '../../services/policyService';
import { PolicyOutcome, PolicyEvaluationResponse } from '../../types/policy';
import { Play, AlertCircle, ShieldAlert, CheckCircle2 } from 'lucide-react';
import { useTenant } from '../../context/TenantContext';

export const PolicySimulator: React.FC = () => {
  const { activeInstitutionId } = useTenant();

  const [originAccountId, setOriginAccountId] = useState('20000000-0000-0000-0000-000000000001');
  const [destAccountId, setDestAccountId] = useState('20000000-0000-0000-0000-000000000003');
  const [amount, setAmount] = useState('1500.0000');
  const [currency, setCurrency] = useState('USD');

  const [isSimulating, setIsSimulating] = useState(false);
  const [result, setResult] = useState<PolicyEvaluationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runSimulation = async () => {
    setIsSimulating(true);
    setError(null);
    setResult(null);
    try {
      const evaluation = await policyService.evaluatePolicy({
        transaction_id: 'sim-' + Math.random().toString(36).substring(2, 10),
        origin_account_id: originAccountId,
        destination_account_id: destAccountId,
        amount,
        currency,
        institution_id: activeInstitutionId,
      });
      setResult(evaluation);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Simulation evaluation failed');
    } finally {
      setIsSimulating(false);
    }
  };

  const getOutcomeBadge = (outcome: PolicyOutcome) => {
    switch (outcome) {
      case 'ALLOW':
        return (
          <div className="flex items-center space-x-2 text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-3 py-1.5 rounded-xl font-mono text-sm font-bold">
            <CheckCircle2 className="w-4 h-4" />
            <span>ALLOW</span>
          </div>
        );
      case 'STEP_UP':
        return (
          <div className="flex items-center space-x-2 text-amber-400 bg-amber-500/10 border border-amber-500/30 px-3 py-1.5 rounded-xl font-mono text-sm font-bold">
            <ShieldAlert className="w-4 h-4" />
            <span>STEP_UP (Dual-Control Required)</span>
          </div>
        );
      case 'HOLD':
        return (
          <div className="flex items-center space-x-2 text-purple-400 bg-purple-500/10 border border-purple-500/30 px-3 py-1.5 rounded-xl font-mono text-sm font-bold">
            <AlertCircle className="w-4 h-4" />
            <span>HOLD (Fraud / Velocity Review)</span>
          </div>
        );
      case 'DECLINE':
        return (
          <div className="flex items-center space-x-2 text-rose-400 bg-rose-500/10 border border-rose-500/30 px-3 py-1.5 rounded-xl font-mono text-sm font-bold">
            <AlertCircle className="w-4 h-4" />
            <span>DECLINE (Fail-Closed)</span>
          </div>
        );
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white flex items-center space-x-2">
            <Play className="w-4 h-4 text-cyan-400" />
            <span>Real-Time Deterministic Policy Simulator</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Evaluate simulated transaction fixtures against active 7-tier rule precedence.
          </p>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-xs text-rose-400">
          {error}
        </div>
      )}

      {/* Inputs Form */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label htmlFor="sim-origin-account-input" className="block text-xs text-slate-300 mb-1">Origin Account UUID</label>
          <input
            id="sim-origin-account-input"
            type="text"
            value={originAccountId}
            onChange={(e) => setOriginAccountId(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
          />
        </div>

        <div>
          <label htmlFor="sim-dest-account-input" className="block text-xs text-slate-300 mb-1">Destination Account UUID</label>
          <input
            id="sim-dest-account-input"
            type="text"
            value={destAccountId}
            onChange={(e) => setDestAccountId(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
          />
        </div>

        <div>
          <label htmlFor="sim-amount-input" className="block text-xs text-slate-300 mb-1">Transaction Amount ($)</label>
          <input
            id="sim-amount-input"
            type="text"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white focus:outline-none focus:border-cyan-500"
          />
        </div>

        <div>
          <label htmlFor="sim-currency-input" className="block text-xs text-slate-300 mb-1">Currency Code</label>
          <input
            id="sim-currency-input"
            type="text"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white focus:outline-none focus:border-cyan-500"
          />
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={runSimulation}
          disabled={isSimulating}
          className="px-5 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-cyan-500 to-indigo-600 hover:opacity-95 text-white transition flex items-center space-x-2 shadow-lg shadow-cyan-500/20"
        >
          {isSimulating ? (
            <span>Evaluating Policy...</span>
          ) : (
            <>
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Execute Policy Evaluation</span>
            </>
          )}
        </button>
      </div>

      {/* Output Result */}
      {result && (
        <div className="p-4 rounded-xl bg-slate-800/80 border border-slate-700 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-300">Deterministic Outcome:</span>
            {getOutcomeBadge(result.outcome)}
          </div>
          <div className="text-xs font-mono space-y-1 text-slate-400">
            <div><span className="text-slate-500">Reason Code:</span> <span className="text-white font-semibold">{result.reason_code}</span></div>
            <div><span className="text-slate-500">Decision ID:</span> <span className="text-slate-300">{result.decision_id}</span></div>
            {result.challenge_id && (
              <div><span className="text-slate-500">Challenge ID:</span> <span className="text-amber-300">{result.challenge_id}</span></div>
            )}
            {result.hold_id && (
              <div><span className="text-slate-500">Hold ID:</span> <span className="text-purple-300">{result.hold_id}</span></div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

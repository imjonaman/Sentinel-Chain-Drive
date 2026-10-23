import React from 'react';
import { Sliders, ShieldCheck, ArrowDown } from 'lucide-react';
import { PolicySimulator } from '../../components/forms/PolicySimulator';

export const PoliciesConsolePage: React.FC = () => {
  const precedenceTiers = [
    { tier: 1, title: 'Security Violations', outcome: 'DECLINE', desc: 'Invalid Ed25519 signature, revoked agent, replayed nonce, or clock skew > 300s.' },
    { tier: 2, title: 'Account Restrictions', outcome: 'DECLINE', desc: 'Origin or destination account FROZEN or CLOSED.' },
    { tier: 3, title: 'Agent Capability Limits', outcome: 'DECLINE', desc: 'Per-transaction cap breach or 24-hour cumulative velocity exhaustion.' },
    { tier: 4, title: 'Institutional Cap Limits', outcome: 'DECLINE', desc: 'Institution-wide single transaction hard limit exceeded.' },
    { tier: 5, title: 'MuleChain Risk Holds', outcome: 'HOLD', desc: 'MuleChain topological risk score >= threshold or rapid pass-through anomaly.' },
    { tier: 6, title: 'Step-Up Dual Control', outcome: 'STEP_UP', desc: 'Transaction amount >= supervisor threshold; halts for human certification.' },
    { tier: 7, title: 'Default Allow', outcome: 'ALLOW', desc: 'All preceding security and risk checks passed cleanly.' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white flex items-center space-x-2">
          <Sliders className="w-5 h-5 text-indigo-400" />
          <span>Deterministic Policy Governance & Rule Precedence</span>
        </h2>
        <p className="text-xs text-slate-400 mt-0.5">
          Inspect the immutable 7-tier evaluation hierarchy and test proposed constraints in real-time.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        {/* Left: 7-Tier Precedence Visualizer */}
        <div className="glass-card rounded-2xl p-6 border border-slate-800 space-y-4">
          <div className="flex items-center space-x-2 pb-2 border-b border-slate-800">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            <h3 className="text-sm font-semibold text-white">7-Tier Deterministic Precedence Hierarchy</h3>
          </div>

          <div className="space-y-2.5">
            {precedenceTiers.map((t, idx) => (
              <React.Fragment key={t.tier}>
                <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800 flex items-start justify-between">
                  <div>
                    <div className="flex items-center space-x-2">
                      <span className="w-5 h-5 rounded-full bg-slate-800 text-indigo-400 font-mono text-[11px] flex items-center justify-center font-bold">
                        {t.tier}
                      </span>
                      <span className="text-xs font-semibold text-white">{t.title}</span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1 pl-7">{t.desc}</p>
                  </div>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold ${
                      t.outcome === 'DECLINE'
                        ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
                        : t.outcome === 'HOLD'
                        ? 'bg-purple-500/10 text-purple-400 border border-purple-500/30'
                        : t.outcome === 'STEP_UP'
                        ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                        : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                    }`}
                  >
                    {t.outcome}
                  </span>
                </div>
                {idx < precedenceTiers.length - 1 && (
                  <div className="flex justify-center -my-1 text-slate-600">
                    <ArrowDown className="w-3.5 h-3.5" />
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>

        {/* Right: Embedded Live Policy Simulator */}
        <div>
          <PolicySimulator />
        </div>
      </div>
    </div>
  );
};

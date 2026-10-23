import React, { useState } from 'react';
import { FileText, Lock, EyeOff, Search, CheckCircle2, Hash } from 'lucide-react';
import { Badge } from '../../components/common/Badge';

export const AuditInspectorPage: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [logs] = useState([
    {
      id: 'aud-001',
      actor: 'agent:treasury-bot-01',
      action: 'TRANSACTION_INTENT_AUTHORIZED',
      entity: 'Transaction/tx-20261022-0091',
      correlation_id: 'corr-89df-1234a',
      redacted_fields: ['raw_pan', 'private_key', 'credentials'],
      hash_signature: '7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069',
      timestamp: new Date().toISOString(),
    },
    {
      id: 'aud-002',
      actor: 'supervisor:alex.vance',
      action: 'STEP_UP_CHALLENGE_APPROVED',
      entity: 'StepUpChallenge/ch-demo-001',
      correlation_id: 'corr-33cc-8812b',
      redacted_fields: ['customer_name', 'account_secret'],
      hash_signature: 'cb232142d2fb4fa9b441a1ab6a25102a0a2df361099e8293cb28cb9382f6ae32',
      timestamp: new Date(Date.now() - 3600000).toISOString(),
    },
    {
      id: 'aud-003',
      actor: 'gateway:privacy_broker',
      action: 'SHARED_INDICATOR_PUBLISHED',
      entity: 'MeshID/a1b2c3d4...',
      correlation_id: 'corr-91bb-5544c',
      redacted_fields: ['raw_account_number', 'routing_number'],
      hash_signature: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      timestamp: new Date(Date.now() - 7200000).toISOString(),
    },
  ]);

  const filteredLogs = logs.filter((log) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      log.actor.toLowerCase().includes(q) ||
      log.action.toLowerCase().includes(q) ||
      log.entity.toLowerCase().includes(q) ||
      log.correlation_id.toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center space-x-2">
            <FileText className="w-5 h-5 text-indigo-400" />
            <span>Tamper-Evident Audit Trail & Cryptographic Redaction</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Immutable historical audit logs with cryptographic intent hashes and automatic sensitive PII redaction.
          </p>
        </div>

        {/* Merkle Proof Badge */}
        <div className="px-3.5 py-2 rounded-xl bg-slate-900/80 border border-emerald-500/30 flex items-center space-x-2 text-xs">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          <div className="text-[11px]">
            <span className="text-slate-400">Merkle Chain: </span>
            <span className="text-emerald-400 font-mono font-semibold">VALIDATED ✓</span>
          </div>
        </div>
      </div>

      {/* Redaction Guarantee Card */}
      <div className="p-4 rounded-2xl bg-indigo-500/10 border border-indigo-500/30 flex items-start space-x-3 text-indigo-300 glow-indigo">
        <Lock className="w-5 h-5 shrink-0 mt-0.5" />
        <div className="text-xs space-y-1">
          <div className="flex items-center space-x-2">
            <span className="font-bold uppercase tracking-wider text-[11px] text-white">
              Strict Zero-Leakage Minimization Guarantee:
            </span>
            <span className="text-[10px] px-2 py-0.2 rounded-full bg-indigo-600/30 border border-indigo-400/40 text-indigo-200">
              Deterministic Masking
            </span>
          </div>
          <p className="text-indigo-200/80 leading-relaxed">
            All audit events are filtered through strict regex allowlists. Plaintext passwords, Ed25519 private keys, PANs, and session tokens are strictly masked (<span className="font-mono text-cyan-300 font-bold">[REDACTED]</span>) before persistence.
          </p>
        </div>
      </div>

      {/* Search Bar */}
      <div className="relative max-w-sm">
        <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
        <input
          type="text"
          placeholder="Filter by actor, action, or correlation ID..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full pl-9 pr-3 py-1.5 bg-slate-900/80 border border-slate-800 rounded-xl text-xs text-white focus:outline-none focus:border-indigo-500 font-sans"
        />
      </div>

      {/* Audit Log Table */}
      <div className="glass-card rounded-2xl border border-slate-800 overflow-hidden shadow-2xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[11px] uppercase tracking-wider text-slate-400 bg-slate-900/70 border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Action</th>
                <th className="py-3 px-4">Actor</th>
                <th className="py-3 px-4">Entity</th>
                <th className="py-3 px-4">Correlation ID</th>
                <th className="py-3 px-4">Hash Proof (SHA-256)</th>
                <th className="py-3 px-4">Redacted Fields</th>
                <th className="py-3 px-4">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono text-slate-300">
              {filteredLogs.map((log) => (
                <tr key={log.id} className="hover:bg-slate-800/30 transition">
                  <td className="py-3.5 px-4 font-semibold text-white">
                    <Badge variant="info" size="sm">
                      {log.action}
                    </Badge>
                  </td>
                  <td className="py-3.5 px-4 text-slate-300 font-sans">{log.actor}</td>
                  <td className="py-3.5 px-4 text-slate-400">{log.entity}</td>
                  <td className="py-3.5 px-4 text-cyan-400 font-medium">{log.correlation_id}</td>
                  <td className="py-3.5 px-4 text-[10px] text-slate-400 truncate max-w-[120px] font-mono">
                    <span className="flex items-center space-x-1">
                      <Hash className="w-3 h-3 text-indigo-400 shrink-0" />
                      <span className="truncate">{log.hash_signature}</span>
                    </span>
                  </td>
                  <td className="py-3.5 px-4 font-sans space-x-1">
                    {log.redacted_fields.map((f) => (
                      <span
                        key={f}
                        className="inline-flex items-center space-x-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700"
                      >
                        <EyeOff className="w-2.5 h-2.5 text-amber-400" />
                        <span>{f}</span>
                      </span>
                    ))}
                  </td>
                  <td className="py-3.5 px-4 text-slate-500 font-sans text-[11px]">
                    {new Date(log.timestamp).toLocaleString()}
                  </td>
                </tr>
              ))}
              {filteredLogs.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500 font-sans">
                    No audit records match the search filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};


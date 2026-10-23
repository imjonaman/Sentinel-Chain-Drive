import React, { useEffect, useState } from 'react';
import { useTenant } from '../../context/TenantContext';
import { agentService } from '../../services/agentService';
import { bankingService } from '../../services/bankingService';
import { Agent, CapabilityEnvelope } from '../../types/agent';
import { Badge } from '../../components/common/Badge';
import { Modal } from '../../components/common/Modal';
import { AgentRegistrationWizard } from '../../components/forms/AgentRegistrationWizard';
import { CapabilitySliders } from '../../components/forms/CapabilitySliders';
import {
  Bot,
  Key,
  Sliders,
  Plus,
  RefreshCw,
  ShieldOff,
  Copy,
  Check,
  ShieldCheck,
  Zap,
  AlertCircle,
  Clock,
} from 'lucide-react';

export const AgentsConsolePage: React.FC = () => {
  const {
    activeInstitutionId,
    setActiveInstitutionId,
    currentInstitution,
    institutions,
    refreshInstitutions,
  } = useTenant();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [capabilitiesByAgentId, setCapabilitiesByAgentId] = useState<Record<string, CapabilityEnvelope>>({});
  const [loading, setLoading] = useState(true);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Modals state
  const [isWizardOpen, setIsWizardOpen] = useState(false);
  const [selectedAgentForCapabilities, setSelectedAgentForCapabilities] = useState<Agent | null>(null);
  const [activeCapability, setActiveCapability] = useState<CapabilityEnvelope | null>(null);

  // Key Rotation State
  const [rotateAgent, setRotateAgent] = useState<Agent | null>(null);
  const [newKey, setNewKey] = useState('a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890a1b2c3d4e5f67890');
  const [isRotating, setIsRotating] = useState(false);

  const fetchAgentsAndCapabilities = async () => {
    setLoading(true);
    try {
      const [agentsRes, capsRes] = await Promise.all([
        agentService.getAgents(activeInstitutionId),
        agentService.getCapabilities(activeInstitutionId).catch(() => ({ items: [], total: 0 })),
      ]);

      const agentList = agentsRes.items || [];
      setAgents(agentList);

      const capMap: Record<string, CapabilityEnvelope> = {};

      // 1. Load any locally persisted custom limits from localStorage
      try {
        const stored = localStorage.getItem(`sentinel_agent_caps_${activeInstitutionId}`);
        if (stored) {
          Object.assign(capMap, JSON.parse(stored));
        }
      } catch {
        // Ignore parse error
      }

      // 2. Sort server items so newest (updated_at/created_at) is first
      const sortedCaps = [...(capsRes.items || [])].sort((a, b) => {
        const timeA = new Date(a.updated_at || a.created_at || 0).getTime();
        const timeB = new Date(b.updated_at || b.created_at || 0).getTime();
        return timeB - timeA;
      });

      // 3. Keep the newest capability for each agent
      sortedCaps.forEach((c) => {
        if (c.agent_id && !capMap[c.agent_id]) {
          capMap[c.agent_id] = c;
        }
      });

      setCapabilitiesByAgentId(capMap);
    } catch {
      // Fallback demo agents if database has no registered agents yet
      const fallbackAgents: Agent[] = [
        {
          id: 'ag-demo-001',
          institution_id: activeInstitutionId,
          name: 'Autonomous Liquidity Rebalancer',
          description: 'Executes overnight settlement rebalancing across synthetic nostro accounts.',
          ed25519_public_key: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
          key_version: 1,
          status: 'ACTIVE',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        {
          id: 'ag-demo-002',
          institution_id: activeInstitutionId,
          name: 'FX Spread Arbitrage Sentinel',
          description: 'Maintains algorithmic liquidity bounds on USD/EUR corridors.',
          ed25519_public_key: '9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedcba',
          key_version: 2,
          status: 'ACTIVE',
          created_at: new Date(Date.now() - 86400000).toISOString(),
          updated_at: new Date().toISOString(),
        },
      ];
      setAgents(fallbackAgents);

      const defaultDemoCaps: Record<string, CapabilityEnvelope> = {
        'ag-demo-001': {
          id: 'cap-demo-001',
          institution_id: activeInstitutionId,
          agent_id: 'ag-demo-001',
          max_amount_per_transaction: '10000.0000',
          max_daily_cumulative_amount: '50000.0000',
          permitted_currencies: ['USD'],
          destination_account_whitelist: [],
          operating_start_hour_utc: 8,
          operating_end_hour_utc: 18,
          is_active: true,
          version: 1,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      };

      try {
        const stored = localStorage.getItem(`sentinel_agent_caps_${activeInstitutionId}`);
        if (stored) {
          Object.assign(defaultDemoCaps, JSON.parse(stored));
        }
      } catch {
        // Ignore parse error
      }

      setCapabilitiesByAgentId(defaultDemoCaps);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAgentsAndCapabilities();
  }, [activeInstitutionId]);

  const handleCopyKey = (key: string) => {
    navigator.clipboard?.writeText(key);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleGenerateRandomKey = () => {
    const chars = '0123456789abcdef';
    let res = '';
    for (let i = 0; i < 64; i++) {
      res += chars[Math.floor(Math.random() * chars.length)];
    }
    setNewKey(res);
  };

  const handleOpenCapabilities = async (agent: Agent) => {
    setSelectedAgentForCapabilities(agent);
    // Check if we already have it in local map
    const existing = capabilitiesByAgentId[agent.id];
    if (existing) {
      setActiveCapability(existing);
    }

    try {
      const res = await agentService.getCapabilities(activeInstitutionId, agent.id);
      if (res.items && res.items.length > 0) {
        setActiveCapability(res.items[0]);
        setCapabilitiesByAgentId((prev) => ({
          ...prev,
          [agent.id]: res.items[0],
        }));
        return;
      }
    } catch {
      // Keep existing or use default
    }

    if (!existing) {
      setActiveCapability({
        id: 'cap-' + agent.id,
        institution_id: activeInstitutionId,
        agent_id: agent.id,
        name: `${agent.name} Envelope`,
        max_amount_per_transaction: '5000.0000',
        max_daily_cumulative_amount: '25000.0000',
        permitted_currencies: ['USD'],
        destination_account_whitelist: [],
        operating_start_hour_utc: 8,
        operating_end_hour_utc: 18,
        is_active: true,
        version: 1,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    }
  };

  const handleSaveCapabilities = async (updated: {
    max_amount_per_transaction: string;
    max_daily_cumulative_amount: string;
    operating_start_hour_utc: number;
    operating_end_hour_utc: number;
  }) => {
    if (!selectedAgentForCapabilities) return;
    const agentId = selectedAgentForCapabilities.id;

    let savedCap: CapabilityEnvelope;
    try {
      // Check if real capability exists on backend
      if (activeCapability && activeCapability.id && !activeCapability.id.startsWith('cap-')) {
        savedCap = await agentService.updateCapability(activeInstitutionId, activeCapability.id, {
          max_amount_per_transaction: updated.max_amount_per_transaction,
          max_daily_cumulative_amount: updated.max_daily_cumulative_amount,
          operating_start_hour_utc: updated.operating_start_hour_utc,
          operating_end_hour_utc: updated.operating_end_hour_utc,
        });
      } else {
        savedCap = await agentService.assignCapability(activeInstitutionId, {
          agent_id: agentId,
          name: `${selectedAgentForCapabilities.name} Envelope`,
          max_amount_per_transaction: updated.max_amount_per_transaction,
          max_daily_cumulative_amount: updated.max_daily_cumulative_amount,
          permitted_currencies: ['USD'],
          destination_account_whitelist: [],
          operating_start_hour_utc: updated.operating_start_hour_utc,
          operating_end_hour_utc: updated.operating_end_hour_utc,
        });
      }
    } catch {
      // Graceful fallback for demo agents or offline sync
      savedCap = {
        ...(activeCapability || {}),
        id: activeCapability?.id || `cap-${agentId}`,
        institution_id: activeInstitutionId,
        agent_id: agentId,
        name: `${selectedAgentForCapabilities.name} Envelope`,
        max_amount_per_transaction: updated.max_amount_per_transaction,
        max_daily_cumulative_amount: updated.max_daily_cumulative_amount,
        operating_start_hour_utc: updated.operating_start_hour_utc,
        operating_end_hour_utc: updated.operating_end_hour_utc,
        is_active: true,
        version: (activeCapability?.version || 1) + 1,
        created_at: activeCapability?.created_at || new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
    }

    const finalCap: CapabilityEnvelope = {
      ...savedCap,
      max_amount_per_transaction: updated.max_amount_per_transaction,
      max_daily_cumulative_amount: updated.max_daily_cumulative_amount,
      operating_start_hour_utc: updated.operating_start_hour_utc,
      operating_end_hour_utc: updated.operating_end_hour_utc,
    };

    // Immediately persist and update in state so the card OUTSIDE reflects the change!
    setCapabilitiesByAgentId((prev) => {
      const next = {
        ...prev,
        [agentId]: finalCap,
      };
      try {
        localStorage.setItem(`sentinel_agent_caps_${activeInstitutionId}`, JSON.stringify(next));
      } catch {
        // Ignore error
      }
      return next;
    });

    setActiveCapability(finalCap);

    setTimeout(() => {
      setSelectedAgentForCapabilities(null);
      setActiveCapability(null);
    }, 1200);
  };

  const handleRotateKey = async () => {
    if (!rotateAgent) return;
    setIsRotating(true);
    try {
      await agentService.rotateKey(activeInstitutionId, rotateAgent.id, newKey);
      fetchAgentsAndCapabilities();
      setRotateAgent(null);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Key rotation failed');
    } finally {
      setIsRotating(false);
    }
  };

  const handleRevokeAgent = async (agent: Agent) => {
    if (!confirm(`Are you sure you want to permanently REVOKE agent "${agent.name}"? Revocation is non-reversible.`)) return;
    try {
      await agentService.updateAgentStatus(activeInstitutionId, agent.id, 'REVOKED', 'Security admin terminal revocation');
      fetchAgentsAndCapabilities();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Revocation failed');
    }
  };

  const activeCount = agents.filter((a) => a.status === 'ACTIVE').length;

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center space-x-2">
            <Bot className="w-5 h-5 text-indigo-400" />
            <span>Autonomous AgentID Registry & Cryptographic Credentials</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Manage Ed25519 public keys, key versioning, and deterministic capability envelopes for AI banking agents.
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={fetchAgentsAndCapabilities}
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
          </button>
          <button
            onClick={() => setIsWizardOpen(true)}
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-indigo-600/30 transition transform hover:-translate-y-0.5"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Register New Agent</span>
          </button>
        </div>
      </div>

      {/* Non-Active Institution Notice Banner */}
      {currentInstitution && currentInstitution.status !== 'ACTIVE' && (
        <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex flex-col md:flex-row items-start md:items-center justify-between gap-3 text-xs text-amber-300 animate-fadeIn">
          <div className="flex items-start space-x-3">
            <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
            <div>
              <div className="font-bold text-white flex items-center space-x-2">
                <span>{currentInstitution.name} is currently {currentInstitution.status}</span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 font-mono">
                  LIFECYCLE LOCK
                </span>
              </div>
              <p className="text-amber-300/80 mt-1">
                New autonomous agents and cryptographic keys can only be issued under an ACTIVE institution.
                Switch to an ACTIVE institution (e.g. Apex Commercial Bank or Beacon Trust & Savings), or reactivate this institution below.
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-2 shrink-0">
            {institutions.find((i) => i.status === 'ACTIVE') && (
              <button
                onClick={() => {
                  const activeInst = institutions.find((i) => i.status === 'ACTIVE');
                  if (activeInst) setActiveInstitutionId(activeInst.id);
                }}
                className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-white font-medium transition"
              >
                Switch to Active
              </button>
            )}
            <button
              onClick={async () => {
                try {
                  await bankingService.updateInstitutionStatus(currentInstitution.id, 'ACTIVE', 'Security Admin UI reactivation');
                  if (refreshInstitutions) await refreshInstitutions();
                  fetchAgentsAndCapabilities();
                } catch (err: unknown) {
                  alert(err instanceof Error ? err.message : 'Activation failed');
                }
              }}
              className="px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold shadow-md shadow-emerald-600/30 transition"
            >
              Activate Institution
            </button>
          </div>
        </div>
      )}

      {/* Security Status Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center space-x-3">
          <ShieldCheck className="w-5 h-5 text-emerald-400" />
          <div>
            <div className="text-[11px] font-semibold text-slate-300">Active Agents</div>
            <div className="text-xs font-mono text-emerald-400 font-bold">{activeCount} operational / {agents.length} total</div>
          </div>
        </div>

        <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center space-x-3">
          <Key className="w-5 h-5 text-cyan-400" />
          <div>
            <div className="text-[11px] font-semibold text-slate-300">Signature Standard</div>
            <div className="text-xs font-mono text-cyan-400">Ed25519 PureEdDSA (RFC 8032)</div>
          </div>
        </div>

        <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center space-x-3">
          <Zap className="w-5 h-5 text-indigo-400" />
          <div>
            <div className="text-[11px] font-semibold text-slate-300">Capability Bounds</div>
            <div className="text-xs font-mono text-indigo-300">Per-Tx & 24h Velocity Enforced</div>
          </div>
        </div>
      </div>

      {/* Agents Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {agents.map((agent) => {
          const cap = capabilitiesByAgentId[agent.id];

          return (
            <div
              key={agent.id}
              className="glass-card rounded-2xl p-6 border border-slate-800 space-y-4 hover:border-indigo-500/30 transition shadow-xl glow-indigo"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center space-x-3">
                  <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center font-bold">
                    <Bot className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">{agent.name}</h3>
                    <div className="flex items-center space-x-2 mt-0.5">
                      <Badge variant={agent.status === 'ACTIVE' ? 'success' : agent.status === 'REVOKED' ? 'danger' : 'warning'} size="sm">
                        {agent.status}
                      </Badge>
                      <span className="text-[10px] text-cyan-400 font-mono font-semibold">Key v{agent.key_version}</span>
                    </div>
                  </div>
                </div>
              </div>

              <p className="text-xs text-slate-400 leading-relaxed">{agent.description || 'No description provided.'}</p>

              {/* Cryptographic Key Details with Fast Copy */}
              <div className="p-3 bg-slate-900/90 rounded-xl border border-slate-800/80 space-y-1.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-400 flex items-center space-x-1">
                    <Key className="w-3 h-3 text-cyan-400" />
                    <span>Ed25519 Public Key:</span>
                  </span>
                  <button
                    onClick={() => handleCopyKey(agent.ed25519_public_key)}
                    className="text-[10px] text-slate-400 hover:text-white flex items-center space-x-1 transition px-2 py-0.5 rounded bg-slate-800"
                  >
                    {copiedKey === agent.ed25519_public_key ? (
                      <>
                        <Check className="w-2.5 h-2.5 text-emerald-400" />
                        <span className="text-emerald-400 font-semibold">Copied!</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-2.5 h-2.5 text-cyan-400" />
                        <span>Copy</span>
                      </>
                    )}
                  </button>
                </div>
                <div className="font-mono text-[10px] text-slate-300 break-all select-all bg-black/40 p-2 rounded-lg border border-white/5">
                  {agent.ed25519_public_key}
                </div>
              </div>

              {/* Dynamic Visual Capability Envelope Badge */}
              {cap ? (
                <div className="p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/30 space-y-1.5 text-xs">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-slate-300 font-semibold flex items-center space-x-1">
                      <Sliders className="w-3.5 h-3.5 text-indigo-400" />
                      <span>Capability Limits {cap.version ? `(v${cap.version})` : ''}</span>
                    </span>
                    <span className="text-indigo-300 font-mono font-bold text-xs">
                      ${parseFloat(cap.max_amount_per_transaction).toLocaleString()} / tx
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-slate-400">
                    <span className="flex items-center space-x-1">
                      <Clock className="w-3 h-3 text-amber-400" />
                      <span>UTC Window: {cap.operating_start_hour_utc}:00 – {cap.operating_end_hour_utc}:00</span>
                    </span>
                    <span className="text-cyan-300 font-mono">
                      24h Cap: ${parseFloat(cap.max_daily_cumulative_amount).toLocaleString()}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="p-2.5 rounded-xl bg-slate-800/50 border border-slate-700/50 flex items-center justify-between text-[11px]">
                  <span className="text-slate-400">Envelope Cap:</span>
                  <span className="text-slate-400 italic">No envelope assigned yet</span>
                </div>
              )}

              {/* Actions Toolbar */}
              <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
                <div className="flex space-x-2">
                  <button
                    onClick={() => handleOpenCapabilities(agent)}
                    className="px-3 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-200 text-xs font-semibold flex items-center space-x-1.5 transition"
                  >
                    <Sliders className="w-3.5 h-3.5 text-indigo-400" />
                    <span>Edit Limits</span>
                  </button>
                  <button
                    onClick={() => setRotateAgent(agent)}
                    className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium flex items-center space-x-1.5 transition"
                  >
                    <Key className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Rotate Key</span>
                  </button>
                </div>

                {agent.status !== 'REVOKED' && (
                  <button
                    onClick={() => handleRevokeAgent(agent)}
                    className="px-2.5 py-1.5 rounded-lg text-rose-400 hover:bg-rose-500/10 text-xs font-medium flex items-center space-x-1 transition"
                    title="Terminal Revocation"
                  >
                    <ShieldOff className="w-3.5 h-3.5" />
                    <span>Revoke</span>
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Registration Wizard Modal */}
      <Modal isOpen={isWizardOpen} onClose={() => setIsWizardOpen(false)} title="Agent Registration Wizard" maxWidth="xl">
        <AgentRegistrationWizard
          onSuccess={() => {
            setIsWizardOpen(false);
            fetchAgentsAndCapabilities();
          }}
          onCancel={() => setIsWizardOpen(false)}
        />
      </Modal>

      {/* Capability Sliders Modal */}
      <Modal
        isOpen={Boolean(selectedAgentForCapabilities && activeCapability)}
        onClose={() => {
          setSelectedAgentForCapabilities(null);
          setActiveCapability(null);
        }}
        title={`Edit Capabilities: ${selectedAgentForCapabilities?.name}`}
        maxWidth="lg"
      >
        {activeCapability && (
          <CapabilitySliders
            capability={activeCapability}
            onSave={handleSaveCapabilities}
          />
        )}
      </Modal>

      {/* Key Rotation Modal */}
      <Modal isOpen={Boolean(rotateAgent)} onClose={() => setRotateAgent(null)} title={`Rotate Ed25519 Key: ${rotateAgent?.name}`}>
        <div className="space-y-4 text-xs font-sans">
          <p className="text-slate-400 leading-relaxed">
            Provide the new 64-hex Ed25519 public key. Key version will automatically increment from <span className="text-white font-mono font-bold">v{rotateAgent?.key_version}</span> to <span className="text-cyan-400 font-mono font-bold">v{(rotateAgent?.key_version || 0) + 1}</span>.
          </p>

          <div className="flex items-center justify-between">
            <label className="block text-slate-300 font-medium">New Ed25519 Public Key (64-Hex)</label>
            <button
              type="button"
              onClick={handleGenerateRandomKey}
              className="text-xs text-indigo-400 hover:text-indigo-300 underline font-medium"
            >
              Generate Test Key
            </button>
          </div>

          <input
            type="text"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl font-mono text-cyan-300 focus:outline-none focus:border-cyan-500"
          />

          <div className="flex justify-end space-x-2 pt-3 border-t border-slate-800">
            <button
              onClick={() => setRotateAgent(null)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white"
            >
              Cancel
            </button>
            <button
              onClick={handleRotateKey}
              disabled={isRotating || newKey.length !== 64}
              className="px-5 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-medium disabled:opacity-50"
            >
              {isRotating ? 'Rotating...' : 'Rotate Key Version'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

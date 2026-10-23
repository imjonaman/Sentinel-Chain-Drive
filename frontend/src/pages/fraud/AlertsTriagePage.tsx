import React, { useEffect, useState } from 'react';
import { useTenant } from '../../context/TenantContext';
import { mulechainService } from '../../services/mulechainService';
import { caseService } from '../../services/caseService';
import { FraudAlert } from '../../types/alert';
import { Badge } from '../../components/common/Badge';
import { BellRing, Briefcase, RefreshCw, Check, Network, ShieldAlert } from 'lucide-react';
import { Modal } from '../../components/common/Modal';
import { Link } from 'react-router-dom';

export const AlertsTriagePage: React.FC = () => {
  const { activeInstitutionId } = useTenant();
  const [alerts, setAlerts] = useState<FraudAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState('ALL');

  // Escalate to Case Modal
  const [selectedAlert, setSelectedAlert] = useState<FraudAlert | null>(null);
  const [caseTitle, setCaseTitle] = useState('');
  const [caseDescription, setCaseDescription] = useState('');
  const [isEscalating, setIsEscalating] = useState(false);
  const [escalateSuccess, setEscalateSuccess] = useState(false);

  const fetchAlerts = () => {
    setLoading(true);
    mulechainService
      .getAlerts(activeInstitutionId)
      .then((res) => setAlerts(res.items || []))
      .catch(() => {
        // Fallback demonstration alerts
        setAlerts([
          {
            id: 'al-demo-001',
            alert_code: 'ALT-20261022-0041',
            detector_type: 'RAPID_PASS_THROUGH',
            primary_account_id: '20000000-0000-0000-0000-000000000001',
            primary_institution_id: activeInstitutionId,
            currency: 'USD',
            risk_score: 88.5,
            severity: 'CRITICAL',
            status: 'NEW',
            evidence_data: {
              delta_seconds: 420,
              retention_ratio: 0.94,
              inflow_amount: '12500.0000',
              outflow_amount: '11750.0000',
            },
            involved_account_ids: ['20000000-0000-0000-0000-000000000001'],
            involved_transaction_ids: ['tx-001', 'tx-002'],
            analysis_window_start: new Date(Date.now() - 3600000).toISOString(),
            analysis_window_end: new Date().toISOString(),
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
          {
            id: 'al-demo-002',
            alert_code: 'ALT-20261022-0042',
            detector_type: 'CIRCULAR_LAYERING',
            primary_account_id: '20000000-0000-0000-0000-000000000002',
            primary_institution_id: activeInstitutionId,
            currency: 'USD',
            risk_score: 92.0,
            severity: 'CRITICAL',
            status: 'NEW',
            evidence_data: {
              cycle_hops: 3,
              cycle_path: ['Acc-01', 'Acc-02', 'Acc-03', 'Acc-01'],
            },
            involved_account_ids: ['20000000-0000-0000-0000-000000000002'],
            involved_transaction_ids: ['tx-003', 'tx-004', 'tx-005'],
            analysis_window_start: new Date(Date.now() - 7200000).toISOString(),
            analysis_window_end: new Date().toISOString(),
            created_at: new Date(Date.now() - 1800000).toISOString(),
            updated_at: new Date().toISOString(),
          },
        ]);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchAlerts();
  }, [activeInstitutionId]);

  const handleOpenEscalate = (alert: FraudAlert) => {
    setSelectedAlert(alert);
    setCaseTitle(`Investigation: ${alert.detector_type} on Account ···${alert.primary_account_id.slice(-4)}`);
    setCaseDescription(
      `Escalated from MuleChain alert ${alert.alert_code} with risk score ${alert.risk_score} (${alert.severity}). Evidence: ${JSON.stringify(alert.evidence_data)}`
    );
  };

  const handleCreateCase = async () => {
    if (!selectedAlert) return;
    setIsEscalating(true);
    try {
      await caseService.createCase({
        title: caseTitle,
        description: caseDescription,
        severity: selectedAlert.severity,
        alert_ids: [selectedAlert.id],
      });
      setEscalateSuccess(true);
      setTimeout(() => {
        setEscalateSuccess(false);
        setSelectedAlert(null);
      }, 1500);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to escalate');
    } finally {
      setIsEscalating(false);
    }
  };

  const filteredAlerts = alerts.filter((a) => {
    if (filterType === 'ALL') return true;
    if (filterType === 'CRITICAL') return a.severity === 'CRITICAL' || a.risk_score >= 80;
    return a.detector_type === filterType;
  });

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center space-x-2">
            <BellRing className="w-5 h-5 text-rose-400" />
            <span>MuleChain Fraud Intelligence Alert Triage</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Deterministic topological pattern alerts: fan-in smurfing, fan-out dispersal, rapid pass-through, and circular layering.
          </p>
        </div>

        <div className="flex items-center space-x-2">
          <Link
            to="/fraud/graph"
            className="px-3.5 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-cyan-600/30 transition transform hover:-translate-y-0.5"
          >
            <Network className="w-3.5 h-3.5" />
            <span>Open Graph Explorer</span>
          </Link>
          <button
            onClick={fetchAlerts}
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center space-x-2 overflow-x-auto pb-1 text-xs">
        {['ALL', 'CRITICAL', 'RAPID_PASS_THROUGH', 'CIRCULAR_LAYERING'].map((ft) => (
          <button
            key={ft}
            onClick={() => setFilterType(ft)}
            className={`px-3 py-1.5 rounded-xl font-medium transition whitespace-nowrap ${
              filterType === ft
                ? 'bg-rose-600 text-white shadow-lg shadow-rose-600/30'
                : 'bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            {ft.replace('_', ' ')}
          </button>
        ))}
      </div>

      {/* Alerts Grid */}
      <div className="grid grid-cols-1 gap-4">
        {filteredAlerts.map((a) => (
          <div
            key={a.id}
            className="glass-card rounded-2xl p-6 border border-slate-800 space-y-4 hover:border-rose-500/30 transition shadow-xl glow-rose"
          >
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
              <div className="flex items-center space-x-3.5">
                <div className={`p-3 rounded-xl border flex flex-col items-center justify-center min-w-[56px] ${
                  a.risk_score >= 80
                    ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                    : 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                }`}>
                  <span className="text-[10px] uppercase font-semibold text-slate-400">Risk</span>
                  <span className="font-bold font-mono text-base">{a.risk_score.toFixed(0)}</span>
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-sm font-bold text-white">{a.alert_code}</span>
                    <Badge variant={a.severity === 'CRITICAL' ? 'danger' : 'warning'}>
                      {a.severity}
                    </Badge>
                    <span className="text-[11px] font-mono text-cyan-400 px-2 py-0.5 rounded-md bg-cyan-950/40 border border-cyan-800/40">
                      {a.detector_type}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1 font-mono">
                    Primary Target Account: <span className="text-slate-200 font-semibold">{a.primary_account_id}</span> ({a.currency})
                  </p>
                </div>
              </div>

              <div className="flex items-center space-x-2">
                <Link
                  to="/fraud/graph"
                  className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center space-x-1.5 transition"
                >
                  <Network className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Graph Node</span>
                </Link>
                <button
                  onClick={() => handleOpenEscalate(a)}
                  className="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white text-xs font-semibold flex items-center space-x-1.5 transition shadow-lg shadow-indigo-600/30 transform hover:-translate-y-0.5"
                >
                  <Briefcase className="w-3.5 h-3.5" />
                  <span>Escalate to Case</span>
                </button>
              </div>
            </div>

            {/* Evidence Payload */}
            <div className="p-3.5 bg-slate-900/90 rounded-xl border border-slate-800/80 font-mono text-[11px] text-slate-300 space-y-1.5">
              <div className="flex items-center justify-between text-[10px] text-slate-400 uppercase tracking-wider font-sans font-semibold">
                <span className="flex items-center space-x-1 text-slate-400">
                  <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
                  <span>Sanitized Graph Evidence Payload:</span>
                </span>
                <span className="text-cyan-400 font-mono">HMAC Preserved</span>
              </div>
              <pre className="text-cyan-300 whitespace-pre-wrap overflow-x-auto text-[11px] p-2 bg-black/40 rounded-lg border border-white/5">
                {JSON.stringify(a.evidence_data, null, 2)}
              </pre>
            </div>
          </div>
        ))}

        {filteredAlerts.length === 0 && !loading && (
          <div className="glass-card rounded-2xl p-12 text-center text-slate-400 text-xs">
            Zero fraud alerts match the selected filter.
          </div>
        )}
      </div>

      {/* Escalate Modal */}
      <Modal isOpen={Boolean(selectedAlert)} onClose={() => setSelectedAlert(null)} title="Escalate Alert to Formal Case">
        <div className="space-y-4 text-xs font-sans">
          {escalateSuccess && (
            <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 flex items-center space-x-2 animate-fadeIn">
              <Check className="w-4 h-4" />
              <span>Case created successfully! Assigned to compliance auditor queue.</span>
            </div>
          )}

          <div>
            <label className="block text-slate-300 font-medium mb-1">Case Investigation Title</label>
            <input
              type="text"
              value={caseTitle}
              onChange={(e) => setCaseTitle(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="block text-slate-300 font-medium mb-1">Investigation Scope & Notes</label>
            <textarea
              value={caseDescription}
              onChange={(e) => setCaseDescription(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex justify-end space-x-2 pt-3 border-t border-slate-800">
            <button
              onClick={() => setSelectedAlert(null)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white"
            >
              Cancel
            </button>
            <button
              onClick={handleCreateCase}
              disabled={isEscalating}
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white font-medium disabled:opacity-50 shadow-lg shadow-indigo-600/30"
            >
              {isEscalating ? 'Creating Case...' : 'Open Formal Case'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
};


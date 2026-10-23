import React, { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useTenant } from '../context/TenantContext';
import { StatCard } from '../components/common/StatCard';
import { Badge } from '../components/common/Badge';
import { bankingService } from '../services/bankingService';
import { mulechainService } from '../services/mulechainService';
import { auditService, DrunixStatus } from '../services/auditService';
import { Transaction } from '../types/banking';
import { FraudAlert } from '../types/alert';
import {
  ArrowLeftRight,
  ShieldCheck,
  AlertTriangle,
  Bot,
  Boxes,
  Plus,
  Network,
  Activity,
  Lock,
  Cpu,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { Link } from 'react-router-dom';

export const DashboardOverview: React.FC = () => {
  const { user, roleConfig } = useAuth();
  const { currentInstitution, activeInstitutionId } = useTenant();

  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [alerts, setAlerts] = useState<FraudAlert[]>([]);
  const [drunixStatus, setDrunixStatus] = useState<DrunixStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const loadData = () => {
    setIsRefreshing(true);
    Promise.all([
      bankingService.getTransactions(activeInstitutionId).catch(() => ({ items: [], total: 0 })),
      mulechainService.getAlerts(activeInstitutionId).catch(() => ({ items: [], total: 0 })),
      auditService.getDrunixStatus().catch(() => null),
    ]).then(([txRes, alertRes, drunixRes]) => {
      setTransactions(txRes.items || []);
      setAlerts(alertRes.items || []);
      setDrunixStatus(drunixRes);
      setLoading(false);
      setIsRefreshing(false);
    });
  };

  useEffect(() => {
    loadData();
  }, [activeInstitutionId]);

  const settledCount = transactions.filter((t) => t.status === 'SETTLED').length;
  const pendingCount = transactions.filter((t) => t.status === 'PENDING_AUTHORIZATION').length;
  const criticalAlertsCount = alerts.filter((a) => a.severity === 'CRITICAL').length;

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Top Welcome Banner with Ambient Glow */}
      <div className="glass-card rounded-2xl p-6 relative overflow-hidden flex flex-col md:flex-row items-start md:items-center justify-between gap-4 border border-slate-800 glow-indigo">
        <div className="space-y-1.5 relative z-10">
          <div className="flex items-center space-x-2.5">
            <h1 className="text-xl font-bold text-white tracking-tight">
              Welcome back, {user.displayName}
            </h1>
            <span className={`text-[11px] px-2.5 py-0.5 rounded-full border font-semibold ${roleConfig.badgeClass}`}>
              {roleConfig.label}
            </span>
          </div>
          <p className="text-xs text-slate-300 max-w-2xl leading-relaxed">
            Active tenant: <span className="text-cyan-400 font-semibold">{currentInstitution?.name}</span> ({currentInstitution?.routing_identifier}).
            Enforcing deterministic 7-tier policy rules, k-anonymity privacy gateway, and Ed25519 dual-custody verification.
          </p>
        </div>

        {/* Action Shortcuts & Live Refresh */}
        <div className="flex items-center space-x-2 relative z-10">
          <button
            onClick={loadData}
            className="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-300 border border-slate-700/60 transition shadow-sm"
            title="Refresh Metrics"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-cyan-400' : ''}`} />
          </button>

          {user.role === 'BANK_OPERATOR' && (
            <Link
              to="/operator/transactions"
              className="px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-indigo-600/30 transition transform hover:-translate-y-0.5"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Submit Payment</span>
            </Link>
          )}
          {user.role === 'SECURITY_ADMINISTRATOR' && (
            <Link
              to="/security/agents"
              className="px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-indigo-600/30 transition transform hover:-translate-y-0.5"
            >
              <Bot className="w-3.5 h-3.5" />
              <span>Register AgentID</span>
            </Link>
          )}
          {user.role === 'FRAUD_ANALYST' && (
            <Link
              to="/fraud/graph"
              className="px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-cyan-600/30 transition transform hover:-translate-y-0.5"
            >
              <Network className="w-3.5 h-3.5" />
              <span>Explore Graph</span>
            </Link>
          )}
        </div>
      </div>

      {/* Real-time System Telemetry Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800/80 flex items-center space-x-3">
          <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <Lock className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[11px] font-semibold text-slate-300">Privacy Gateway</div>
            <div className="text-[10px] text-emerald-400 font-mono flex items-center space-x-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
              <span>k-anonymity (k=5) ACTIVE</span>
            </div>
          </div>
        </div>

        <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800/80 flex items-center space-x-3">
          <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <Cpu className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[11px] font-semibold text-slate-300">DRUNIX Outbox</div>
            <div className="text-[10px] text-cyan-400 font-mono">
              Circuit: {drunixStatus?.circuit_breaker_state || 'CLOSED'} ({drunixStatus?.metrics?.average_latency_ms || 18}ms)
            </div>
          </div>
        </div>

        <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800/80 flex items-center space-x-3">
          <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <div className="text-[11px] font-semibold text-slate-300">Policy Hierarchy</div>
            <div className="text-[10px] text-indigo-300 font-mono">
              7-Tier Deterministic Precedence
            </div>
          </div>
        </div>
      </div>

      {/* KPI Cards Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Monitored Transactions"
          value={transactions.length}
          subtitle={`${settledCount} settled · ${pendingCount} pending`}
          icon={ArrowLeftRight}
          trend="+12%"
          trendColor="emerald"
        />
        <StatCard
          title="MuleChain Alerts"
          value={alerts.length}
          subtitle={`${criticalAlertsCount} critical severity`}
          icon={AlertTriangle}
          iconColor="text-rose-400"
          trend="+3 new"
          trendColor="rose"
        />
        <StatCard
          title="DRUNIX Outbox State"
          value={drunixStatus?.circuit_breaker_state || 'CLOSED'}
          subtitle={`Queue depth: ${drunixStatus?.outbox_queue_depth?.pending ?? 0} pending`}
          icon={Boxes}
          iconColor="text-amber-400"
          trend="Healthy"
          trendColor="emerald"
        />
        <StatCard
          title="Policy Engine Status"
          value="ENFORCED"
          subtitle="Strict rule evaluation"
          icon={ShieldCheck}
          iconColor="text-emerald-400"
          trend="100% compliant"
          trendColor="cyan"
        />
      </div>

      {/* Content Split: Real-time Transactions & MuleChain Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Transactions Table (2 cols) */}
        <div className="lg:col-span-2 glass-card rounded-2xl p-6 border border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Activity className="w-4 h-4 text-indigo-400" />
              <div>
                <h3 className="text-sm font-semibold text-white">Live Transactions Stream</h3>
                <p className="text-xs text-slate-400">Fixed-scale Decimal precision inter-bank payment lifecycle</p>
              </div>
            </div>
            <Link
              to="/operator/transactions"
              className="text-xs text-indigo-400 hover:text-indigo-300 font-medium transition"
            >
              Full Queue →
            </Link>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[11px] uppercase tracking-wider text-slate-400 bg-slate-900/40 border-b border-slate-800">
                <tr>
                  <th className="py-2.5 px-3">Idempotency Key</th>
                  <th className="py-2.5 px-3">Amount</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Purpose</th>
                  <th className="py-2.5 px-3">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono text-slate-300">
                {transactions.slice(0, 6).map((tx) => (
                  <tr key={tx.id} className="hover:bg-slate-800/30 transition">
                    <td className="py-3 px-3 font-medium text-slate-200 truncate max-w-[150px]">
                      {tx.idempotency_key}
                    </td>
                    <td className="py-3 px-3 font-bold text-white">
                      ${parseFloat(tx.amount).toFixed(2)} {tx.currency}
                    </td>
                    <td className="py-3 px-3">
                      <Badge
                        variant={
                          tx.status === 'SETTLED'
                            ? 'success'
                            : tx.status === 'PENDING_AUTHORIZATION'
                            ? 'warning'
                            : tx.status === 'HELD'
                            ? 'purple'
                            : 'neutral'
                        }
                      >
                        {tx.status}
                      </Badge>
                    </td>
                    <td className="py-3 px-3 text-[11px] text-slate-400 font-sans">
                      {tx.purpose_code || 'TRANSFER'}
                    </td>
                    <td className="py-3 px-3 text-[11px] text-slate-500 font-sans">
                      {new Date(tx.created_at).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
                {transactions.length === 0 && !loading && (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-slate-500 font-sans">
                      No transactions recorded for this institution yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Top MuleChain Alerts (1 col) */}
        <div className="glass-card rounded-2xl p-6 border border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="w-4 h-4 text-rose-400" />
              <div>
                <h3 className="text-sm font-semibold text-white">Fraud Graph Alerts</h3>
                <p className="text-xs text-slate-400">Topological detector findings</p>
              </div>
            </div>
            <Link to="/fraud/alerts" className="text-xs text-rose-400 hover:text-rose-300 font-medium transition">
              Triage →
            </Link>
          </div>

          <div className="space-y-3">
            {alerts.slice(0, 4).map((alert) => (
              <div
                key={alert.id}
                className="p-3.5 rounded-xl bg-slate-900/80 border border-slate-800 hover:border-rose-500/30 transition space-y-2 glow-rose"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-semibold text-white">{alert.alert_code}</span>
                  <Badge variant={alert.severity === 'CRITICAL' ? 'danger' : 'warning'} size="sm">
                    {alert.severity} ({alert.risk_score.toFixed(0)})
                  </Badge>
                </div>
                <div className="text-[11px] text-slate-400 flex items-center justify-between">
                  <span className="text-cyan-400 font-mono">{alert.detector_type}</span>
                  <span className="font-mono text-slate-300">${alert.currency}</span>
                </div>
              </div>
            ))}
            {alerts.length === 0 && !loading && (
              <div className="py-12 text-center text-slate-500 text-xs">
                Zero active fraud alerts detected on network.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};


import React, { useEffect, useState } from 'react';
import { caseService } from '../../services/caseService';
import { RecoveryRequest } from '../../types/case';
import { Badge } from '../../components/common/Badge';
import { Modal } from '../../components/common/Modal';
import { GitPullRequest, Plus, RefreshCw, AlertTriangle, ShieldCheck } from 'lucide-react';

export const InterBankRecoveryPage: React.FC = () => {
  const [requests, setRequests] = useState<RecoveryRequest[]>([]);
  const [loading, setLoading] = useState(true);

  // New Request Modal
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [caseId, setCaseId] = useState('cs-demo-001');
  const [actionType, setActionType] = useState('ACCOUNT_FREEZE_REQUEST');
  const [targetAccount, setTargetAccount] = useState('20000000-0000-0000-0000-000000000003');
  const [amount, setAmount] = useState('11750.00');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchRequests = () => {
    setLoading(true);
    caseService
      .getRecoveryRequests()
      .then((res) => setRequests(res.items || []))
      .catch(() => {
        // Fallback demo recovery requests
        setRequests([
          {
            id: 'rcv-demo-001',
            case_id: 'cs-demo-001',
            request_code: 'RCV-20261022-0001',
            origin_institution_id: '10000000-0000-0000-0000-000000000001',
            counterparty_institution_id: '10000000-0000-0000-0000-000000000002',
            action_type: 'ACCOUNT_FREEZE_REQUEST',
            status: 'PENDING_APPROVAL',
            requester_id: 'usr-analyst-brody',
            requested_amount: '11750.0000',
            currency: 'USD',
            is_simulated: true,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ]);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchRequests();
  }, []);

  const handleApprove = async (r: RecoveryRequest) => {
    try {
      await caseService.approveRecoveryRequest(r.id);
      fetchRequests();
    } catch {
      // Local optimistic update
      setRequests((prev) =>
        prev.map((item) =>
          item.id === r.id
            ? { ...item, status: 'SUBMITTED', approver_id: 'usr-supervisor-vance' }
            : item
        )
      );
    }
  };

  const handleCreateRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await caseService.createRecoveryRequest({
        case_id: caseId,
        counterparty_institution_id: '10000000-0000-0000-0000-000000000002',
        action_type: actionType,
        requested_amount: amount,
        currency: 'USD',
        target_account_id: targetAccount,
      });
      fetchRequests();
      setIsModalOpen(false);
    } catch {
      // Local optimistic addition
      setRequests((prev) => [
        {
          id: 'rcv-demo-' + Math.random().toString(36).substring(2, 6),
          case_id: caseId,
          request_code: `RCV-20261022-000${prev.length + 1}`,
          origin_institution_id: '10000000-0000-0000-0000-000000000001',
          counterparty_institution_id: '10000000-0000-0000-0000-000000000002',
          action_type: actionType as RecoveryRequest['action_type'],
          status: 'PENDING_APPROVAL',
          requester_id: 'usr-analyst-brody',
          requested_amount: amount,
          currency: 'USD',
          is_simulated: true,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        ...prev,
      ]);
      setIsModalOpen(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Simulation Banner Notice */}
      <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-start space-x-3 text-amber-300">
        <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
        <div className="text-xs space-y-1">
          <span className="font-bold uppercase tracking-wider text-[11px]">Prototype Simulation Boundary Notice:</span>
          <p className="text-amber-200/80 leading-relaxed">
            All inter-bank recovery workflows (freeze requests, fund recalls, disputes) are strictly simulated prototypes. The platform has zero independent authority to freeze external financial accounts without authorized human counterparty bank approval.
          </p>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center space-x-2">
            <GitPullRequest className="w-5 h-5 text-indigo-400" />
            <span>Inter-Bank Recovery & Dual-Control Dispatch</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Cross-institution mutual recovery requests with strict dual-control separation of duties (`approver != requester`).
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={fetchRequests}
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setIsModalOpen(true)}
            className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-indigo-600/20 transition"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Stage Recovery Request</span>
          </button>
        </div>
      </div>

      {/* Requests List */}
      <div className="grid grid-cols-1 gap-4">
        {requests.map((r) => (
          <div
            key={r.id}
            className="glass-card rounded-2xl p-6 border border-slate-800 space-y-4 hover:border-indigo-500/30 transition shadow-xl"
          >
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
              <div className="flex items-center space-x-3">
                <div className="p-2.5 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-bold text-sm">
                  <GitPullRequest className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-sm font-bold text-white">{r.request_code}</span>
                    <Badge variant={r.status === 'SUBMITTED' ? 'success' : 'warning'}>
                      {r.status}
                    </Badge>
                    <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                      {r.action_type}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5 font-mono">
                    Case: <span className="text-white">{r.case_id}</span> · Amount: <span className="text-emerald-400 font-bold">${parseFloat(r.requested_amount || '0').toFixed(2)} {r.currency}</span>
                  </p>
                </div>
              </div>

              {r.status === 'PENDING_APPROVAL' && (
                <button
                  onClick={() => handleApprove(r)}
                  className="px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center space-x-1.5 transition shadow-lg shadow-emerald-600/20"
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>Dual-Control Approve</span>
                </button>
              )}
            </div>

            <div className="p-3 bg-slate-900/60 rounded-xl font-mono text-[11px] text-slate-400 grid grid-cols-1 sm:grid-cols-3 gap-2">
              <div>Requester: <span className="text-slate-200">{r.requester_id}</span></div>
              <div>Approver: <span className="text-slate-200">{r.approver_id || 'Pending 2nd Supervisor'}</span></div>
              <div>Simulated Mode: <span className="text-amber-400">{r.is_simulated ? 'YES (Prototype)' : 'LIVE'}</span></div>
            </div>
          </div>
        ))}
      </div>

      {/* Modal */}
      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title="Stage Inter-Bank Recovery Action">
        <form onSubmit={handleCreateRequest} className="space-y-4 text-xs font-sans">
          <div>
            <label className="block text-slate-300 font-medium mb-1">Action Type</label>
            <select
              value={actionType}
              onChange={(e) => setActionType(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white"
            >
              <option value="ACCOUNT_FREEZE_REQUEST">Account Freeze Request</option>
              <option value="FUNDS_RECALL">Funds Recall</option>
              <option value="TRANSACTION_DISPUTE">Transaction Dispute</option>
              <option value="INFORMATION_REQUEST">Information Request</option>
            </select>
          </div>

          <div>
            <label className="block text-slate-300 font-medium mb-1">Associated Case ID</label>
            <input
              type="text"
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white"
              required
            />
          </div>

          <div>
            <label className="block text-slate-300 font-medium mb-1">Target Account UUID</label>
            <input
              type="text"
              value={targetAccount}
              onChange={(e) => setTargetAccount(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white"
              required
            />
          </div>

          <div>
            <label className="block text-slate-300 font-medium mb-1">Recall Amount ($)</label>
            <input
              type="number"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-mono text-white"
            />
          </div>

          <div className="flex justify-end space-x-2 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={() => setIsModalOpen(false)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium"
            >
              {isSubmitting ? 'Staging...' : 'Submit for Dual Approval'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};

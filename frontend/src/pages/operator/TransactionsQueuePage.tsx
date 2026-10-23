import React, { useEffect, useState } from 'react';
import { useTenant } from '../../context/TenantContext';
import { bankingService } from '../../services/bankingService';
import { Transaction, Account } from '../../types/banking';
import { Badge } from '../../components/common/Badge';
import { Modal } from '../../components/common/Modal';
import {
  Plus,
  ArrowLeftRight,
  RefreshCw,
  Send,
  Search,
  CheckCircle,
  Clock,
  PauseCircle,
  Sparkles,
} from 'lucide-react';

export const TransactionsQueuePage: React.FC = () => {
  const { activeInstitutionId } = useTenant();
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);

  // Submit Modal State
  const [isSubmitModalOpen, setIsSubmitModalOpen] = useState(false);
  const [originAccount, setOriginAccount] = useState('');
  const [destAccount, setDestAccount] = useState('');
  const [amount, setAmount] = useState('2500.0000');
  const [idempotencyKey, setIdempotencyKey] = useState(`tx-ui-${Date.now()}`);
  const [purposeCode, setPurposeCode] = useState('INVOICE_PAYMENT');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);

  const fetchTransactions = () => {
    setLoading(true);
    Promise.all([
      bankingService.getTransactions(activeInstitutionId),
      bankingService.getAccounts(activeInstitutionId),
    ])
      .then(([txRes, accRes]) => {
        setTransactions(txRes.items || []);
        setAccounts(accRes.items || []);
        if (accRes.items && accRes.items.length > 0) {
          setOriginAccount((prev) => (accRes.items.some((a) => a.id === prev) ? prev : accRes.items[0].id));
          setDestAccount((prev) => (accRes.items.some((a) => a.id === prev) ? prev : (accRes.items[1]?.id || accRes.items[0].id)));
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchTransactions();
  }, [activeInstitutionId]);

  const handleSimulateAction = async (txId: string, action: 'SETTLE' | 'HOLD' | 'REJECT' | 'CANCEL') => {
    try {
      await bankingService.simulateAction(txId, action);
      setActionFeedback(`Transaction ${txId.substring(0, 8)} successfully updated to ${action}`);
      setTimeout(() => setActionFeedback(null), 3000);
      fetchTransactions();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Action failed');
    }
  };

  const handleSubmitTransaction = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitMessage(null);
    try {
      const res = await bankingService.submitTransaction({
        idempotency_key: idempotencyKey,
        origin_institution_id: activeInstitutionId,
        origin_account_id: originAccount,
        destination_institution_id: activeInstitutionId,
        destination_account_id: destAccount,
        amount: parseFloat(amount).toFixed(4),
        currency: 'USD',
        purpose_code: purposeCode,
      });
      setSubmitMessage(`Transaction ${res.status}: ID ${res.id.substring(0, 8)}...`);
      fetchTransactions();
      setTimeout(() => {
        setIsSubmitModalOpen(false);
        setSubmitMessage(null);
        setIdempotencyKey(`tx-ui-${Date.now()}`);
      }, 1500);
    } catch (err: unknown) {
      setSubmitMessage(err instanceof Error ? `Error: ${err.message}` : 'Failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const filteredTransactions = transactions.filter((tx) => {
    const matchesStatus = statusFilter === 'ALL' ? true : tx.status === statusFilter;
    const matchesSearch =
      searchQuery.trim() === ''
        ? true
        : tx.idempotency_key.toLowerCase().includes(searchQuery.toLowerCase()) ||
          tx.origin_account_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
          tx.destination_account_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
          (tx.purpose_code && tx.purpose_code.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchesStatus && matchesSearch;
  });

  const settledCount = transactions.filter((t) => t.status === 'SETTLED').length;
  const pendingCount = transactions.filter((t) => t.status === 'PENDING_AUTHORIZATION').length;
  const heldCount = transactions.filter((t) => t.status === 'HELD').length;
  const totalVolume = transactions
    .reduce((acc, t) => acc + parseFloat(t.amount || '0'), 0)
    .toFixed(2);

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center space-x-2">
            <ArrowLeftRight className="w-5 h-5 text-indigo-400" />
            <span>Transaction Authorization & Settlement Queue</span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time financial state machine enforcing exact Decimal precision and deterministic idempotency.
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={fetchTransactions}
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
          </button>

          <button
            onClick={() => setIsSubmitModalOpen(true)}
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white text-xs font-semibold flex items-center space-x-1.5 shadow-lg shadow-indigo-600/30 transition transform hover:-translate-y-0.5"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Submit Transaction</span>
          </button>
        </div>
      </div>

      {/* Action Feedback Banner */}
      {actionFeedback && (
        <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-emerald-400 text-xs flex items-center space-x-2 animate-fadeIn glow-emerald">
          <Sparkles className="w-4 h-4 shrink-0" />
          <span>{actionFeedback}</span>
        </div>
      )}

      {/* Summary Stat Badges Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase font-semibold text-slate-400">Total Volume</div>
            <div className="text-sm font-bold font-mono text-white mt-0.5">${totalVolume}</div>
          </div>
          <ArrowLeftRight className="w-4 h-4 text-indigo-400" />
        </div>

        <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase font-semibold text-slate-400">Settled Final</div>
            <div className="text-sm font-bold font-mono text-emerald-400 mt-0.5">{settledCount}</div>
          </div>
          <CheckCircle className="w-4 h-4 text-emerald-400" />
        </div>

        <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase font-semibold text-slate-400">Pending Review</div>
            <div className="text-sm font-bold font-mono text-amber-400 mt-0.5">{pendingCount}</div>
          </div>
          <Clock className="w-4 h-4 text-amber-400" />
        </div>

        <div className="p-3 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between">
          <div>
            <div className="text-[10px] uppercase font-semibold text-slate-400">MuleChain Holds</div>
            <div className="text-sm font-bold font-mono text-purple-400 mt-0.5">{heldCount}</div>
          </div>
          <PauseCircle className="w-4 h-4 text-purple-400" />
        </div>
      </div>

      {/* Controls: Search & Filter Tabs */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        {/* Search Bar */}
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search key, account, or purpose..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 bg-slate-900/80 border border-slate-800 rounded-xl text-xs text-white focus:outline-none focus:border-indigo-500 font-sans"
          />
        </div>

        {/* Filter Tabs */}
        <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 text-xs">
          {['ALL', 'PENDING_AUTHORIZATION', 'AUTHORIZED', 'SETTLED', 'HELD', 'REJECTED'].map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-3 py-1.5 rounded-xl font-medium transition whitespace-nowrap ${
                statusFilter === st
                  ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                  : 'bg-slate-900/80 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              {st.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      {/* Transactions Table */}
      <div className="glass-card rounded-2xl border border-slate-800 overflow-hidden shadow-2xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[11px] uppercase tracking-wider text-slate-400 bg-slate-900/70 border-b border-slate-800">
              <tr>
                <th className="py-3 px-4">Idempotency Key</th>
                <th className="py-3 px-4">Amount</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Origin Account</th>
                <th className="py-3 px-4">Destination Account</th>
                <th className="py-3 px-4">Timestamp</th>
                <th className="py-3 px-4 text-right">Operator Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono text-slate-300">
              {filteredTransactions.map((tx) => (
                <tr key={tx.id} className="hover:bg-slate-800/30 transition">
                  <td className="py-3.5 px-4 font-semibold text-white max-w-[160px] truncate">
                    {tx.idempotency_key}
                  </td>
                  <td className="py-3.5 px-4 font-bold text-emerald-400">
                    ${parseFloat(tx.amount).toFixed(4)} {tx.currency}
                  </td>
                  <td className="py-3.5 px-4">
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
                  <td className="py-3.5 px-4 text-slate-400 truncate max-w-[120px]">
                    {tx.origin_account_id}
                  </td>
                  <td className="py-3.5 px-4 text-slate-400 truncate max-w-[120px]">
                    {tx.destination_account_id}
                  </td>
                  <td className="py-3.5 px-4 text-slate-500 font-sans text-[11px]">
                    {new Date(tx.created_at).toLocaleString()}
                  </td>
                  <td className="py-3.5 px-4 text-right font-sans space-x-1.5">
                    {tx.status === 'PENDING_AUTHORIZATION' && (
                      <>
                        <button
                          onClick={() => handleSimulateAction(tx.id, 'SETTLE')}
                          className="px-2.5 py-1 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[11px] font-semibold transition"
                        >
                          Settle
                        </button>
                        <button
                          onClick={() => handleSimulateAction(tx.id, 'HOLD')}
                          className="px-2.5 py-1 rounded-lg bg-purple-500/10 hover:bg-purple-500/20 text-purple-400 border border-purple-500/30 text-[11px] font-semibold transition"
                        >
                          Hold
                        </button>
                        <button
                          onClick={() => handleSimulateAction(tx.id, 'REJECT')}
                          className="px-2.5 py-1 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 text-[11px] font-semibold transition"
                        >
                          Reject
                        </button>
                      </>
                    )}
                    {tx.status === 'HELD' && (
                      <button
                        onClick={() => handleSimulateAction(tx.id, 'SETTLE')}
                        className="px-2.5 py-1 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[11px] font-semibold transition"
                      >
                        Release & Settle
                      </button>
                    )}
                    {tx.status === 'SETTLED' && (
                      <span className="text-[11px] text-emerald-400 font-semibold flex items-center justify-end space-x-1">
                        <CheckCircle className="w-3.5 h-3.5" />
                        <span>Settlement Final</span>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
              {filteredTransactions.length === 0 && !loading && (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500 font-sans">
                    No transactions match the selected criteria.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Submit Transaction Modal */}
      <Modal
        isOpen={isSubmitModalOpen}
        onClose={() => setIsSubmitModalOpen(false)}
        title="Submit Simulated Banking Transaction"
      >
        <form onSubmit={handleSubmitTransaction} className="space-y-4 text-xs font-sans">
          {submitMessage && (
            <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-indigo-300">
              {submitMessage}
            </div>
          )}

          <div>
            <label className="block text-slate-300 font-medium mb-1">Idempotency Key (UUID or Tag)</label>
            <input
              type="text"
              value={idempotencyKey}
              onChange={(e) => setIdempotencyKey(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl font-mono text-white focus:outline-none focus:border-indigo-500"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-slate-300 font-medium mb-1">Origin Account</label>
              <select
                value={originAccount}
                onChange={(e) => setOriginAccount(e.target.value)}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl font-mono text-white focus:outline-none focus:border-indigo-500"
              >
                {accounts.length === 0 && <option value="">No accounts available</option>}
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.account_type} ···{a.account_number.slice(-4)} (${parseFloat(a.balance).toFixed(0)})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-slate-300 font-medium mb-1">Destination Account</label>
              <select
                value={destAccount}
                onChange={(e) => setDestAccount(e.target.value)}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl font-mono text-white focus:outline-none focus:border-indigo-500"
              >
                {accounts.length === 0 && <option value="">No accounts available</option>}
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.account_type} ···{a.account_number.slice(-4)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-slate-300 font-medium mb-1">Amount ($)</label>
              <input
                type="number"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl font-mono text-white focus:outline-none focus:border-indigo-500"
                required
              />
            </div>

            <div>
              <label className="block text-slate-300 font-medium mb-1">Purpose Code</label>
              <input
                type="text"
                value={purposeCode}
                onChange={(e) => setPurposeCode(e.target.value)}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl font-mono text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div className="pt-4 border-t border-slate-800 flex justify-end space-x-2">
            <button
              type="button"
              onClick={() => setIsSubmitModalOpen(false)}
              className="px-4 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white font-medium flex items-center space-x-1.5 shadow-lg shadow-indigo-600/30 transition"
            >
              <Send className="w-3.5 h-3.5" />
              <span>{isSubmitting ? 'Submitting...' : 'Submit Transaction'}</span>
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};


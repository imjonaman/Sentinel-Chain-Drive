import React, { useState } from 'react';
import { ShieldAlert, Check, X, AlertCircle } from 'lucide-react';
import { Badge } from '../../components/common/Badge';
import { Modal } from '../../components/common/Modal';
import { StepUpChallenge } from '../../types/policy';

export const StepUpChallengesPage: React.FC = () => {
  // Demonstration active challenges
  const [challenges, setChallenges] = useState<StepUpChallenge[]>([
    {
      id: 'ch-demo-001',
      transaction_id: 'tx-highval-2026-0091',
      institution_id: '10000000-0000-0000-0000-000000000001',
      initiating_agent_id: '00000000-0000-0000-0000-000000000099',
      transaction_intent_hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      challenge_reason: 'Amount exceeds Tier-6 dual-control threshold ($10,000.00)',
      status: 'PENDING',
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      created_at: new Date().toISOString(),
    },
    {
      id: 'ch-demo-002',
      transaction_id: 'tx-mulealert-2026-0042',
      institution_id: '10000000-0000-0000-0000-000000000001',
      initiating_agent_id: '00000000-0000-0000-0000-000000000088',
      transaction_intent_hash: '7d793037a0760186574b0282f2f435e7b1e507746905713176181b7732613f21',
      challenge_reason: 'Elevated MuleChain risk score (65.0) on destination node',
      status: 'PENDING',
      expires_at: new Date(Date.now() + 1800000).toISOString(),
      created_at: new Date(Date.now() - 900000).toISOString(),
    },
  ]);

  const [activeReview, setActiveReview] = useState<StepUpChallenge | null>(null);
  const [reviewNotes, setReviewNotes] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDecision = (challengeId: string, decision: 'APPROVED' | 'REJECTED') => {
    setIsSubmitting(true);
    setError(null);
    try {
      setChallenges((prev) =>
        prev.map((c) =>
          c.id === challengeId
            ? {
                ...c,
                status: decision,
                reviewed_by: 'Alex Vance (Dual-Control Supervisor)',
                reviewed_at: new Date().toISOString(),
                reviewer_notes: reviewNotes || 'Human supervisor reviewed and certified intent hash.',
              }
            : c
        )
      );
      setActiveReview(null);
      setReviewNotes('');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Review action failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white flex items-center space-x-2">
          <ShieldAlert className="w-5 h-5 text-amber-400" />
          <span>Dual-Control Step-Up Authorization Queue</span>
        </h2>
        <p className="text-xs text-slate-400 mt-0.5">
          Enforces mandatory human supervisor review on transactions triggering Tier-6 capability bounds.
        </p>
      </div>

      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-xs text-rose-400 flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Challenges List */}
      <div className="grid grid-cols-1 gap-4">
        {challenges.map((c) => (
          <div
            key={c.id}
            className="glass-card rounded-2xl p-6 border border-slate-800 space-y-4 hover:border-slate-700 transition"
          >
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
              <div className="flex items-center space-x-3">
                <div className="p-2 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  <ShieldAlert className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-sm font-bold text-white">{c.id}</span>
                    <Badge variant={c.status === 'PENDING' ? 'warning' : c.status === 'APPROVED' ? 'success' : 'danger'}>
                      {c.status}
                    </Badge>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">{c.challenge_reason}</p>
                </div>
              </div>

              {c.status === 'PENDING' && (
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => setActiveReview(c)}
                    className="px-3.5 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition"
                  >
                    Conduct Dual Review
                  </button>
                </div>
              )}
            </div>

            {/* Technical Verification Details */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-3 rounded-xl bg-slate-900/60 font-mono text-[11px] text-slate-400">
              <div>
                <span className="text-slate-500">Transaction ID:</span>
                <span className="text-slate-300 block truncate">{c.transaction_id}</span>
              </div>
              <div>
                <span className="text-slate-500">Initiating AgentID:</span>
                <span className="text-slate-300 block truncate">{c.initiating_agent_id || 'System Autonomous'}</span>
              </div>
              <div>
                <span className="text-slate-500">Expires:</span>
                <span className="text-amber-300 block">{new Date(c.expires_at).toLocaleTimeString()}</span>
              </div>
            </div>

            {/* If Already Reviewed */}
            {c.reviewed_by && (
              <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800 text-xs space-y-1">
                <div className="text-slate-400 font-medium">
                  Reviewer: <span className="text-white">{c.reviewed_by}</span> at{' '}
                  <span className="text-slate-400">{new Date(c.reviewed_at!).toLocaleString()}</span>
                </div>
                <div className="text-slate-400 italic">Notes: "{c.reviewer_notes}"</div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Review Modal */}
      <Modal
        isOpen={Boolean(activeReview)}
        onClose={() => setActiveReview(null)}
        title={`Dual-Control Challenge Review: ${activeReview?.id || ''}`}
        maxWidth="lg"
      >
        {activeReview && (
          <div className="space-y-5">
            <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-300 space-y-1">
              <span className="font-bold">Separation of Duties Policy:</span>
              <p className="text-[11px] text-amber-300/80">
                You are certifying that you are NOT the initiating agent or transaction originator. Your approval will unlock execution for settlement.
              </p>
            </div>

            <div>
              <label className="block text-xs text-slate-300 mb-1">Supervisor Audit Notes</label>
              <textarea
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                placeholder="Document verified corporate mandate, invoice number, or verification rationale..."
                rows={3}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-amber-500"
              />
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setActiveReview(null)}
                className="px-4 py-2 rounded-xl text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <div className="flex space-x-2">
                <button
                  type="button"
                  disabled={isSubmitting}
                  onClick={() => handleDecision(activeReview.id, 'REJECTED')}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 transition flex items-center space-x-1"
                >
                  <X className="w-3.5 h-3.5" />
                  <span>Decline Transaction</span>
                </button>
                <button
                  type="button"
                  disabled={isSubmitting}
                  onClick={() => handleDecision(activeReview.id, 'APPROVED')}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition flex items-center space-x-1 shadow-lg shadow-emerald-600/20"
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>Approve & Release</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

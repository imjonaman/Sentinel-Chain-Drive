import React, { useState, useEffect } from 'react';
import { CapabilityEnvelope } from '../../types/agent';
import { Sliders, Clock, DollarSign, Check, AlertCircle, Sparkles } from 'lucide-react';

interface CapabilitySlidersProps {
  capability: CapabilityEnvelope;
  onSave?: (updated: {
    max_amount_per_transaction: string;
    max_daily_cumulative_amount: string;
    operating_start_hour_utc: number;
    operating_end_hour_utc: number;
  }) => Promise<void>;
}

export const CapabilitySliders: React.FC<CapabilitySlidersProps> = ({ capability, onSave }) => {
  const [singleAmount, setSingleAmount] = useState<number>(
    parseFloat(capability.max_amount_per_transaction || '5000')
  );
  const [dailyAmount, setDailyAmount] = useState<number>(
    parseFloat(capability.max_daily_cumulative_amount || '25000')
  );
  const [startHour, setStartHour] = useState<number>(capability.operating_start_hour_utc ?? 8);
  const [endHour, setEndHour] = useState<number>(capability.operating_end_hour_utc ?? 18);

  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync state whenever capability prop changes
  useEffect(() => {
    setSingleAmount(parseFloat(capability.max_amount_per_transaction || '5000'));
    setDailyAmount(parseFloat(capability.max_daily_cumulative_amount || '25000'));
    setStartHour(capability.operating_start_hour_utc ?? 8);
    setEndHour(capability.operating_end_hour_utc ?? 18);
    setError(null);
    setSaveSuccess(false);
  }, [capability]);

  const applyPreset = (single: number, daily: number, start: number, end: number) => {
    setSingleAmount(single);
    setDailyAmount(daily);
    setStartHour(start);
    setEndHour(end);
    setError(null);
  };

  const handleSave = async () => {
    if (singleAmount <= 0) {
      setError('Single transaction limit must be greater than $0');
      return;
    }
    if (dailyAmount <= 0) {
      setError('Daily cumulative limit must be greater than $0');
      return;
    }
    if (singleAmount > dailyAmount) {
      setError('Single transaction limit cannot exceed 24h cumulative limit');
      return;
    }
    if (startHour >= endHour) {
      setError('Operating end hour must be after start hour (UTC)');
      return;
    }

    setError(null);
    setIsSaving(true);
    setSaveSuccess(false);
    try {
      if (onSave) {
        await onSave({
          max_amount_per_transaction: singleAmount.toFixed(4),
          max_daily_cumulative_amount: dailyAmount.toFixed(4),
          operating_start_hour_utc: startHour,
          operating_end_hour_utc: endHour,
        });
      }
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to update capabilities');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-semibold text-white flex items-center space-x-2">
            <Sliders className="w-4 h-4 text-indigo-400" />
            <span>Capability Envelope Limits {capability.version ? `(v${capability.version})` : ''}</span>
          </h4>
          <p className="text-xs text-slate-400 mt-0.5">
            Configure hard mathematical velocity bounds and UTC operating windows
          </p>
        </div>
        <span className="text-xs px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono font-medium">
          ACTIVE BOUNDARY
        </span>
      </div>

      {/* Presets Strip */}
      <div className="flex items-center space-x-2 p-2 rounded-xl bg-slate-800/40 border border-slate-700/50 text-[11px]">
        <span className="text-slate-400 flex items-center space-x-1 shrink-0 font-medium">
          <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
          <span>Presets:</span>
        </span>
        <button
          type="button"
          onClick={() => applyPreset(1000, 5000, 9, 17)}
          className="px-2 py-0.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
        >
          Micro ($1k / $5k)
        </button>
        <button
          type="button"
          onClick={() => applyPreset(5000, 25000, 8, 18)}
          className="px-2 py-0.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
        >
          Standard ($5k / $25k)
        </button>
        <button
          type="button"
          onClick={() => applyPreset(25000, 100000, 6, 22)}
          className="px-2 py-0.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
        >
          Treasury ($25k / $100k)
        </button>
      </div>

      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-xs text-rose-400 flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Sliders Container */}
      <div className="space-y-5">
        {/* Single Transaction Limit */}
        <div className="space-y-2 p-3 bg-slate-800/30 rounded-xl border border-slate-800">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-300 font-medium flex items-center space-x-1">
              <DollarSign className="w-3.5 h-3.5 text-indigo-400" />
              <span>Single Transaction Cap</span>
            </span>
            <div className="flex items-center space-x-2">
              <span className="font-mono text-indigo-300 font-bold">${singleAmount.toLocaleString()}</span>
              <div className="flex items-center space-x-0.5 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5">
                <span className="text-slate-400 text-[10px]">$</span>
                <input
                  type="number"
                  min="1"
                  step="100"
                  value={singleAmount}
                  onChange={(e) => setSingleAmount(Math.max(0, Number(e.target.value)))}
                  className="w-20 bg-transparent text-right font-mono text-xs text-white focus:outline-none"
                />
              </div>
            </div>
          </div>
          <input
            type="range"
            min="100"
            max="100000"
            step="500"
            value={Math.min(singleAmount, 100000)}
            onChange={(e) => setSingleAmount(Number(e.target.value))}
            className="w-full accent-indigo-500 cursor-pointer"
          />
          <div className="flex justify-between text-[10px] text-slate-500 font-mono">
            <span>$100 min</span>
            <span>$50,000 mid</span>
            <span>$100,000+ max</span>
          </div>
        </div>

        {/* 24-Hour Cumulative Limit */}
        <div className="space-y-2 p-3 bg-slate-800/30 rounded-xl border border-slate-800">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-300 font-medium flex items-center space-x-1">
              <DollarSign className="w-3.5 h-3.5 text-cyan-400" />
              <span>24h Daily Cumulative Cap</span>
            </span>
            <div className="flex items-center space-x-2">
              <span className="font-mono text-cyan-300 font-bold">${dailyAmount.toLocaleString()}</span>
              <div className="flex items-center space-x-0.5 bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5">
                <span className="text-slate-400 text-[10px]">$</span>
                <input
                  type="number"
                  min="1"
                  step="500"
                  value={dailyAmount}
                  onChange={(e) => setDailyAmount(Math.max(0, Number(e.target.value)))}
                  className="w-24 bg-transparent text-right font-mono text-xs text-white focus:outline-none"
                />
              </div>
            </div>
          </div>
          <input
            type="range"
            min="500"
            max="500000"
            step="1000"
            value={Math.min(dailyAmount, 500000)}
            onChange={(e) => setDailyAmount(Number(e.target.value))}
            className="w-full accent-cyan-500 cursor-pointer"
          />
          <div className="flex justify-between text-[10px] text-slate-500 font-mono">
            <span>$500 min</span>
            <span>$250,000 mid</span>
            <span>$500,000+ max</span>
          </div>
        </div>

        {/* Operating Hours */}
        <div className="space-y-2 p-3 bg-slate-800/30 rounded-xl border border-slate-800">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="text-slate-300 font-medium flex items-center space-x-1">
              <Clock className="w-3.5 h-3.5 text-amber-400" />
              <span>UTC Operating Window</span>
            </span>
            <span className="font-mono text-amber-300 font-medium text-xs">
              {startHour.toString().padStart(2, '0')}:00 – {endHour.toString().padStart(2, '0')}:00 UTC
            </span>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="text-[11px] text-slate-400">Start Hour (0–23 UTC)</span>
              <input
                type="number"
                min="0"
                max="23"
                value={startHour}
                onChange={(e) => setStartHour(Number(e.target.value))}
                className="w-full px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs font-mono text-white mt-1 focus:outline-none focus:border-amber-500"
              />
            </div>
            <div>
              <span className="text-[11px] text-slate-400">End Hour (1–23 UTC)</span>
              <input
                type="number"
                min="1"
                max="23"
                value={endHour}
                onChange={(e) => setEndHour(Number(e.target.value))}
                className="w-full px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs font-mono text-white mt-1 focus:outline-none focus:border-amber-500"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="pt-2 flex justify-end">
        <button
          onClick={handleSave}
          disabled={isSaving}
          className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-gradient-to-r from-indigo-600 to-cyan-500 hover:opacity-95 text-white transition flex items-center space-x-1.5 shadow-lg shadow-indigo-600/25 disabled:opacity-50"
        >
          {isSaving ? (
            <span>Saving Limits...</span>
          ) : saveSuccess ? (
            <>
              <Check className="w-4 h-4 text-emerald-400" />
              <span className="text-white font-bold">Saved!</span>
            </>
          ) : (
            <>
              <Sliders className="w-3.5 h-3.5" />
              <span>Update Envelope</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
};

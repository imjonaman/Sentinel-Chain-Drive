import React from 'react';
import { LucideIcon } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  trend?: string;
  trendColor?: 'emerald' | 'rose' | 'amber' | 'indigo' | 'cyan';
  iconColor?: string;
  accentGradient?: string;
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  trendColor = 'emerald',
  iconColor = 'text-indigo-400',
  accentGradient = 'from-indigo-500/10 via-transparent to-transparent',
}) => {
  const trendBg = {
    emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    rose: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
    amber: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    indigo: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30',
    cyan: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30',
  }[trendColor];

  return (
    <div className={`glass-card glass-card-hover rounded-2xl p-5 relative overflow-hidden bg-gradient-to-br ${accentGradient}`}>
      {/* Decorative ambient corner glow */}
      <div className="absolute top-0 right-0 -mr-6 -mt-6 w-24 h-24 rounded-full bg-white/5 blur-2xl pointer-events-none" />

      <div className="flex items-start justify-between relative z-10">
        <div>
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">{title}</span>
          <div className="text-2xl md:text-3xl font-extrabold font-mono text-white mt-1.5 tracking-tight">
            {value}
          </div>
          {subtitle && <p className="text-xs text-slate-400 mt-1 leading-snug">{subtitle}</p>}
        </div>
        <div className={`p-3 rounded-2xl bg-slate-900/90 border border-slate-700/60 shadow-lg ${iconColor}`}>
          <Icon className="w-5 h-5" />
        </div>
      </div>

      {trend && (
        <div className="mt-3.5 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs relative z-10">
          <span className={`px-2 py-0.5 rounded-full font-mono font-bold text-[10px] border ${trendBg}`}>
            {trend}
          </span>
          <span className="text-slate-500 text-[11px]">telemetry active</span>
        </div>
      )}
    </div>
  );
};

import React, { useState, useEffect } from 'react';
import { useAuth, ROLE_CONFIGS } from '../../context/AuthContext';
import { useTenant } from '../../context/TenantContext';
import { UserRole } from '../../types/auth';
import {
  Shield,
  Building2,
  ChevronDown,
  Check,
  Clock,
  Sparkles,
  Wifi,
} from 'lucide-react';

export const Navbar: React.FC = () => {
  const { user, setRole, roleConfig } = useAuth();
  const { institutions, activeInstitutionId, setActiveInstitutionId, currentInstitution } = useTenant();

  const [isRoleDropdownOpen, setIsRoleDropdownOpen] = useState(false);
  const [isTenantDropdownOpen, setIsTenantDropdownOpen] = useState(false);
  const [currentTimeUtc, setCurrentTimeUtc] = useState<string>('');

  const tenantDropdownRef = React.useRef<HTMLDivElement>(null);
  const roleDropdownRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (tenantDropdownRef.current && !tenantDropdownRef.current.contains(event.target as Node)) {
        setIsTenantDropdownOpen(false);
      }
      if (roleDropdownRef.current && !roleDropdownRef.current.contains(event.target as Node)) {
        setIsRoleDropdownOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsTenantDropdownOpen(false);
        setIsRoleDropdownOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTimeUtc(
        now.toUTCString().replace('GMT', 'UTC').split(' ').slice(4, 5).join(' ') + ' UTC'
      );
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="h-16 border-b border-slate-800/80 bg-[#070b16]/95 backdrop-blur-xl sticky top-0 z-40 px-4 md:px-6 flex items-center justify-between shadow-2xl">
      {/* Brand & Platform Identifier */}
      <div className="flex items-center space-x-3.5">
        <div className="relative group">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/30 ring-1 ring-white/20 transition group-hover:scale-105">
            <Shield className="w-5 h-5 text-white" />
          </div>
          <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-cyan-500 ring-2 ring-[#070b16]"></span>
          </span>
        </div>

        <div>
          <div className="flex items-center space-x-2">
            <span className="font-extrabold text-sm md:text-base tracking-wider bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
              SENTINEL
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded-md bg-gradient-to-r from-indigo-500/20 to-cyan-500/20 text-cyan-300 font-mono font-semibold border border-cyan-500/30 tracking-wider">
              CHAIN DRIVE
            </span>
            <span className="hidden sm:inline-flex items-center text-[10px] font-mono text-emerald-400 px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20">
              v0.1.0-P10
            </span>
          </div>
          <p className="text-[11px] text-slate-400 hidden md:flex items-center space-x-1.5">
            <span>AI-Agent Authorization</span>
            <span className="text-slate-600">•</span>
            <span>Cross-Bank Fraud Intelligence</span>
          </p>
        </div>
      </div>

      {/* Center Live Telemetry Bar */}
      <div className="hidden xl:flex items-center space-x-4 px-4 py-1.5 rounded-full bg-slate-900/80 border border-slate-800 text-xs font-mono text-slate-400">
        <div className="flex items-center space-x-1.5 text-emerald-400">
          <Wifi className="w-3.5 h-3.5 animate-pulse" />
          <span>16ms</span>
        </div>
        <span className="text-slate-700">|</span>
        <div className="flex items-center space-x-1.5 text-slate-300">
          <Clock className="w-3.5 h-3.5 text-cyan-400" />
          <span>{currentTimeUtc || 'SYNCING...'}</span>
        </div>
        <span className="text-slate-700">|</span>
        <div className="flex items-center space-x-1.5 text-indigo-400">
          <Sparkles className="w-3.5 h-3.5" />
          <span>MuleChain: ACTIVE</span>
        </div>
      </div>

      {/* Right Controls: Institution Switcher & Role Switcher */}
      <div className="flex items-center space-x-3">
        {/* Institution Tenant Switcher */}
        <div ref={tenantDropdownRef} className="relative">
          <button
            onClick={() => {
              setIsTenantDropdownOpen(!isTenantDropdownOpen);
              setIsRoleDropdownOpen(false);
            }}
            className="flex items-center space-x-2.5 px-3 py-1.5 rounded-xl bg-slate-900/90 hover:bg-slate-800/90 border border-slate-700/80 text-xs text-slate-200 transition shadow-inner group"
          >
            <div className="p-1 rounded-md bg-indigo-500/10 text-indigo-400 group-hover:text-indigo-300">
              <Building2 className="w-3.5 h-3.5" />
            </div>
            <div className="text-left hidden sm:block">
              <div className="font-semibold text-slate-200 max-w-[140px] truncate leading-tight">
                {currentInstitution?.name || 'Apex Commercial Bank'}
              </div>
              <div className="text-[10px] font-mono leading-none flex items-center space-x-1.5 mt-0.5">
                <span className="text-slate-400">{currentInstitution?.routing_identifier || 'APEXUS33'}</span>
                <span
                  className={`px-1 rounded text-[9px] font-bold ${
                    currentInstitution?.status === 'ACTIVE'
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                      : currentInstitution?.status === 'SUSPENDED'
                      ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                      : 'bg-slate-800 text-slate-400 border border-slate-700'
                  }`}
                >
                  {currentInstitution?.status || 'ACTIVE'}
                </span>
              </div>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 group-hover:text-white transition" />
          </button>

          {isTenantDropdownOpen && (
            <div className="absolute right-0 mt-2 w-80 rounded-2xl bg-[#0B1120] border border-slate-800 shadow-2xl p-2 z-50 animate-fadeIn">
              <div className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                <span>Select Institution Context</span>
                <span className="text-indigo-400 font-mono">X-Institution-ID</span>
              </div>
              <div className="mt-1 space-y-1">
                {institutions.map((inst) => (
                  <button
                    key={inst.id}
                    onClick={() => {
                      setActiveInstitutionId(inst.id);
                      setIsTenantDropdownOpen(false);
                    }}
                    className={`w-full text-left p-2.5 rounded-xl text-xs flex items-center justify-between transition ${
                      inst.id === activeInstitutionId
                        ? 'bg-indigo-600/20 text-white font-medium border border-indigo-500/40 glow-indigo'
                        : 'text-slate-300 hover:bg-slate-800/60'
                    }`}
                  >
                    <div>
                      <div className="flex items-center space-x-1.5">
                        <span className="font-semibold">{inst.name}</span>
                        <span
                          className={`text-[9px] px-1.5 py-0.2 rounded font-mono font-bold ${
                            inst.status === 'ACTIVE'
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                              : inst.status === 'SUSPENDED'
                              ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          {inst.status}
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                        {inst.routing_identifier} · {inst.country_code}
                      </div>
                    </div>
                    {inst.id === activeInstitutionId && (
                      <span className="p-1 rounded-full bg-indigo-500/20 text-indigo-400">
                        <Check className="w-3 h-3" />
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Role Switcher */}
        <div ref={roleDropdownRef} className="relative">
          <button
            onClick={() => {
              setIsRoleDropdownOpen(!isRoleDropdownOpen);
              setIsTenantDropdownOpen(false);
            }}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all shadow-md ${roleConfig.badgeClass} hover:opacity-90`}
          >
            <span className="w-2 h-2 rounded-full bg-current animate-pulse"></span>
            <span>{roleConfig.label}</span>
            <ChevronDown className="w-3.5 h-3.5 opacity-80" />
          </button>

          {isRoleDropdownOpen && (
            <div className="absolute right-0 mt-2 w-80 rounded-2xl bg-[#0B1120] border border-slate-800 shadow-2xl p-2.5 z-50 animate-fadeIn">
              <div className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                Select Active Operator Persona
              </div>
              <div className="mt-1 space-y-1.5">
                {(Object.keys(ROLE_CONFIGS) as UserRole[]).map((r) => {
                  const cfg = ROLE_CONFIGS[r];
                  const isActive = user.role === r;
                  return (
                    <button
                      key={r}
                      onClick={() => {
                        setRole(r);
                        setIsRoleDropdownOpen(false);
                      }}
                      className={`w-full text-left p-2.5 rounded-xl text-xs transition ${
                        isActive
                          ? 'bg-slate-800/90 border border-slate-700 shadow-inner'
                          : 'hover:bg-slate-800/50 text-slate-300'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-white flex items-center space-x-1.5">
                          <span
                            className={`w-2 h-2 rounded-full ${
                              r === 'BANK_OPERATOR'
                                ? 'bg-emerald-400'
                                : r === 'SECURITY_ADMINISTRATOR'
                                ? 'bg-indigo-400'
                                : r === 'FRAUD_ANALYST'
                                ? 'bg-rose-400'
                                : 'bg-amber-400'
                            }`}
                          />
                          <span>{cfg.label}</span>
                        </span>
                        {isActive && <Check className="w-3.5 h-3.5 text-indigo-400" />}
                      </div>
                      <p className="text-[11px] text-slate-400 mt-1 leading-snug">{cfg.description}</p>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};

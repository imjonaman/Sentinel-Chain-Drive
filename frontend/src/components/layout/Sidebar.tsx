import React from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import {
  LayoutDashboard,
  ArrowLeftRight,
  ShieldAlert,
  Bot,
  Sliders,
  Network,
  BellRing,
  Briefcase,
  GitPullRequest,
  FileText,
  Boxes,
  Zap,
} from 'lucide-react';

interface NavSection {
  title: string;
  items: {
    name: string;
    path: string;
    icon: React.ElementType;
    roles: string[];
    badge?: string;
    badgeColor?: string;
  }[];
}

export const Sidebar: React.FC = () => {
  const { user } = useAuth();

  const sections: NavSection[] = [
    {
      title: 'CORE PLATFORM',
      items: [
        {
          name: 'Mission Overview',
          path: '/',
          icon: LayoutDashboard,
          roles: ['BANK_OPERATOR', 'SECURITY_ADMINISTRATOR', 'FRAUD_ANALYST', 'AUDITOR'],
        },
      ],
    },
    {
      title: 'BANK OPERATIONS',
      items: [
        {
          name: 'Transaction Queue',
          path: '/operator/transactions',
          icon: ArrowLeftRight,
          roles: ['BANK_OPERATOR', 'AUDITOR'],
        },
        {
          name: 'Dual-Control Step-Up',
          path: '/operator/step-up',
          icon: ShieldAlert,
          roles: ['BANK_OPERATOR'],
          badge: '2-MAN RULE',
          badgeColor: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
        },
      ],
    },
    {
      title: 'SECURITY & GOVERNANCE',
      items: [
        {
          name: 'AgentID Registry',
          path: '/security/agents',
          icon: Bot,
          roles: ['SECURITY_ADMINISTRATOR', 'AUDITOR'],
        },
        {
          name: 'Deterministic Policies',
          path: '/security/policies',
          icon: Sliders,
          roles: ['SECURITY_ADMINISTRATOR', 'AUDITOR'],
        },
      ],
    },
    {
      title: 'FRAUD & GRAPH INTEL',
      items: [
        {
          name: 'Topology Explorer',
          path: '/fraud/graph',
          icon: Network,
          roles: ['FRAUD_ANALYST', 'SECURITY_ADMINISTRATOR', 'AUDITOR'],
          badge: 'CYTOSCAPE',
          badgeColor: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
        },
        {
          name: 'MuleChain Alerts',
          path: '/fraud/alerts',
          icon: BellRing,
          roles: ['FRAUD_ANALYST', 'AUDITOR'],
        },
        {
          name: 'Case Management',
          path: '/fraud/cases',
          icon: Briefcase,
          roles: ['FRAUD_ANALYST', 'AUDITOR'],
        },
        {
          name: 'Inter-Bank Recovery',
          path: '/fraud/recovery',
          icon: GitPullRequest,
          roles: ['FRAUD_ANALYST', 'BANK_OPERATOR'],
        },
      ],
    },
    {
      title: 'AUDIT & COMPLIANCE',
      items: [
        {
          name: 'DRUNIX Ledger Outbox',
          path: '/audit/drunix',
          icon: Boxes,
          roles: ['AUDITOR', 'BANK_OPERATOR'],
        },
        {
          name: 'Redaction Audit Trail',
          path: '/audit/logs',
          icon: FileText,
          roles: ['AUDITOR', 'SECURITY_ADMINISTRATOR'],
        },
      ],
    },
  ];

  return (
    <aside className="w-64 border-r border-slate-800/80 bg-[#070B16]/80 backdrop-blur-xl flex flex-col justify-between shrink-0 h-[calc(100vh-4rem)]">
      <div className="p-4 space-y-6 overflow-y-auto">
        {sections.map((sec) => {
          const visibleItems = sec.items.filter((item) => item.roles.includes(user.role));
          if (visibleItems.length === 0) return null;

          return (
            <div key={sec.title} className="space-y-1">
              <div className="px-3 mb-1 text-[10px] font-bold tracking-wider text-slate-500 uppercase flex items-center justify-between">
                <span>{sec.title}</span>
              </div>
              <nav className="space-y-1">
                {visibleItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <NavLink
                      key={item.path}
                      to={item.path}
                      end={item.path === '/'}
                      className={({ isActive }) =>
                        `group flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                          isActive
                            ? 'bg-gradient-to-r from-indigo-600 to-indigo-700 text-white shadow-lg shadow-indigo-600/30 font-semibold'
                            : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
                        }`
                      }
                    >
                      <div className="flex items-center space-x-2.5">
                        <Icon className="w-4 h-4 shrink-0 transition group-hover:scale-110" />
                        <span>{item.name}</span>
                      </div>
                      {item.badge && (
                        <span
                          className={`text-[9px] px-1.5 py-0.5 rounded font-mono font-bold border tracking-wider ${
                            item.badgeColor || 'text-slate-400 bg-slate-800 border-slate-700'
                          }`}
                        >
                          {item.badge}
                        </span>
                      )}
                    </NavLink>
                  );
                })}
              </nav>
            </div>
          );
        })}
      </div>

      {/* Operator Session Info Footer */}
      <div className="p-3.5 m-3 rounded-2xl bg-gradient-to-b from-slate-900/90 to-slate-950/90 border border-slate-800/90 shadow-xl">
        <div className="flex items-center space-x-3">
          <div className="relative">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center font-bold text-xs text-white shadow-md">
              {user.displayName.slice(0, 2).toUpperCase()}
            </div>
            <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 ring-2 ring-[#070B16]"></span>
          </div>
          <div className="truncate">
            <div className="text-xs font-semibold text-white truncate">{user.displayName}</div>
            <div className="text-[10px] text-cyan-400 font-mono truncate flex items-center space-x-1">
              <Zap className="w-2.5 h-2.5" />
              <span>ACTIVE SESSION</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
};

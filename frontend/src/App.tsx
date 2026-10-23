import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { TenantProvider } from './context/TenantContext';
import { AppLayout } from './components/layout/AppLayout';

// Pages
import { DashboardOverview } from './pages/DashboardOverview';
import { TransactionsQueuePage } from './pages/operator/TransactionsQueuePage';
import { StepUpChallengesPage } from './pages/operator/StepUpChallengesPage';
import { AgentsConsolePage } from './pages/security/AgentsConsolePage';
import { PoliciesConsolePage } from './pages/security/PoliciesConsolePage';
import { GraphExplorerPage } from './pages/fraud/GraphExplorerPage';
import { AlertsTriagePage } from './pages/fraud/AlertsTriagePage';
import { CaseManagementPage } from './pages/fraud/CaseManagementPage';
import { InterBankRecoveryPage } from './pages/fraud/InterBankRecoveryPage';
import { DrunixOutboxPage } from './pages/audit/DrunixOutboxPage';
import { AuditInspectorPage } from './pages/audit/AuditInspectorPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30000,
    },
  },
});

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TenantProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<AppLayout />}>
                <Route index element={<DashboardOverview />} />
                
                {/* Operator Views */}
                <Route path="operator/transactions" element={<TransactionsQueuePage />} />
                <Route path="operator/step-up" element={<StepUpChallengesPage />} />

                {/* Security Administrator Views */}
                <Route path="security/agents" element={<AgentsConsolePage />} />
                <Route path="security/policies" element={<PoliciesConsolePage />} />

                {/* Fraud Analyst Views */}
                <Route path="fraud/graph" element={<GraphExplorerPage />} />
                <Route path="fraud/alerts" element={<AlertsTriagePage />} />
                <Route path="fraud/cases" element={<CaseManagementPage />} />
                <Route path="fraud/recovery" element={<InterBankRecoveryPage />} />

                {/* Auditor Views */}
                <Route path="audit/drunix" element={<DrunixOutboxPage />} />
                <Route path="audit/logs" element={<AuditInspectorPage />} />

                {/* Catch-all redirect */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </TenantProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
};

export default App;

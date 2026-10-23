import { apiClient } from './api';
import { FraudAlert } from '../types/alert';
import { CytoscapeElement, GraphNodeData, GraphEdgeData } from '../types/graph';
import { bankingService } from './bankingService';

export const mulechainService = {
  getAlerts: (institutionId?: string) => {
    return apiClient<{ items: FraudAlert[]; total: number }>('/api/v1/alerts?limit=100', {
      institutionId,
    });
  },

  getAlert: (alertId: string) => {
    return apiClient<FraudAlert>(`/api/v1/alerts/${alertId}`);
  },

  triggerAnalysis: (payload: { currency: string; max_transactions?: number }) => {
    return apiClient<{
      transactions_analyzed: number;
      accounts_analyzed: number;
      alerts_generated: number;
      alerts_deduplicated: number;
      execution_time_ms: number;
      alerts: FraudAlert[];
    }>('/api/v1/mulechain/analyze', {
      method: 'POST',
      body: JSON.stringify({
        currency: payload.currency || 'USD',
        max_transactions: payload.max_transactions || 1000,
      }),
    });
  },

  // Builds Cytoscape elements from accounts, settled transactions, and fraud alerts
  getGraphElements: async (institutionId?: string): Promise<CytoscapeElement[]> => {
    const [accountsRes, txRes, alertsRes] = await Promise.all([
      bankingService.getAccounts(institutionId),
      bankingService.getTransactions(institutionId),
      mulechainService.getAlerts(institutionId),
    ]);

    const accounts = accountsRes.items || [];
    const transactions = txRes.items || [];
    const alerts = alertsRes.items || [];

    // Map account risk status from active alerts
    const accountAlertMap = new Map<string, { count: number; maxSeverity: string; pattern?: string }>();
    alerts.forEach((alert) => {
      alert.involved_account_ids?.forEach((accId) => {
        const existing = accountAlertMap.get(accId) || { count: 0, maxSeverity: 'LOW' };
        existing.count += 1;
        if (alert.severity === 'CRITICAL' || existing.maxSeverity !== 'CRITICAL') {
          existing.maxSeverity = alert.severity;
          existing.pattern = alert.detector_type;
        }
        accountAlertMap.set(accId, existing);
      });
    });

    const elements: CytoscapeElement[] = [];

    // Account nodes
    const nodeIds = new Set<string>();
    accounts.forEach((acc) => {
      nodeIds.add(acc.id);
      const alertInfo = accountAlertMap.get(acc.id);
      const riskStatus = 
        alertInfo?.maxSeverity === 'CRITICAL' ? 'CRITICAL' :
        alertInfo?.maxSeverity === 'HIGH' ? 'HIGH_RISK' :
        alertInfo?.maxSeverity ? 'SUSPICIOUS' : 'NORMAL';

      const nodeData: GraphNodeData = {
        id: acc.id,
        label: `${acc.account_type || 'ACC'} ···${acc.account_number.slice(-4)}`,
        institution_id: acc.institution_id,
        account_type: acc.account_type,
        balance: acc.balance,
        currency: acc.currency,
        risk_status: riskStatus,
        riskStatus,
        alert_count: alertInfo?.count || 0,
      };

      elements.push({
        group: 'nodes',
        data: nodeData,
      });
    });

    // Transaction directed edges (bounded to known nodes or dynamically creating external endpoints)
    transactions.slice(0, 500).forEach((tx) => {
      // Ensure source node exists
      if (!nodeIds.has(tx.origin_account_id)) {
        nodeIds.add(tx.origin_account_id);
        elements.push({
          group: 'nodes',
          data: {
            id: tx.origin_account_id,
            label: `ACC ···${tx.origin_account_id.slice(-4)}`,
            institution_id: tx.origin_institution_id,
            currency: tx.currency,
            risk_status: 'NORMAL',
            riskStatus: 'NORMAL',
            alert_count: 0,
          },
        });
      }
      // Ensure target node exists
      if (!nodeIds.has(tx.destination_account_id)) {
        nodeIds.add(tx.destination_account_id);
        elements.push({
          group: 'nodes',
          data: {
            id: tx.destination_account_id,
            label: `ACC ···${tx.destination_account_id.slice(-4)}`,
            institution_id: tx.destination_institution_id,
            currency: tx.currency,
            risk_status: 'NORMAL',
            riskStatus: 'NORMAL',
            alert_count: 0,
          },
        });
      }

      // Check if transaction is involved in an alert
      let patternType: GraphEdgeData['pattern_type'] = null;
      for (const a of alerts) {
        if (a.involved_transaction_ids?.includes(tx.id)) {
          if (a.detector_type === 'FAN_IN_SMURFING') patternType = 'FAN_IN';
          else if (a.detector_type === 'FAN_OUT_DISPERSAL') patternType = 'FAN_OUT';
          else if (a.detector_type === 'RAPID_PASS_THROUGH') patternType = 'PASS_THROUGH';
          else if (a.detector_type === 'CIRCULAR_LAYERING') patternType = 'CYCLE';
          break;
        }
      }

      const edgeData: GraphEdgeData = {
        id: tx.id,
        source: tx.origin_account_id,
        target: tx.destination_account_id,
        amount: tx.amount,
        currency: tx.currency,
        timestamp: tx.created_at,
        status: tx.status,
        pattern_type: patternType,
      };

      elements.push({
        group: 'edges',
        data: edgeData,
      });
    });

    return elements;
  },
};

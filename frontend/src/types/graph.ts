export interface GraphNodeData {
  id: string;
  label: string;
  institution_id: string;
  institution_code?: string;
  account_type?: string;
  balance?: string;
  currency: string;
  risk_status: 'NORMAL' | 'SUSPICIOUS' | 'HIGH_RISK' | 'CRITICAL';
  riskStatus?: 'NORMAL' | 'SUSPICIOUS' | 'HIGH_RISK' | 'CRITICAL';
  alert_count: number;
}

export interface GraphEdgeData {
  id: string;
  source: string;
  target: string;
  amount: string;
  currency: string;
  timestamp: string;
  status: string;
  pattern_type?: 'FAN_IN' | 'FAN_OUT' | 'PASS_THROUGH' | 'CYCLE' | null;
}

export interface CytoscapeElement {
  group: 'nodes' | 'edges';
  data: GraphNodeData | GraphEdgeData;
}

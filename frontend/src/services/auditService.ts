import { apiClient } from './api';

export interface DrunixStatus {
  service_status: string;
  adapter_type: string;
  circuit_breaker_state: string;
  consecutive_failures: number;
  outbox_queue_depth: {
    pending: number;
    in_progress: number;
    completed: number;
    failed: number;
  };
  metrics?: {
    total_processed: number;
    average_latency_ms: number;
    replayed_events: number;
  };
}

export const auditService = {
  getSystemInfo: () => apiClient<{
    app_name: string;
    version: string;
    environment: string;
    database_name: string;
  }>('/api/v1/system/info'),

  getHealth: () => apiClient<{ status: string }>('/health/ready'),

  getDrunixStatus: () => apiClient<DrunixStatus>('/api/v1/drunix/status'),
};

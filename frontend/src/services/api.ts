export interface RequestOptions extends RequestInit {
  institutionId?: string;
}

export async function apiClient<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const institutionId = options.institutionId || localStorage.getItem('sentinel_tenant_id') || '10000000-0000-0000-0000-000000000001';
  const correlationId = 'ui-' + Math.random().toString(36).substring(2, 10);

  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');
  headers.set('Accept', 'application/json');
  headers.set('X-Institution-ID', institutionId);
  headers.set('X-Correlation-ID', correlationId);

  const response = await fetch(endpoint, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorDetail = 'API request failed';
    try {
      const errJson = await response.json();
      errorDetail = errJson.message || errJson.error?.message || JSON.stringify(errJson);
    } catch {
      errorDetail = `HTTP ${response.status} ${response.statusText}`;
    }
    throw new Error(errorDetail);
  }

  // Handle empty responses
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

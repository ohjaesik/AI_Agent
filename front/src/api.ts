const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001';
const ENV_API_KEY = import.meta.env.VITE_API_KEY ?? '';
const ENV_USER_ROLE = import.meta.env.VITE_USER_ROLE ?? 'admin';
const ENV_USER_ID = import.meta.env.VITE_USER_ID ?? 'admin-user';

interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
}

function getAuthHeaders(): Record<string, string> {
  const apiKey = localStorage.getItem('ax_api_key') || ENV_API_KEY;
  const userRole = localStorage.getItem('ax_user_role') || ENV_USER_ROLE;
  const userId = localStorage.getItem('ax_user_id') || ENV_USER_ID;

  const headers: Record<string, string> = {};

  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }
  if (userRole) {
    headers['X-User-Role'] = userRole;
  }
  if (userId) {
    headers['X-User-Id'] = userId;
  }

  return headers;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { params, headers, ...rest } = options;
  
  // Construct URL with query parameters
  let url = `${API_BASE_URL}${path}`;
  if (params) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, val]) => {
      if (val !== undefined && val !== null) {
        query.append(key, String(val));
      }
    });
    const queryString = query.toString();
    if (queryString) {
      url += `?${queryString}`;
    }
  }

  const defaultHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...getAuthHeaders(),
  };

  const res = await fetch(url, {
    headers: {
      ...defaultHeaders,
      ...headers,
    },
    ...rest,
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${detail || 'Request failed'}`);
  }

  return res.json() as Promise<T>;
}

export interface HealthResponse {
  status: string;
}

export interface AnalysisResponse {
  status: 'ok' | 'interrupted';
  interrupt?: string;
  report_docx_path?: string;
  generation?: Record<string, any>;
  report_data?: Record<string, any>;
  citation_validation?: Record<string, any>;
  top_candidates?: Array<any>;
  compliance_summary?: Record<string, any>;
  model_decisions?: Array<any>;
  supervisor_delegations?: Array<any>;
  errors?: Array<any>;
}

export function getHealth() {
  return request<HealthResponse>('/health');
}

export function runAnalysis(params: { projectId?: number; companyId?: number; autoApprove?: boolean }) {
  return request<AnalysisResponse>('/analysis/run', {
    method: 'POST',
    params: {
      project_id: params.projectId,
      company_id: params.companyId,
      auto_approve: params.autoApprove !== false ? 'true' : 'false',
    },
  });
}

export function applyReviewToRanking(payload: { priority_ranking: any; human_review: any }) {
  return request<{ status: string; priority_ranking: any }>('/reviews/apply-ranking', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function reindexRag(params: { companyId?: number; reset?: boolean } = {}) {
  return request<{ status: string; inserted_chunks: number }>('/rag/reindex', {
    method: 'POST',
    params: {
      company_id: params.companyId,
      reset: params.reset !== false ? 'true' : 'false',
    },
  });
}

export function searchSimilarChunks(params: { query: string; companyId: number; processId?: number; topK?: number }) {
  return request<{ status: string; results: Array<any> }>('/rag/search', {
    method: 'GET',
    params: {
      query: params.query,
      company_id: params.companyId,
      process_id: params.processId,
      top_k: params.topK ?? 5,
    },
  });
}

export function ingestDocument(formData: FormData) {
  // For file upload, fetch handles boundaries automatically when Content-Type header is omitted
  return fetch(`${API_BASE_URL}/documents/ingest`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: formData,
  }).then(async (res) => {
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`${res.status} ${res.statusText}: ${detail || 'Ingestion failed'}`);
    }
    return res.json();
  });
}

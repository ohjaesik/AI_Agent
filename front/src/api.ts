// AX Delivery Planner frontend API client.
// 화면 컴포넌트가 fetch 세부 구현을 몰라도 되도록 backend endpoint별 함수를 제공한다.

// Vite 환경변수는 build 시점에 주입된다. 값이 없으면 로컬 FastAPI 기본 주소를 사용한다.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001';
const ENV_API_KEY = import.meta.env.VITE_API_KEY ?? '';
const ENV_USER_ROLE = import.meta.env.VITE_USER_ROLE ?? 'admin';
const ENV_USER_ID = import.meta.env.VITE_USER_ID ?? 'admin-user';

// 공통 요청 옵션. params는 query string으로 바꾸고, 나머지는 fetch 옵션으로 그대로 전달한다.
interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
}

function getAuthHeaders(): Record<string, string> {
  // 사용자가 설정 탭에서 저장한 값이 있으면 localStorage 값을 우선 사용한다.
  // 없으면 `.env`의 VITE_* 기본값을 header에 넣어 개발 환경에서도 바로 테스트할 수 있게 한다.
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
  // 모든 JSON API 요청이 거치는 공통 wrapper다.
  // query parameter 생성, 인증 header 병합, HTTP error message 정규화를 한곳에서 처리한다.
  const { params, headers, ...rest } = options;
  
  // undefined/null 값은 query string에 넣지 않아 backend가 기본값을 쓰게 한다.
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
    // JSON endpoint 기본값. 파일 업로드는 multipart boundary 때문에 별도 함수에서 처리한다.
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
  // backend /health endpoint가 반환하는 최소 상태값.
  status: string;
}

export interface AnalysisResponse {
  // /analysis/run 응답. 자동 승인 시 `ok`, HITL이 필요하면 `interrupted`가 반환된다.
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
  // API 서버 연결 상태를 확인해 header의 상태 badge를 갱신한다.
  return request<HealthResponse>('/health');
}

export function runAnalysis(params: { projectId?: number; companyId?: number; autoApprove?: boolean }) {
  // Supervisor graph 전체 분석을 실행한다. project/company ID는 query parameter로 전달된다.
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
  // Human-in-the-loop review 결과를 ranking에 반영할 때 호출한다.
  return request<{ status: string; priority_ranking: any }>('/reviews/apply-ranking', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function reindexRag(params: { companyId?: number; reset?: boolean } = {}) {
  // DB에 저장된 문서를 다시 chunking/embedding해 RAG index를 재구성한다.
  return request<{ status: string; inserted_chunks: number }>('/rag/reindex', {
    method: 'POST',
    params: {
      company_id: params.companyId,
      reset: params.reset !== false ? 'true' : 'false',
    },
  });
}

export function searchSimilarChunks(params: { query: string; companyId: number; processId?: number; topK?: number }) {
  // RAG 검색 품질을 UI에서 빠르게 확인하기 위한 similarity search endpoint.
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
  // 파일 업로드는 browser가 multipart boundary를 자동 생성해야 하므로 Content-Type을 직접 넣지 않는다.
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

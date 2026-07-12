// AX Delivery Planner dashboard SPA.
// 백엔드 FastAPI endpoint를 호출해 문서 ingestion, RAG 검색, Supervisor 분석, HITL review를 한 화면에서 실행한다.
import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from './api';
import './App.css';

// 화면은 독립 route를 쓰지 않고 탭 상태만으로 전환한다.
type Tab = 'dashboard' | 'ingestion' | 'analysis' | 'settings';

// 화면 하단 console에 남기는 사용자 친화적 실행 로그 형식.
interface LogLine {
  text: string;
  type: 'info' | 'success' | 'error';
  timestamp: string;
}

type Candidate = Record<string, any>;

function asNumber(value: any): number | null {
  // backend가 숫자를 문자열로 내려줘도 화면 계산에는 숫자로 정규화한다.
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatValue(value: any): string {
  // compliance summary처럼 값 형태가 다양한 응답을 UI에 안전하게 표시한다.
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function formatPercent(value: any): string {
  const parsed = asNumber(value);
  return parsed === null ? '-' : `${parsed.toFixed(parsed % 1 === 0 ? 0 : 1)}%`;
}

function formatMoney(value: any): string {
  const parsed = asNumber(value);
  if (parsed === null) return '-';
  return `${Math.round(parsed).toLocaleString()}원`;
}

function formatUsd(value: any): string {
  const parsed = asNumber(value);
  if (parsed === null) return '-';
  return `$${parsed.toFixed(parsed < 1 ? 4 : 2)}`;
}

function getAnalysisCandidates(result: api.AnalysisResponse | null): Candidate[] {
  // 화면은 임시 후보를 만들지 않고, backend 응답에 들어온 후보만 표시한다.
  return Array.isArray(result?.top_candidates) ? result.top_candidates : [];
}

function getCandidateId(candidate: Candidate, fallbackIndex = 0): string | number {
  return candidate.process_id ?? candidate.id ?? candidate.rank ?? fallbackIndex + 1;
}

function getCandidateName(candidate: Candidate): string {
  return candidate.candidate_agent_name || candidate.name || candidate.process_name || `프로세스 ID ${candidate.process_id ?? '-'}`;
}

function getCandidateScore(candidate: Candidate): number | null {
  return asNumber(candidate.final_score ?? candidate.score ?? candidate.confidence_score ?? candidate.total_score);
}

function getCandidateStatus(candidate: Candidate): string {
  return String(candidate.agent_decision_status || candidate.status || candidate.predicted_status || 'unknown');
}

function getStatusBadgeClass(status: string): string {
  const normalized = status.toLowerCase();
  if (['recommended', 'approved', 'pass', 'ok'].includes(normalized)) return 'badge-success';
  if (['excluded', 'blocked', 'rejected', 'evidence_insufficient'].includes(normalized)) return 'badge-danger';
  if (['human_review_required', 'auto_replan_required', 'review', 'pending'].includes(normalized)) return 'badge-warning';
  return 'badge-info';
}

function getRiskLabel(candidate: Candidate): string {
  const riskLevel = candidate.risk_level || candidate.governance_risk || candidate.compliance_level;
  if (riskLevel) return String(riskLevel);
  const riskScore = asNumber(candidate.risk_score);
  if (riskScore === null) return '-';
  if (riskScore >= 4) return '높음';
  if (riskScore >= 2) return '보통';
  return '낮음';
}

function getRiskBadgeClass(candidate: Candidate): string {
  const riskText = getRiskLabel(candidate).toLowerCase();
  const riskScore = asNumber(candidate.risk_score);
  if (riskText.includes('high') || riskText.includes('높') || (riskScore !== null && riskScore >= 4)) return 'badge-danger';
  if (riskText.includes('medium') || riskText.includes('보통') || (riskScore !== null && riskScore >= 2)) return 'badge-warning';
  return 'badge-success';
}

function getCandidateSavingLabel(candidate: Candidate): string {
  if (candidate.saving_rate !== undefined && candidate.saving_rate !== null) {
    return `${formatPercent(candidate.saving_rate)} 절감`;
  }
  if (candidate.monthly_saving !== undefined && candidate.monthly_saving !== null) {
    return `${formatMoney(candidate.monthly_saving)} 절감`;
  }
  return '-';
}

function getCandidateFeasibilityLabel(candidate: Candidate): string {
  const value = candidate.feasibility ?? candidate.automation_feasibility ?? candidate.feasibility_score ?? candidate.readiness_status;
  return formatValue(value);
}

function getComplianceEntries(summary?: Record<string, any>): Array<[string, string]> {
  return Object.entries(summary || {}).map(([key, value]) => [key, formatValue(value)]);
}

function getRoiCandidate(candidates: Candidate[]): Candidate | null {
  return candidates.find((candidate) => (
    candidate.saving_rate !== undefined ||
    candidate.monthly_saving !== undefined ||
    candidate.current_cost !== undefined ||
    candidate.expected_cost !== undefined
  )) || candidates[0] || null;
}

function getBaselineCost(candidate: Candidate | null): number | null {
  if (!candidate) return null;
  return asNumber(candidate.current_cost ?? candidate.baseline_cost ?? candidate.current_monthly_cost ?? candidate.baseline_monthly_cost);
}

function getExpectedCost(candidate: Candidate | null): number | null {
  if (!candidate) return null;
  return asNumber(candidate.expected_cost ?? candidate.agent_cost ?? candidate.expected_monthly_cost ?? candidate.estimated_cost);
}

function getAfterCostPercent(candidate: Candidate | null): number | null {
  const baseline = getBaselineCost(candidate);
  const expected = getExpectedCost(candidate);
  if (baseline !== null && baseline > 0 && expected !== null) {
    return Math.max(0, Math.min(100, (expected / baseline) * 100));
  }
  const savingRate = asNumber(candidate?.saving_rate);
  if (savingRate !== null) {
    return Math.max(0, Math.min(100, 100 - savingRate));
  }
  return null;
}

export default function App() {
  // Navigation & Health: 현재 탭과 backend 연결 상태를 관리한다.
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [apiStatus, setApiStatus] = useState<'checking' | 'ok' | 'unreachable'>('checking');

  // Settings state: API key/role/user ID는 localStorage에 저장해 새로고침 후에도 유지한다.
  const [apiKey, setApiKey] = useState(localStorage.getItem('ax_api_key') || '');
  const [userRole, setUserRole] = useState(localStorage.getItem('ax_user_role') || 'admin');
  const [userId, setUserId] = useState(localStorage.getItem('ax_user_id') || 'admin-user');
  const [companyId, setCompanyId] = useState<number>(1);
  const [projectId, setProjectId] = useState<number>(1);

  // Dashboard state: 홈 화면은 mock 대신 backend summary API에서 받은 실제 DB/실행 요약만 표시한다.
  const [dashboardSummary, setDashboardSummary] = useState<api.DashboardSummaryResponse | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState('');

  // Ingestion state: 문서 업로드 form, 보안 등급, process 연결값을 관리한다.
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [uploadMsg, setUploadMsg] = useState('');
  const [docTitle, setDocTitle] = useState('');
  const [docType, setDocType] = useState('SOP');
  const [docDept, setDocDept] = useState('생산관리팀');
  const [docSecurity, setDocSecurity] = useState('internal');
  const [docProcessId, setDocProcessId] = useState('');

  // RAG Search & Indexer state: 색인 재생성과 similarity 검색 결과를 관리한다.
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [reindexing, setReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState('');

  // Analysis state: Supervisor graph 실행 여부와 분석 응답 payload를 보관한다.
  const [runningAnalysis, setRunningAnalysis] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<api.AnalysisResponse | null>(null);
  const [autoApprove, setAutoApprove] = useState(true);

  // HITL state: 자동 승인되지 않은 후보를 사람이 재정렬/승인할 때 쓰는 임시 상태다.
  const [hitlDecision, setHitlDecision] = useState<'approve' | 'edit' | 'reject'>('edit');
  const [hitlReason, setHitlReason] = useState('');
  const [hitlCandidates, setHitlCandidates] = useState<any[]>([]);
  const [submittingReview, setSubmittingReview] = useState(false);
  const [reviewResultMsg, setReviewResultMsg] = useState('');

  // Log outputs: backend 작업이 오래 걸릴 때 사용자가 흐름을 볼 수 있도록 화면 console에 누적한다.
  const [consoleLogs, setConsoleLogs] = useState<LogLine[]>([]);
  const consoleBottomRef = useRef<HTMLDivElement>(null);

  const addLog = (text: string, type: 'info' | 'success' | 'error' = 'info') => {
    // 로그마다 표시 시간을 붙여 실행 순서를 눈으로 추적하기 쉽게 만든다.
    const time = new Date().toLocaleTimeString();
    setConsoleLogs((prev) => [...prev, { text, type, timestamp: time }]);
  };

  const loadDashboardSummary = useCallback(() => {
    // 홈 화면은 여기서 받은 값만 사용한다. 실패하면 기존 summary를 유지하고 error만 표시한다.
    setDashboardLoading(true);
    setDashboardError('');
    api.getDashboardSummary({ companyId, projectId })
      .then((res) => {
        setDashboardSummary(res);
        setDashboardLoading(false);
      })
      .catch((err) => {
        setDashboardLoading(false);
        setDashboardError(err.message);
      });
  }, [companyId, projectId]);

  useEffect(() => {
    // 새 로그가 추가되면 console 영역을 맨 아래로 자동 스크롤한다.
    if (consoleBottomRef.current) {
      consoleBottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [consoleLogs]);

  useEffect(() => {
    // backend 연결이 확인된 뒤 실제 dashboard summary를 불러온다.
    if (apiStatus === 'ok') {
      loadDashboardSummary();
    }
  }, [apiStatus, loadDashboardSummary]);

  // API 설정이 바뀌거나 화면이 처음 열릴 때 backend health를 다시 확인한다.
  useEffect(() => {
    setApiStatus('checking');
    addLog('Checking backend connection...', 'info');
    api.getHealth()
      .then(() => {
        setApiStatus('ok');
        addLog('Successfully connected to AX Delivery Planner API backend!', 'success');
      })
      .catch((err) => {
        setApiStatus('unreachable');
        addLog(`Backend unreachable: ${err.message}`, 'error');
      });
  }, [apiKey, userRole, userId]);

  // 설정 탭에서 입력한 인증/사용자 정보를 localStorage에 저장한다.
  const saveSettings = () => {
    localStorage.setItem('ax_api_key', apiKey);
    localStorage.setItem('ax_user_role', userRole);
    localStorage.setItem('ax_user_id', userId);
    addLog(`Configuration saved: Role=${userRole}, ID=${userId}`, 'success');
  };

  // RAG 재색인: backend가 DB 문서를 다시 chunking하고 embedding table을 갱신한다.
  const triggerReindex = () => {
    setReindexing(true);
    setReindexMsg('Reindexing documents...');
    addLog(`Triggered RAG reindexing for Company ID ${companyId}...`, 'info');
    
    api.reindexRag({ companyId, reset: true })
      .then((res) => {
        setReindexing(false);
        setReindexMsg(`Successfully created ${res.inserted_chunks} chunks.`);
        addLog(`Reindexing successful. Created ${res.inserted_chunks} document chunks.`, 'success');
        loadDashboardSummary();
      })
      .catch((err) => {
        setReindexing(false);
        setReindexMsg(`Error: ${err.message}`);
        addLog(`Reindexing failed: ${err.message}`, 'error');
      });
  };

  // RAG 검색: 사용자가 입력한 질의를 backend similarity search endpoint로 전달한다.
  const runSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery) return;
    setIsSearching(true);
    addLog(`Searching RAG index for "${searchQuery}"...`, 'info');

    api.searchSimilarChunks({
      query: searchQuery,
      companyId,
      topK: 4
    })
      .then((res) => {
        setIsSearching(false);
        setSearchResults(res.results || []);
        addLog(`Found ${res.results?.length || 0} matching chunks.`, 'success');
      })
      .catch((err) => {
        setIsSearching(false);
        addLog(`RAG search failed: ${err.message}`, 'error');
      });
  };

  // 문서 업로드: file + metadata를 multipart form으로 만들어 ingestion endpoint에 전달한다.
  const handleUpload = (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) {
      addLog('No file selected for ingestion.', 'error');
      return;
    }

    setUploadProgress('uploading');
    setUploadMsg('Sending file payload to ingestion endpoint...');
    addLog(`Starting ingestion for "${uploadFile.name}"...`, 'info');

    const formData = new FormData();
    formData.append('file', uploadFile);
    formData.append('company_id', String(companyId));
    formData.append('title', docTitle || uploadFile.name);
    formData.append('document_type', docType);
    formData.append('department', docDept);
    formData.append('security_level', docSecurity);
    if (docProcessId) {
      formData.append('process_id', docProcessId);
    }
    formData.append('index', 'true');

    api.ingestDocument(formData)
      .then((res) => {
        setUploadProgress('success');
        setUploadMsg('Ingested and indexed successfully!');
        addLog(`Ingestion successful for ${uploadFile.name}. Result ID: ${res.result?.id || 'OK'}`, 'success');
        setUploadFile(null);
        setDocTitle('');
        loadDashboardSummary();
      })
      .catch((err) => {
        setUploadProgress('error');
        setUploadMsg(err.message);
        addLog(`Ingestion failed: ${err.message}`, 'error');
      });
  };

  // AX 분석 실행: Supervisor graph를 호출하고, 응답이 interrupt면 HITL 후보 UI를 준비한다.
  const handleAnalysis = () => {
    setRunningAnalysis(true);
    setAnalysisResult(null);
    setHitlCandidates([]);
    addLog(`Running AX Prioritization Analysis for Company ID ${companyId}, Project ID ${projectId}...`, 'info');

    api.runAnalysis({
      projectId,
      companyId,
      autoApprove: autoApprove
    })
      .then((res) => {
        setRunningAnalysis(false);
        setAnalysisResult(res);

        if (res.status === 'interrupted') {
          addLog('Analysis interrupted: Waiting for Human Review (HITL).', 'info');
          const actualCandidates = getAnalysisCandidates(res);
          setHitlCandidates(actualCandidates);
          
          try {
            // interrupt payload는 길 수 있으므로 console에는 앞부분만 보여준다.
            const rawInterrupt = res.interrupt || '';
            addLog(`Interrupt payload: ${rawInterrupt.substring(0, 150)}...`, 'info');
          } catch {}

          if (actualCandidates.length === 0) {
            addLog('Human Review payload did not include top_candidates. Candidate list stays empty until the backend returns real candidates.', 'info');
          }
        } else {
          addLog(`Prioritization analysis complete. DOCX Report generated: ${res.report_docx_path || 'outputs/'}`, 'success');
        }
        loadDashboardSummary();
      })
      .catch((err) => {
        setRunningAnalysis(false);
        addLog(`Analysis failed: ${err.message}`, 'error');
      });
  };

  // HITL 후보 재정렬 helper. 위/아래 버튼이 이 함수를 호출해 ranking 순서를 바꾼다.
  const moveCandidate = (index: number, direction: 'up' | 'down') => {
    const nextList = [...hitlCandidates];
    const targetIdx = direction === 'up' ? index - 1 : index + 1;
    if (targetIdx < 0 || targetIdx >= nextList.length) return;
    
    const temp = nextList[index];
    nextList[index] = nextList[targetIdx];
    nextList[targetIdx] = temp;
    setHitlCandidates(nextList);
  };

  // HITL 결정 제출: 사람이 조정한 ranking과 사유를 backend review endpoint로 보낸다.
  const submitReview = () => {
    if (!analysisResult) return;
    setSubmittingReview(true);
    setReviewResultMsg('');
    addLog(`Submitting Human Review decision: "${hitlDecision}"...`, 'info');

    const promoteIds = hitlCandidates.slice(0, 2).map((c, index) => getCandidateId(c, index));
    const excludeIds = hitlCandidates
      .filter((c) => ['excluded', 'blocked', 'evidence_insufficient'].includes(getCandidateStatus(c)) || getRiskBadgeClass(c) === 'badge-danger')
      .map((c, index) => getCandidateId(c, index));
    
    const payload = {
      priority_ranking: {
        items: hitlCandidates.map((c, i) => ({
          ...c,
          process_id: getCandidateId(c, i),
          rank: i + 1,
          name: getCandidateName(c),
        }))
      },
      human_review: {
        decision: hitlDecision,
        comment: hitlReason,
        edited_payload: {
          promote_process_ids: promoteIds,
          exclude_process_ids: excludeIds,
          reason_overrides: Object.fromEntries(
            hitlCandidates.map((c, i) => [String(getCandidateId(c, i)), hitlReason || '화면에서 검토자가 입력한 판단을 반영'])
          )
        }
      }
    };

    api.applyReviewToRanking(payload)
      .then(() => {
        setSubmittingReview(false);
        setReviewResultMsg('Review applied successfully!');
        addLog('Human review applied to ranking output.', 'success');
        addLog('DOCX report finalized with customized priorities.', 'success');
      })
      .catch((err) => {
        setSubmittingReview(false);
        setReviewResultMsg(`Failed: ${err.message}`);
        addLog(`Failed to apply review: ${err.message}`, 'error');
      });
  };

  const analysisCandidates = getAnalysisCandidates(analysisResult);
  const complianceEntries = getComplianceEntries(analysisResult?.compliance_summary);
  const roiCandidate = getRoiCandidate(analysisCandidates);
  const roiBaselineCost = getBaselineCost(roiCandidate);
  const roiExpectedCost = getExpectedCost(roiCandidate);
  const roiAfterPercent = getAfterCostPercent(roiCandidate);
  const estimatedTotalCost = analysisResult?.total_cost_summary?.estimated_total_cost_usd;
  const recentModelDecisions = analysisResult?.model_decisions || [];
  const dashboardCompany = dashboardSummary?.company;
  const dashboardProject = dashboardSummary?.project;
  const dashboardCounts = dashboardSummary?.counts || {};
  const dashboardWorkflow = dashboardSummary?.workflow || {};
  const dashboardTopCandidates = Array.isArray(dashboardWorkflow.top_candidates) ? dashboardWorkflow.top_candidates : [];
  const dashboardCostSummary = dashboardWorkflow.total_cost_summary || {};
  const dashboardCost = dashboardCostSummary.estimated_total_cost_usd ?? dashboardWorkflow.estimated_total_cost_usd;
  const companyMeta = [dashboardCompany?.industry, dashboardCompany?.size].filter(Boolean).join(' · ');
  const companyLabel = dashboardCompany ? `${dashboardCompany.name}${companyMeta ? ` (${companyMeta})` : ''}` : dashboardLoading ? '불러오는 중...' : '선택된 기업 정보 없음';
  const projectLabel = dashboardProject?.title || (dashboardLoading ? '불러오는 중...' : '선택된 프로젝트 정보 없음');
  const dashboardDescription = dashboardCompany?.description || '선택된 기업의 DB 업무, 문서, RAG 색인, 최근 Supervisor 실행 결과를 기준으로 표시합니다.';
  const ragReady = (dashboardCounts.document_chunks || 0) > 0;
  const workflowReady = Boolean(dashboardWorkflow.state_file_path);

  return (
    <div className="app-container">
      {/* 사이드바 내비게이션 */}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">AX</div>
          <div className="brand-name">AX 플래너</div>
        </div>

        <nav>
          <ul className="nav-links">
            <li>
              <button
                className={`nav-item ${activeTab === 'dashboard' ? 'active' : ''}`}
                onClick={() => setActiveTab('dashboard')}
              >
                📊 대시보드 홈
              </button>
            </li>
            <li>
              <button
                className={`nav-item ${activeTab === 'ingestion' ? 'active' : ''}`}
                onClick={() => setActiveTab('ingestion')}
              >
                📂 사내 문서 & RAG 관리
              </button>
            </li>
            <li>
              <button
                className={`nav-item ${activeTab === 'analysis' ? 'active' : ''}`}
                onClick={() => setActiveTab('analysis')}
              >
                ⚡ AI 에이전트 우선순위 분석
              </button>
            </li>
            <li>
              <button
                className={`nav-item ${activeTab === 'settings' ? 'active' : ''}`}
                onClick={() => setActiveTab('settings')}
              >
                ⚙️ 시스템 설정
              </button>
            </li>
          </ul>
        </nav>
      </aside>

      {/* 메인 콘텐츠 영역 */}
      <main className="main-content">
        {/* 헤더 바 */}
        <header className="header">
          <h2 className="header-title">
            {activeTab === 'dashboard' && 'AX 도입 사전진단 대시보드'}
            {activeTab === 'ingestion' && '사내 지식 문서 업로드 & 관리'}
            {activeTab === 'analysis' && 'AI Agent 우선순위 평가 및 추천'}
            {activeTab === 'settings' && '인증 및 시스템 연동 설정'}
          </h2>
          <div className="header-actions">
            <div className="api-status">
              <span className={`status-dot ${apiStatus}`} />
              서버 상태: {apiStatus === 'ok' ? '연결됨 (정상)' : apiStatus === 'checking' ? '확인 중...' : '연결 끊김 (포트 8001 확인)'}
            </div>
            {apiStatus === 'unreachable' && (
              <span style={{ color: 'var(--color-danger)', fontSize: '12px', fontWeight: 'bold' }}>
                로컬 백엔드 서버를 실행해 주세요 (포트 8001).
              </span>
            )}
          </div>
        </header>

        {/* 탭 콘텐츠 */}
        <div className="dashboard-body">
          {/* 탭: 대시보드 홈 */}
          {activeTab === 'dashboard' && (
            <div className="dashboard-grid">
              <div className="col-12 card" style={{ padding: '16px 20px', backgroundColor: 'var(--bg-tertiary)', borderLeft: '4px solid var(--accent-primary)', marginBottom: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                  <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)' }}>
                    📊 <strong>대시보드 홈</strong>: 백엔드 DB와 최근 Supervisor 실행 결과를 기준으로 현재 프로젝트 상태를 표시합니다.
                  </p>
                  <button className="btn btn-secondary" onClick={() => loadDashboardSummary()} disabled={dashboardLoading}>
                    {dashboardLoading ? '불러오는 중...' : '실제 데이터 새로고침'}
                  </button>
                </div>
              </div>

              {dashboardError && (
                <div className="col-12 card" style={{ padding: '14px 18px', borderLeft: '4px solid var(--color-danger)' }}>
                  <p style={{ margin: 0, fontSize: '13px', color: 'var(--color-danger)' }}>
                    대시보드 실제 데이터 조회 실패: {dashboardError}
                  </p>
                </div>
              )}

              {/* 프로젝트 소개 및 가치 정의 카드 */}
              <div className="col-12 card project-goal-card">
                <div className="card-header">
                  <h3 className="card-title">🎯 프로젝트 개요 및 기획 목표 (AX Delivery Planner)</h3>
                </div>
                <div style={{ fontSize: '13px', lineHeight: '1.6', color: 'var(--text-secondary)', padding: '4px 0' }}>
                  <p style={{ marginBottom: '12px' }}>
                    선택된 기업의 업무 프로세스, 사내 지식 문서, 시스템 정보를 기반으로 <strong>AI Agent 도입 후보와 PoC 우선순위</strong>를 계산하는 Multi-Agent 분석 화면입니다.
                  </p>
                  <p style={{ marginBottom: '12px' }}>
                    <strong>AX Delivery Planner</strong>는 DB에 적재된 문서와 RAG 색인, Supervisor 실행 trace, 모델 선택 비용 요약을 함께 확인해 최종 보고서 생성 상태까지 추적합니다.
                  </p>
                  <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginTop: '16px' }}>
                    <div style={{ flex: '1', minWidth: '250px', padding: '14px', borderRadius: '8px', backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                      <strong>👥 주 권장 사용자</strong>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
                        IT기획팀, AX/DX 추진실, 생산혁신팀, 현업 부서장 및 안전·보안 거버넌스 담당 임원진
                      </div>
                    </div>
                    <div style={{ flex: '1', minWidth: '250px', padding: '14px', borderRadius: '8px', backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
                      <strong>⚖️ AI 협업 가치 (Human-in-the-Loop)</strong>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
                        AI는 RAG 기반 근거 수집 및 정량 평가를 수립하고, 최종 순위 조정 및 의사결정 권한은 사람이 통제합니다.
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="col-8 card">
                <div className="card-header">
                  <h3 className="card-title">진행 중인 진단 정보</h3>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div className="form-row">
                    <div className="form-group">
                      <label className="form-label">진단 대상 기업</label>
                      <div className="form-control" style={{ backgroundColor: 'var(--bg-tertiary)', fontWeight: 'bold' }}>
                        {companyLabel}
                      </div>
                    </div>
                    <div className="form-group">
                      <label className="form-label">적용 프로젝트명</label>
                      <div className="form-control" style={{ backgroundColor: 'var(--bg-tertiary)', fontWeight: 'bold' }}>
                        {projectLabel}
                      </div>
                    </div>
                  </div>
                  <div style={{ padding: '16px', borderRadius: '8px', backgroundColor: 'var(--bg-tertiary)', fontSize: '13px' }}>
                    <p><strong>설명:</strong> {dashboardDescription}</p>
                    <p style={{ marginTop: '8px', color: 'var(--text-muted)' }}>
                      Project ID {dashboardProject?.id ?? projectId} · Company ID {dashboardCompany?.id ?? companyId} · 프로젝트 상태 {dashboardProject?.status || '-'}
                    </p>
                  </div>
                </div>
              </div>

              <div className="col-4 card">
                <div className="card-header">
                  <h3 className="card-title">구축 데이터 현황</h3>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                    <span>평가 대상 업무 프로세스</span>
                    <strong>{dashboardCounts.business_processes ?? 0}개</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                    <span>인덱싱된 지식 문서 수</span>
                    <strong>{dashboardCounts.documents ?? 0}건</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                    <span>사내 시스템 수</span>
                    <strong>{dashboardCounts.enterprise_systems ?? 0}개</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                    <span>RAG 벡터 지식베이스</span>
                    <span className={`badge ${ragReady ? 'badge-success' : 'badge-warning'}`} style={{ fontWeight: 'bold' }}>
                      {ragReady ? `${dashboardCounts.document_chunks} chunks` : '미색인'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                    <span>감사 로그</span>
                    <span className={`badge ${(dashboardCounts.audit_logs ?? 0) > 0 ? 'badge-success' : 'badge-info'}`} style={{ fontWeight: 'bold' }}>
                      {dashboardCounts.audit_logs ?? 0}건
                    </span>
                  </div>
                </div>
              </div>

              {/* 최근 실제 workflow 실행 요약 */}
              <div className="col-12 card">
                <div className="card-header">
                  <h3 className="card-title">📊 최근 실제 분석 실행 요약</h3>
                </div>
                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: 0 }}>
                  Supervisor graph가 생성한 workflow_state와 비용 집계가 있을 때만 값이 표시됩니다.
                </p>
                <div className="weight-grid">
                  <div className="weight-item">
                    <span className="weight-label">🏁 실행 상태</span>
                    <span className="weight-val">{workflowReady ? '기록 있음' : '분석 전'}</span>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{dashboardWorkflow.state_file_path || 'workflow_state_real.json 없음'}</span>
                  </div>
                  <div className="weight-item">
                    <span className="weight-label">⭐ 후보 수</span>
                    <span className="weight-val">{dashboardWorkflow.top_candidate_count ?? 0}</span>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>최근 우선순위 후보</span>
                  </div>
                  <div className="weight-item">
                    <span className="weight-label">🧠 모델 결정</span>
                    <span className="weight-val">{dashboardWorkflow.agent_model_decision_count ?? 0}</span>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Supervisor/Agent routing</span>
                  </div>
                  <div className="weight-item">
                    <span className="weight-label">🧰 Tool 호출</span>
                    <span className="weight-val">{dashboardWorkflow.agent_tool_call_count ?? 0}</span>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>자율 실행 trace</span>
                  </div>
                  <div className="weight-item">
                    <span className="weight-label">💵 예상 LLM 비용</span>
                    <span className="weight-val">{formatUsd(dashboardCost)}</span>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{dashboardCostSummary.currency || 'USD'} 기준 추정</span>
                  </div>
                  <div className="weight-item" style={{ border: `1px dashed ${(dashboardWorkflow.error_count ?? 0) > 0 ? '#f87171' : 'var(--border-color)'}` }}>
                    <span className="weight-label" style={{ color: (dashboardWorkflow.error_count ?? 0) > 0 ? '#f87171' : 'var(--text-secondary)' }}>⚠️ 오류</span>
                    <span className="weight-val" style={{ color: (dashboardWorkflow.error_count ?? 0) > 0 ? '#f87171' : 'var(--text-primary)' }}>{dashboardWorkflow.error_count ?? 0}</span>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>workflow errors</span>
                  </div>
                </div>
                <div style={{ marginTop: '16px', padding: '12px 16px', borderRadius: '6px', backgroundColor: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <strong>📄 산출물 상태</strong>
                  <span style={{ color: 'var(--text-secondary)' }}>보고서: <strong>{dashboardWorkflow.report_docx_path || '아직 생성된 보고서 없음'}</strong></span>
                  <span style={{ color: 'var(--text-secondary)' }}>Citation 검증: <strong>{dashboardWorkflow.citation_validated === undefined || dashboardWorkflow.citation_validated === null ? '-' : dashboardWorkflow.citation_validated ? '통과' : '확인 필요'}</strong> · 이슈 {dashboardWorkflow.citation_issue_count ?? 0}건</span>
                  {dashboardWorkflow.report_docx_path && (
                    <a className="btn btn-secondary" href={api.buildBackendAssetUrl(dashboardWorkflow.report_docx_path)} style={{ width: 'fit-content', marginTop: '4px' }}>
                      보고서 다운로드
                    </a>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <strong style={{ fontSize: '13px' }}>최근 후보 Top {dashboardTopCandidates.length}</strong>
                  {dashboardTopCandidates.length > 0 ? (
                    dashboardTopCandidates.map((candidate, index) => (
                      <div key={`${getCandidateId(candidate, index)}-${index}`} style={{ display: 'grid', gridTemplateColumns: '48px minmax(0, 1fr) minmax(72px, 110px) minmax(80px, 100px)', gap: '12px', alignItems: 'center', padding: '10px 12px', border: '1px solid var(--border-color)', borderRadius: '8px', backgroundColor: 'var(--bg-tertiary)', fontSize: '12px' }}>
                        <strong>#{candidate.rank ?? index + 1}</strong>
                        <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>{getCandidateName(candidate)}</span>
                        <span>{getCandidateScore(candidate) !== null ? `${getCandidateScore(candidate)?.toFixed(1)}점` : '-'}</span>
                        <span className={`badge ${getStatusBadgeClass(getCandidateStatus(candidate))}`} style={{ overflowWrap: 'anywhere', textAlign: 'center' }}>{getCandidateStatus(candidate)}</span>
                      </div>
                    ))
                  ) : (
                    <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>
                      아직 최근 분석 후보가 없습니다. 분석 탭에서 Supervisor graph를 실행하면 실제 후보 목록이 여기에 표시됩니다.
                    </p>
                  )}
                </div>
              </div>

              {/* 시스템 이력 로그 */}
              <div className="col-12 card">
                <div className="card-header">
                  <h3 className="card-title">실시간 시스템 동작 로그</h3>
                </div>
                <div className="console-box">
                  {consoleLogs.map((log, index) => (
                    <div key={index} className={`console-line ${log.type}`}>
                      [{log.timestamp}] {log.text}
                    </div>
                  ))}
                  <div ref={consoleBottomRef} />
                </div>
              </div>
            </div>
          )}

          {/* 탭: 사내 문서 및 RAG 관리 */}
          {activeTab === 'ingestion' && (
            <div className="dashboard-grid">
              <div className="col-12 card" style={{ padding: '16px 20px', backgroundColor: 'var(--bg-tertiary)', borderLeft: '4px solid var(--accent-primary)', marginBottom: '8px' }}>
                <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)' }}>
                  📂 <strong>사내 문서 & RAG 관리</strong>: 표준업무절차서(SOP), 매뉴얼 등 신규 문서를 업로드해 AI의 RAG 지식베이스에 추가하거나, 등록된 데이터의 본문 매칭 결과를 즉시 검색하고 검증합니다.
                </p>
              </div>
              <div className="col-6 card">
                <div className="card-header">
                  <h3 className="card-title">사내 지식 문서 신규 등록</h3>
                </div>
                <form onSubmit={handleUpload} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div className="form-group">
                    <label className="form-label">분석용 문서 선택 (.txt, .md, .pdf, .docx)</label>
                    <input
                      type="file"
                      className="form-control"
                      onChange={(e) => {
                        const files = e.target.files;
                        if (files && files.length > 0) {
                          setUploadFile(files[0]);
                          setDocTitle(files[0].name.replace(/\.[^/.]+$/, ""));
                        }
                      }}
                      required
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label">문서 제목 지정 (미입력 시 파일명 사용)</label>
                    <input
                      type="text"
                      className="form-control"
                      value={docTitle}
                      onChange={(e) => setDocTitle(e.target.value)}
                      placeholder="문서 제목을 입력하세요."
                    />
                  </div>

                  <div className="form-row">
                    <div className="form-group">
                      <label className="form-label">문서 분류</label>
                      <select className="form-control" value={docType} onChange={(e) => setDocType(e.target.value)}>
                        <option value="SOP">표준작업절차서 (SOP)</option>
                        <option value="Manual">시스템 매뉴얼 (Manual)</option>
                        <option value="Guideline">업무 가이드라인 (Guideline)</option>
                        <option value="Policy">보안/거버넌스 규정 (Policy)</option>
                      </select>
                    </div>
                    <div className="form-group">
                      <label className="form-label">관련 담당 부서</label>
                      <select className="form-control" value={docDept} onChange={(e) => setDocDept(e.target.value)}>
                        <option value="생산관리팀">생산관리팀</option>
                        <option value="설비정비팀">설비정비팀</option>
                        <option value="품질관리팀">품질관리팀</option>
                        <option value="안전관리팀">안전관리팀</option>
                        <option value="IT기획팀">IT기획팀</option>
                      </select>
                    </div>
                  </div>

                  <div className="form-row">
                    <div className="form-group">
                      <label className="form-label">보안 수준 설정</label>
                      <select className="form-control" value={docSecurity} onChange={(e) => setDocSecurity(e.target.value)}>
                        <option value="public">일반 공개 (Public)</option>
                        <option value="internal">사내 열람 (Internal)</option>
                        <option value="confidential">대외비 (Confidential)</option>
                        <option value="restricted">제한적 접근 (Restricted)</option>
                      </select>
                    </div>
                    <div className="form-group">
                      <label className="form-label">연동할 업무 프로세스 번호 (선택)</label>
                      <input
                        type="number"
                        className="form-control"
                        value={docProcessId}
                        onChange={(e) => setDocProcessId(e.target.value)}
                        placeholder="예: 31"
                      />
                    </div>
                  </div>

                  <button type="submit" className="btn btn-primary" disabled={uploadProgress === 'uploading'}>
                    {uploadProgress === 'uploading' ? '문서 파싱 및 RAG 색인 중...' : '📥 문서 등록 및 RAG 인덱싱 시작'}
                  </button>

                  {uploadMsg && (
                    <div style={{ 
                      padding: '10px', 
                      borderRadius: '6px', 
                      fontSize: '13px',
                      backgroundColor: uploadProgress === 'success' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                      color: uploadProgress === 'success' ? 'var(--color-success)' : 'var(--color-danger)'
                    }}>
                      {uploadMsg === 'Ingested and indexed successfully!' ? '문서가 성공적으로 RAG 데이터베이스에 업로드 및 파싱되었습니다.' : uploadMsg}
                    </div>
                  )}
                </form>
              </div>

              <div className="col-6 card">
                <div className="card-header">
                  <h3 className="card-title">RAG 검색 테스트 및 지식베이스 재색인</h3>
                </div>
                
                {/* 관리자 특수 작업 */}
                <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label className="form-label" style={{ color: 'var(--color-warning)' }}>시스템 관리 도구</label>
                  <button className="btn btn-secondary" onClick={triggerReindex} disabled={reindexing}>
                    {reindexing ? '지식 조각(Chunk) 재생성 중...' : '🔄 RAG 인덱스 전체 재빌드'}
                  </button>
                  {reindexMsg && <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{reindexMsg}</p>}
                </div>

                {/* 지식 매칭 테스트 */}
                <form onSubmit={runSearch} style={{ display: 'flex', flexDirection: 'column', gap: '12px', paddingTop: '8px' }}>
                  <div className="form-group">
                    <label className="form-label">RAG 매칭 검색 테스트</label>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input
                        type="text"
                        className="form-control"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="검색어를 입력하세요 (예: 불량 원인 대조, SAP ERP)"
                      />
                      <button type="submit" className="btn btn-primary" disabled={isSearching}>검색</button>
                    </div>
                  </div>
                </form>

                {searchResults.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '200px', overflowY: 'auto', marginTop: '12px' }}>
                    {searchResults.map((chunk, index) => (
                      <div key={index} style={{ padding: '8px 12px', borderRadius: '6px', backgroundColor: 'var(--bg-tertiary)', fontSize: '12px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', fontWeight: 'bold' }}>
                          <span>문서 ID: {chunk.document_id || '알 수 없음'}</span>
                          <span className="badge badge-info">매칭 스코어: {(chunk.score || 0).toFixed(4)}</span>
                        </div>
                        <p style={{ color: 'var(--text-secondary)', wordBreak: 'break-all' }}>{chunk.content || chunk.text}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 탭: AI 에이전트 우선순위 분석 */}
          {activeTab === 'analysis' && (
            <div className="dashboard-grid">
              <div className="col-12 card" style={{ padding: '16px 20px', backgroundColor: 'var(--bg-tertiary)', borderLeft: '4px solid var(--accent-primary)', marginBottom: '8px' }}>
                <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)' }}>
                  ⚡ <strong>AI 에이전트 우선순위 분석</strong>: 기업 데이터를 바탕으로 부서별 AI 에이전트 도입 타당성 및 ROI를 분석해 PoC 추천 순위를 도출하고, 중간 검토(HITL)를 거쳐 최종 정식 워드 보고서(.docx)를 생성합니다.
                </p>
              </div>
              <div className="col-12 card">
                <div className="card-header">
                  <h3 className="card-title">우선순위 분석 엔진 실행</h3>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
                  <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                    <div className="form-group" style={{ width: '120px' }}>
                      <label className="form-label">기업 코드 ID</label>
                      <input
                        type="number"
                        className="form-control"
                        value={companyId}
                        onChange={(e) => setCompanyId(parseInt(e.target.value) || 1)}
                      />
                    </div>
                    <div className="form-group" style={{ width: '120px' }}>
                      <label className="form-label">프로젝트 ID</label>
                      <input
                        type="number"
                        className="form-control"
                        value={projectId}
                        onChange={(e) => setProjectId(parseInt(e.target.value) || 1)}
                      />
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '20px' }}>
                      <input
                        type="checkbox"
                        id="autoApprove"
                        checked={autoApprove}
                        onChange={(e) => setAutoApprove(e.target.checked)}
                      />
                      <label htmlFor="autoApprove" className="form-label" style={{ margin: 0, cursor: 'pointer' }}>
                        자동 최종 승인 실행 (검토 단계에서 일시정지 생략)
                      </label>
                    </div>
                  </div>
                  <button onClick={handleAnalysis} className="btn btn-primary" disabled={runningAnalysis}>
                    {runningAnalysis ? '⚡ AI 분석 및 보고서 작성 중... (약 1분 소요)' : '🚀 AX 우선순위 추천 및 보고서 생성 시작'}
                  </button>
                </div>

                {/* 분석 진행 중 친절한 피드백 표시 */}
                {runningAnalysis && (
                  <div className="analysis-loading-box">
                    <div className="spinner"></div>
                    <p style={{ fontSize: '15px', fontWeight: 'bold', color: 'var(--text-primary)' }}>
                      AI가 사내 업무 표준서와 시스템 매뉴얼을 다각도로 분석하고 있습니다.
                    </p>
                    <ul>
                      <li>🔍 RAG 기반 사내 문서 지식 데이터 매칭 및 수집</li>
                      <li>📊 업무별 자동화 가능성 및 ROI 예상 수치 시뮬레이션</li>
                      <li>⚖️ 보안, 개인정보, 내부 거버넌스 준수성 체크</li>
                      <li>🧠 Supervisor 모델 라우팅과 Agent별 검증 결과 수집</li>
                    </ul>
                    <p className="loading-hint">
                      ※ 실제 백엔드 workflow 실행 결과를 기다리는 중입니다. 완료까지는 데이터 양과 선택 모델에 따라 달라질 수 있습니다.
                    </p>
                  </div>
                )}
              </div>

              {/* 관리자 검토 (HITL) 패널 */}
              {analysisResult && (
                <div className="col-12 card" style={{ border: analysisResult.status === 'interrupted' ? '2px solid var(--color-warning)' : '1px solid var(--border-color)' }}>
                  <div className="card-header">
                    <h3 className="card-title">
                      {analysisResult.status === 'interrupted' ? '⚠️ 관리자 검토 대기 중 (분석 일시 정지)' : '✅ AI 에이전트 도입 추천 순위 결과'}
                    </h3>
                    <span className={`badge ${analysisResult.status === 'interrupted' ? 'badge-warning' : 'badge-success'}`}>
                      {analysisResult.status === 'interrupted' ? '검토 대기' : '완료'}
                    </span>
                  </div>

                  {analysisResult.status === 'interrupted' ? (
                    <div className="dashboard-grid">
                      <div className="col-8">
                        <p style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '16px' }}>
                          백엔드 분석 중 보안 및 거버넌스 검토 기준치에 의하여 검토 단계가 실행되었습니다. 후보들의 도입 순서를 변경하거나 의사를 결정해 주세요.
                        </p>

                        {hitlCandidates.length === 0 ? (
                          <div style={{ padding: '16px', borderRadius: '6px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)', fontSize: '13px' }}>
                            백엔드 응답에 검토 후보 목록이 포함되지 않았습니다. 실제 후보가 도착하면 이 영역에 표시됩니다.
                          </div>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                            {hitlCandidates.map((c, idx) => {
                              const status = getCandidateStatus(c);
                              const score = getCandidateScore(c);
                              return (
                            <div key={String(getCandidateId(c, idx))} className="rank-item">
                              <div>
                                <span style={{ fontWeight: 'bold', marginRight: '12px', color: 'var(--accent-primary)' }}>추천 #{idx + 1}순위</span>
                                <span style={{ fontWeight: '600' }}>{getCandidateName(c)}</span>
                                <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
                                  <span className={`badge ${getStatusBadgeClass(status)}`}>상태: {status}</span>
                                  <span className="badge badge-info">절감률: {getCandidateSavingLabel(c)}</span>
                                  <span className="badge badge-info">구현성: {getCandidateFeasibilityLabel(c)}</span>
                                  <span className={`badge ${getRiskBadgeClass(c)}`}>위험도: {getRiskLabel(c)}</span>
                                </div>
                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                  업무번호: {getCandidateId(c, idx)} {score !== null ? `| 점수: ${score.toFixed(2)}` : ''}
                                </div>
                              </div>

                              <div className="rank-controls">
                                <button className="rank-btn" onClick={() => moveCandidate(idx, 'up')} disabled={idx === 0}>▲ 위로</button>
                                <button className="rank-btn" onClick={() => moveCandidate(idx, 'down')} disabled={idx === hitlCandidates.length - 1}>▼ 아래로</button>
                              </div>
                            </div>
                              );
                            })}
                          </div>
                        )}
                      </div>

                      <div className="col-4" style={{ display: 'flex', flexDirection: 'column', gap: '16px', borderLeft: '1px solid var(--border-color)', paddingLeft: '24px' }}>
                        <div className="form-group">
                          <label className="form-label">최종 의사결정 방식</label>
                          <select className="form-control" value={hitlDecision} onChange={(e: any) => setHitlDecision(e.target.value)}>
                            <option value="edit">순위 조정 및 승인</option>
                            <option value="approve">제시된 원안 최종 승인</option>
                            <option value="reject">도입 반려</option>
                          </select>
                        </div>

                        <div className="form-group">
                          <label className="form-label">검토 의견 / 특이사항</label>
                          <textarea
                            className="form-control"
                            rows={4}
                            value={hitlReason}
                            onChange={(e) => setHitlReason(e.target.value)}
                            placeholder="우선순위를 수동으로 조정한 근거나 검토 사유를 작성하세요."
                          />
                        </div>

                        <button className="btn btn-primary" onClick={submitReview} disabled={submittingReview || hitlCandidates.length === 0}>
                          {submittingReview ? '제출 반영 중...' : '최종 의사결정 제출 및 완료'}
                        </button>

                        {reviewResultMsg && (
                          <div style={{ padding: '8px', borderRadius: '4px', backgroundColor: 'rgba(16, 185, 129, 0.1)', color: 'var(--color-success)', fontSize: '13px', textAlign: 'center' }}>
                            {reviewResultMsg === 'Review applied successfully!' ? '검토 결과가 성공적으로 반영되어 보고서가 완성되었습니다.' : reviewResultMsg}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div>
                      <p style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '16px' }}>
                        분석이 성공적으로 완료되었습니다. 최적의 AI Agent PoC 과제들이 선정되고 한글 정식 보고서가 생성되었습니다. 아래 다운로드 버튼을 눌러 확인하세요.
                      </p>

                      <div style={{ display: 'flex', gap: '12px', marginBottom: '20px' }}>
                        {analysisResult.report_docx_path && (
                          <a
                            href={api.buildBackendAssetUrl(analysisResult.report_docx_path)}
                            download
                            className="btn btn-primary"
                            style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
                          >
                            📥 최종 보고서 다운로드 (DOCX)
                          </a>
                        )}
                        <button
                          className="btn btn-secondary"
                          onClick={() => {
                            const elem = document.getElementById('report-preview-sheet');
                            if (elem) elem.scrollIntoView({ behavior: 'smooth' });
                          }}
                        >
                          📄 보고서 미리보기로 이동
                        </button>
                      </div>

                      <div className="form-row">
                        <div className="form-group">
                          <label className="form-label">최종 도입 추천 에이전트 (우선순위 순)</label>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            {analysisCandidates.length === 0 ? (
                              <div style={{ padding: '12px', borderRadius: '6px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)', fontSize: '13px' }}>
                                백엔드 응답에 top_candidates가 없습니다.
                              </div>
                            ) : (
                              analysisCandidates.map((c: Candidate, index: number) => {
                                const score = getCandidateScore(c);
                                const status = getCandidateStatus(c);
                                return (
                                  <div key={String(getCandidateId(c, index))} style={{ padding: '10px 14px', borderRadius: '6px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', fontSize: '13px', display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                                    <span><strong>#{index + 1}순위</strong> {getCandidateName(c)}</span>
                                    <span style={{ display: 'inline-flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                      <span className={`badge ${getStatusBadgeClass(status)}`}>{status}</span>
                                      <span className="badge badge-info">점수: {score !== null ? score.toFixed(2) : '-'}</span>
                                      <span className="badge badge-success">절감: {getCandidateSavingLabel(c)}</span>
                                    </span>
                                  </div>
                                );
                              })
                            )}
                          </div>
                        </div>
                        <div className="form-group">
                          <label className="form-label">보안성 및 거버넌스 진단 결과</label>
                          <div style={{ padding: '16px', borderRadius: '6px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', height: '100%', fontSize: '13px' }}>
                            {complianceEntries.length === 0 ? (
                              <span style={{ color: 'var(--text-secondary)' }}>compliance_summary가 비어 있습니다.</span>
                            ) : (
                              complianceEntries.map(([key, value]) => (
                                <div key={key} style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', marginBottom: '8px' }}>
                                  <strong>{key}:</strong>
                                  <span style={{ textAlign: 'right' }}>{value}</span>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      </div>

                      {/* ROI/비용 요약 카드 */}
                      <div className="roi-box">
                        <h4 style={{ fontSize: '14px', fontWeight: '700', color: 'var(--text-primary)', margin: '0 0 8px 0' }}>📈 백엔드 응답 기반 ROI / 실행 비용 요약</h4>
                        <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: 0 }}>
                          아래 값은 화면에서 만든 임시 값이 아니라 분석 응답의 후보 비용/절감률 및 모델 비용 집계를 그대로 표시합니다.
                        </p>
                        {roiCandidate ? (
                          <>
                            <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                              기준 후보: <strong>{getCandidateName(roiCandidate)}</strong>
                            </div>
                            <div className="roi-bar-wrapper">
                              <div className="roi-bar-item">
                                <span className="roi-bar-label">현재 비용</span>
                                <div className="roi-bar-track">
                                  <div className="roi-bar-fill before" style={{ width: '100%' }}>
                                    {roiBaselineCost !== null ? formatMoney(roiBaselineCost) : '응답값 없음'}
                                  </div>
                                </div>
                              </div>
                              <div className="roi-bar-item">
                                <span className="roi-bar-label">Agent 적용 후</span>
                                <div className="roi-bar-track">
                                  <div className="roi-bar-fill after" style={{ width: `${roiAfterPercent ?? 0}%` }}>
                                    {roiExpectedCost !== null ? `${formatMoney(roiExpectedCost)} (${formatPercent(roiAfterPercent)})` : getCandidateSavingLabel(roiCandidate)}
                                  </div>
                                </div>
                              </div>
                            </div>
                            <p style={{ fontSize: '12px', fontWeight: 'bold', color: 'var(--color-success)', marginTop: '12px', marginBottom: 0 }}>
                              절감률/절감액: {getCandidateSavingLabel(roiCandidate)}
                            </p>
                          </>
                        ) : (
                          <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '12px', marginBottom: 0 }}>
                            후보 비용 정보가 응답에 없어 ROI 막대를 표시하지 않았습니다.
                          </p>
                        )}
                        <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '8px', marginBottom: 0 }}>
                          모델 예상 비용 합계: <strong>{estimatedTotalCost !== undefined ? `$${Number(estimatedTotalCost).toFixed(6)}` : '-'}</strong>
                        </p>
                      </div>

                      {/* 실제 실행 trace 요약 카드 */}
                      <div className="card" style={{ marginTop: '16px' }}>
                        <div className="card-header">
                          <h3 className="card-title">실제 분석 trace 요약</h3>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', fontSize: '13px' }}>
                          <div style={{ padding: '12px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
                            <strong>인용 검증</strong>
                            <div style={{ marginTop: '8px', color: 'var(--text-secondary)' }}>
                              valid: {formatValue(analysisResult.citation_validation?.valid)}<br />
                              found: {formatValue(analysisResult.citation_validation?.found_count)}<br />
                              invalid: {formatValue(analysisResult.citation_validation?.invalid_labels)}
                            </div>
                          </div>
                          <div style={{ padding: '12px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
                            <strong>모델 선택</strong>
                            <div style={{ marginTop: '8px', color: 'var(--text-secondary)' }}>
                              {recentModelDecisions.length === 0 ? 'model_decisions 없음' : recentModelDecisions.slice(-3).map((item: any, index: number) => (
                                <div key={index}>{item.agent_id || item.call_kind}: {item.provider}/{item.model}</div>
                              ))}
                            </div>
                          </div>
                          <div style={{ padding: '12px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
                            <strong>오류</strong>
                            <div style={{ marginTop: '8px', color: 'var(--text-secondary)' }}>
                              {(analysisResult.errors || []).length === 0 ? '없음' : (analysisResult.errors || []).map((item: any, index: number) => (
                                <div key={index}>{formatValue(item)}</div>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* 실물 페이지 느낌의 미리보기 구현 */}
                      <div id="report-preview-sheet" className="document-preview-container">
                        <label className="form-label">📄 최종 보고서 실시간 인쇄 미리보기 (Preview)</label>
                        <div className="document-preview">
                          {analysisResult.report_data ? (
                            <>
                              <div className="preview-header">
                                <span className="preview-tag">
                                  {analysisResult.report_data.status === 'draft' ? 'AX 사전 진단 초안 보고서' : 'AX 사전 진단 최종 보고서'}
                                </span>
                                <h4 className="preview-title">{analysisResult.report_data.title}</h4>
                                <div className="preview-meta">
                                  작성일자: {analysisResult.report_data.date} {analysisResult.report_data.author ? `| 작성자: ${analysisResult.report_data.author}` : ''} | 분석 주체: AX Planner Multi-Agent System
                                </div>
                              </div>

                              {(analysisResult.report_data.sections || []).map((section: any, sIdx: number) => (
                                <div key={sIdx} className="preview-section" style={{ marginBottom: '24px' }}>
                                  <h5 className="preview-section-title" style={{ fontSize: '15px', fontWeight: '700', borderBottom: '1px solid #e2e8f0', paddingBottom: '6px', color: '#1e293b', marginTop: '16px', marginBottom: '12px' }}>
                                    {section.heading}
                                  </h5>
                                  {(section.blocks || []).map((block: any, bIdx: number) => {
                                    if (block.type === 'paragraph') {
                                      return (
                                        <p key={bIdx} className="preview-p" style={{ fontSize: '13px', lineHeight: '1.6', color: '#334155', marginBottom: '10px', textAlign: 'justify', wordBreak: 'keep-all' }}>
                                          {block.text}
                                        </p>
                                      );
                                    } else if (block.type === 'table') {
                                      return (
                                        <div key={bIdx} style={{ overflowX: 'auto', width: '100%', marginBottom: '14px', marginTop: '8px' }}>
                                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: `${block.font_size || 8}pt` }}>
                                            <thead>
                                              <tr style={{ backgroundColor: '#f8fafc', borderTop: '1px solid #cbd5e1', borderBottom: '1px solid #cbd5e1' }}>
                                                {(block.headers || []).map((header: string, hIdx: number) => (
                                                  <th key={hIdx} style={{ padding: '6px 8px', textAlign: 'left', fontWeight: 'bold', border: '1px solid #e2e8f0', color: '#334155' }}>
                                                    {header}
                                                  </th>
                                                ))}
                                              </tr>
                                            </thead>
                                            <tbody>
                                              {(block.rows || []).map((row: any[], rIdx: number) => (
                                                <tr key={rIdx} style={{ borderBottom: '1px solid #f1f5f9' }}>
                                                  {row.map((cell: any, cIdx: number) => (
                                                    <td key={cIdx} style={{ padding: '6px 8px', border: '1px solid #e2e8f0', color: '#475569', whiteSpace: 'pre-wrap' }}>
                                                      {cell}
                                                    </td>
                                                  ))}
                                                </tr>
                                              ))}
                                            </tbody>
                                          </table>
                                        </div>
                                      );
                                    }
                                    return null;
                                  })}
                                </div>
                              ))}
                            </>
                          ) : (
                            <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
                              <p>보고서 데이터가 비어 있거나 로드되지 않았습니다.</p>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 탭: 시스템 설정 */}
          {activeTab === 'settings' && (
            <div className="dashboard-grid">
              <div className="col-12 card" style={{ padding: '16px 20px', backgroundColor: 'var(--bg-tertiary)', borderLeft: '4px solid var(--accent-primary)', marginBottom: '8px' }}>
                <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)' }}>
                  ⚙️ <strong>시스템 설정</strong>: 백엔드 API 호출용 보안 인증 키(X-API-Key) 관리, 사용자 역할별 권한 테스트(Viewer/Analyst/Manager/Admin), 대상 기업/프로젝트 식별자 제어를 수행합니다.
                </p>
              </div>
              <div className="col-8 card">
                <div className="card-header">
                  <h3 className="card-title">사용자 권한 및 인증 설정</h3>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div className="form-group">
                    <label className="form-label">시스템 API 보안 키 (X-API-Key)</label>
                    <input
                      type="password"
                      className="form-control"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="백엔드 APP_API_KEY 보안 키를 입력하세요 (예: local-test-key)"
                    />
                  </div>

                  <div className="form-row">
                    <div className="form-group">
                      <label className="form-label">사용자 식별 ID</label>
                      <input
                        type="text"
                        className="form-control"
                        value={userId}
                        onChange={(e) => setUserId(e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">부여된 시스템 권한 (Role)</label>
                      <select className="form-control" value={userRole} onChange={(e) => setUserRole(e.target.value)}>
                        <option value="viewer">단순 조회자 (Viewer)</option>
                        <option value="analyst">분석 전문가 (Analyst)</option>
                        <option value="manager">검토 책임자 (Manager)</option>
                        <option value="admin">최고 관리자 (Admin)</option>
                      </select>
                    </div>
                  </div>

                  <button className="btn btn-primary" onClick={saveSettings}>
                    💾 인증 정보 및 권한 저장
                  </button>
                </div>
              </div>

              <div className="col-4 card">
                <div className="card-header">
                  <h3 className="card-title">기본 분석 대상 식별값</h3>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div className="form-group">
                    <label className="form-label">기본 회사 코드 ID</label>
                    <input
                      type="number"
                      className="form-control"
                      value={companyId}
                      onChange={(e) => setCompanyId(parseInt(e.target.value) || 1)}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">기본 프로젝트 ID</label>
                    <input
                      type="number"
                      className="form-control"
                      value={projectId}
                      onChange={(e) => setProjectId(parseInt(e.target.value) || 1)}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

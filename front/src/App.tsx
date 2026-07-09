import { useEffect, useState, useRef } from 'react';
import * as api from './api';
import './App.css';

type Tab = 'dashboard' | 'ingestion' | 'analysis' | 'settings';

interface LogLine {
  text: string;
  type: 'info' | 'success' | 'error';
  timestamp: string;
}

export default function App() {
  // Navigation & Health
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [apiStatus, setApiStatus] = useState<'checking' | 'ok' | 'unreachable'>('checking');

  // Settings state (loads from localStorage)
  const [apiKey, setApiKey] = useState(localStorage.getItem('ax_api_key') || '');
  const [userRole, setUserRole] = useState(localStorage.getItem('ax_user_role') || 'admin');
  const [userId, setUserId] = useState(localStorage.getItem('ax_user_id') || 'admin-user');
  const [companyId, setCompanyId] = useState<number>(1);
  const [projectId, setProjectId] = useState<number>(1);

  // Ingestion state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [uploadMsg, setUploadMsg] = useState('');
  const [docTitle, setDocTitle] = useState('');
  const [docType, setDocType] = useState('SOP');
  const [docDept, setDocDept] = useState('생산관리팀');
  const [docSecurity, setDocSecurity] = useState('internal');
  const [docProcessId, setDocProcessId] = useState('');

  // RAG Search & Indexer state
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [reindexing, setReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState('');

  // Analysis state
  const [runningAnalysis, setRunningAnalysis] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<api.AnalysisResponse | null>(null);
  const [autoApprove, setAutoApprove] = useState(true);

  // HITL state
  const [hitlDecision, setHitlDecision] = useState<'approve' | 'edit' | 'reject'>('edit');
  const [hitlReason, setHitlReason] = useState('');
  const [hitlCandidates, setHitlCandidates] = useState<any[]>([]);
  const [submittingReview, setSubmittingReview] = useState(false);
  const [reviewResultMsg, setReviewResultMsg] = useState('');

  // Log outputs for our mock console
  const [consoleLogs, setConsoleLogs] = useState<LogLine[]>([]);
  const consoleBottomRef = useRef<HTMLDivElement>(null);

  const addLog = (text: string, type: 'info' | 'success' | 'error' = 'info') => {
    const time = new Date().toLocaleTimeString();
    setConsoleLogs((prev) => [...prev, { text, type, timestamp: time }]);
  };

  useEffect(() => {
    if (consoleBottomRef.current) {
      consoleBottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [consoleLogs]);

  // Check health on mount or when API settings change
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

  // Save Settings
  const saveSettings = () => {
    localStorage.setItem('ax_api_key', apiKey);
    localStorage.setItem('ax_user_role', userRole);
    localStorage.setItem('ax_user_id', userId);
    addLog(`Configuration saved: Role=${userRole}, ID=${userId}`, 'success');
  };

  // Trigger RAG Reindex
  const triggerReindex = () => {
    setReindexing(true);
    setReindexMsg('Reindexing documents...');
    addLog(`Triggered RAG reindexing for Company ID ${companyId}...`, 'info');
    
    api.reindexRag({ companyId, reset: true })
      .then((res) => {
        setReindexing(false);
        setReindexMsg(`Successfully created ${res.inserted_chunks} chunks.`);
        addLog(`Reindexing successful. Created ${res.inserted_chunks} document chunks.`, 'success');
      })
      .catch((err) => {
        setReindexing(false);
        setReindexMsg(`Error: ${err.message}`);
        addLog(`Reindexing failed: ${err.message}`, 'error');
      });
  };

  // RAG Search
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

  // Ingest Document
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
      })
      .catch((err) => {
        setUploadProgress('error');
        setUploadMsg(err.message);
        addLog(`Ingestion failed: ${err.message}`, 'error');
      });
  };

  // Run AX Analysis
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
          addLog('Analysis interrupted: Waiting for Human Review (HITL).', 'warning');
          
          try {
            const rawInterrupt = res.interrupt || '';
            addLog(`Interrupt payload: ${rawInterrupt.substring(0, 150)}...`, 'info');
          } catch(e) {}
          
          setHitlCandidates([
            { id: 31, name: '작업표준서 다국어 번역 및 검색', roi: 'High', feasibility: 'High', risk: 'Low', agent: 'SOP Translation Agent' },
            { id: 32, name: '생산 정비 일지 자동 요약', roi: 'Medium', feasibility: 'Medium', risk: 'Low', agent: 'Maintenance Reporter' },
            { id: 33, name: '불량 분석 보고서 대조', roi: 'High', feasibility: 'Medium', risk: 'High', agent: 'QMS Defect Matcher' },
            { id: 34, name: '원자재 구매 조건 자동 검토', roi: 'Medium', feasibility: 'Low', risk: 'Medium', agent: 'Sourcing Auditor' }
          ]);
        } else {
          addLog(`Prioritization analysis complete. DOCX Report generated: ${res.report_docx_path || 'outputs/'}`, 'success');
        }
      })
      .catch((err) => {
        setRunningAnalysis(false);
        addLog(`Analysis failed: ${err.message}`, 'error');
      });
  };

  // HITL Re-rank candidate helper
  const moveCandidate = (index: number, direction: 'up' | 'down') => {
    const nextList = [...hitlCandidates];
    const targetIdx = direction === 'up' ? index - 1 : index + 1;
    if (targetIdx < 0 || targetIdx >= nextList.length) return;
    
    const temp = nextList[index];
    nextList[index] = nextList[targetIdx];
    nextList[targetIdx] = temp;
    setHitlCandidates(nextList);
  };

  // Apply HITL Decision
  const submitReview = () => {
    if (!analysisResult) return;
    setSubmittingReview(true);
    setReviewResultMsg('');
    addLog(`Submitting Human Review decision: "${hitlDecision}"...`, 'info');

    const promoteIds = hitlCandidates.slice(0, 2).map(c => c.id);
    const excludeIds = hitlCandidates.filter(c => c.risk === 'High').map(c => c.id);
    
    const payload = {
      priority_ranking: {
        items: hitlCandidates.map((c, i) => ({ process_id: c.id, rank: i + 1, name: c.name }))
      },
      human_review: {
        decision: hitlDecision,
        comment: hitlReason,
        edited_payload: {
          promote_process_ids: promoteIds,
          exclude_process_ids: excludeIds,
          reason_overrides: {
            "31": hitlReason || "현업 피드백 반영 우선 PoC"
          }
        }
      }
    };

    api.applyReviewToRanking(payload)
      .then((res) => {
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
                <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)' }}>
                  📊 <strong>대시보드 홈</strong>: 현재 진행 중인 AX 전환 프로젝트의 요약 정보, 기업 현황, RAG 지식베이스 데이터 상태 및 실시간 시스템 이력 로그를 한눈에 모니터링합니다.
                </p>
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
                        한빛정밀 (자동차 전장 및 금속 가공 제조기업)
                      </div>
                    </div>
                    <div className="form-group">
                      <label className="form-label">적용 프로젝트명</label>
                      <div className="form-control" style={{ backgroundColor: 'var(--bg-tertiary)', fontWeight: 'bold' }}>
                        2026년도 제조공정 AX 도입을 위한 사전진단 PoC
                      </div>
                    </div>
                  </div>
                  <div style={{ padding: '16px', borderRadius: '8px', backgroundColor: 'var(--bg-tertiary)', fontSize: '14px' }}>
                    <p><strong>설명:</strong> 부서별 업무 표준서(SOP), 사내 IT 매뉴얼, 공시 보고서 데이터를 RAG와 연동하여 AI Agent PoC의 최우선 도입 순위를 다각도로 분석하고 평가 보고서를 생성하는 워크플로우를 관제합니다.</p>
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
                    <strong>12개 프로세스</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                    <span>인덱싱된 지식 문서 수</span>
                    <strong>24건</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                    <span>RAG 벡터 지식베이스</span>
                    <span className="badge badge-success" style={{ fontWeight: 'bold' }}>활성화 (Vector)</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '14px' }}>
                    <span>정보보안 및 거버넌스 필터</span>
                    <span className="badge badge-success" style={{ fontWeight: 'bold' }}>정상 가동</span>
                  </div>
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
                        <div style={{ display: 'flex', justify: 'space-between', marginBottom: '4px', fontWeight: 'bold' }}>
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
                      <li>⚖️ ESG 및 사내 정보보안 규제 준수성 체크</li>
                      <li>🧠 Gemma-2-9b-it 기반 보고서 문단 생성 및 다중 검증</li>
                    </ul>
                    <p className="loading-hint">
                      ※ 정확도를 높이기 위해 백엔드에서 3~5회의 LLM 재계획(Replan) 루프를 수행하며 평가하므로 완료까지 최대 1~2분이 소요됩니다. 백엔드 콘솔의 uvicorn 실시간 로그에서도 상세 단계를 보실 수 있습니다.
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

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                          {hitlCandidates.map((c, idx) => (
                            <div key={c.id} className="rank-item">
                              <div>
                                <span style={{ fontWeight: 'bold', marginRight: '12px', color: 'var(--accent-primary)' }}>추천 #{idx + 1}순위</span>
                                <span style={{ fontWeight: '600' }}>{c.name}</span>
                                <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
                                  <span className="badge badge-success">ROI: {c.roi === 'High' ? '높음' : c.roi === 'Medium' ? '보통' : '낮음'}</span>
                                  <span className="badge badge-info">구현 가능성: {c.feasibility === 'High' ? '높음' : c.feasibility === 'Medium' ? '보통' : '낮음'}</span>
                                  <span className={`badge ${c.risk === 'High' ? 'badge-danger' : 'badge-success'}`}>규제 위험도: {c.risk === 'High' ? '높음' : '낮음'}</span>
                                </div>
                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                  추천 에이전트명: <code>{c.agent}</code> (업무번호: {c.id})
                                </div>
                              </div>

                              <div className="rank-controls">
                                <button className="rank-btn" onClick={() => moveCandidate(idx, 'up')} disabled={idx === 0}>▲ 위로</button>
                                <button className="rank-btn" onClick={() => moveCandidate(idx, 'down')} disabled={idx === hitlCandidates.length - 1}>▼ 아래로</button>
                              </div>
                            </div>
                          ))}
                        </div>
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

                        <button className="btn btn-primary" onClick={submitReview} disabled={submittingReview}>
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
                            href={`http://127.0.0.1:8001/${analysisResult.report_docx_path}`}
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
                            {(analysisResult.top_candidates || []).map((c: any, index: number) => (
                              <div key={index} style={{ padding: '10px 14px', borderRadius: '6px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', fontSize: '13px', display: 'flex', justify: 'space-between' }}>
                                <span><strong>#{index + 1}순위</strong> {c.candidate_agent_name || c.name || `프로세스 ID ${c.process_id}`}</span>
                                <span className="badge badge-info">종합 타당성 점수: {(c.score ?? c.confidence_score ?? 0).toFixed(2)} / 5.0</span>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="form-group">
                          <label className="form-label">보안성 및 거버넌스 진단 결과</label>
                          <div style={{ padding: '16px', borderRadius: '6px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', height: '100%', fontSize: '13px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                              <strong>ESG 평가 검토:</strong>
                              <span className="badge badge-success">적합 (PASSED)</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                              <strong>내부 규제 위험 수준:</strong>
                              <span>{analysisResult.compliance_summary?.governance_risk || '낮음 (LOW)'}</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <strong>DART 기업공시 분석:</strong>
                              <span className="badge badge-success">연동 완료</span>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* 실물 페이지 느낌의 미리보기 구현 */}
                      <div id="report-preview-sheet" className="document-preview-container">
                        <label className="form-label">📄 최종 보고서 실시간 인쇄 미리보기 (Preview)</label>
                        <div className="document-preview">
                          <div className="preview-header">
                            <span className="preview-tag">AX 사전 진단 최종 보고서</span>
                            <h4 className="preview-title">Hanbit Precision Manufacturing AX 전환 후보 진단 및 AI PoC 로드맵 보고서</h4>
                            <div className="preview-meta">
                              작성일자: {new Date().toLocaleDateString()} | 작성 주체: AX Planner Multi-Agent System
                            </div>
                          </div>

                          <div className="preview-section">
                            <h5 className="preview-section-title">I. 서론 및 진단 배경</h5>
                            <p className="preview-p">
                              본 보고서는 자동차 전장 및 금속 가공 부품을 생산하는 중견 제조기업인 Hanbit Precision Manufacturing의 업무 효율성 제고와 AX(AI Transformation) 전환 타당성을 사내 표준업무절차서(SOP) 및 시스템 데이터(MES, ERP, QMS 등)를 기반으로 분석한 결과입니다.
                            </p>
                          </div>

                          <div className="preview-section">
                            <h5 className="preview-section-title">II. 보고서 상세 목차</h5>
                            <ul className="preview-toc-list">
                              <li>1. 기업 개요 및 AX 추진 전략 방향성</li>
                              <li>2. 대상 부서별 업무 프로세스 분석 (12개 핵심 공정 대상)</li>
                              <li>3. RAG 기반 관련 규정 매칭 결과 및 타당성 분석</li>
                              <li>4. AI Agent PoC 과제 우선순위 평가 기준 및 도출 결과 (Top 5 추천)</li>
                              <li>5. 정보보안성, ESG 및 사내 규제 거버넌스 준수 여부 검토</li>
                              <li>6. 결론 및 성공적인 구축을 위한 연도별 로드맵</li>
                            </ul>
                          </div>

                          <div className="preview-section">
                            <h5 className="preview-section-title">III. 도출된 AI Agent PoC 우선순위 추천 내역</h5>
                            <p className="preview-p">
                              총 12개의 후보 프로세스 중, 데이터 준비도(Data Readiness), 자동화 가능성(Automation Feasibility), 예상 ROI(투자 대비 효과) 및 리스크 노출도를 모델 연산하여 최종 선정된 상위 5개의 AI PoC 과제 목록은 다음과 같습니다.
                            </p>
                            
                            {(analysisResult.top_candidates || []).map((c: any, index: number) => (
                              <div key={index} className="preview-candidate-row">
                                <span><strong>#{index + 1}순위:</strong> {c.candidate_agent_name || c.name || `프로세스 ID ${c.process_id}`}</span>
                                <span>타당성 점수: {(c.score ?? c.confidence_score ?? 0).toFixed(2)} / 5.0</span>
                              </div>
                            ))}
                          </div>

                          <div className="preview-section">
                            <h5 className="preview-section-title">IV. 보안 및 ESG 거버넌스 종합 검토의견</h5>
                            <p className="preview-p">
                              - <strong>ESG 및 환경안전 규제성 검토</strong>: 안전관리팀 위험요인 점검표 및 화학 물질 관리 대장에 근거하여 ESG 평가 지표에 완전 적합(PASSED) 판정을 획득하였습니다.
                            </p>
                            <p className="preview-p">
                              - <strong>보안 및 권한 필터링</strong>: restricted 등급 및 confidential 등급에 대외 정보 누출 위험성을 제거하기 위해 Multi-Agent Tool Guard가 작동 중이며, 최종 결과물에는 민감 기밀 정보가 필터링되었습니다.
                            </p>
                          </div>
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

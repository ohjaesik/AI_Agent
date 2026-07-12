"""FastAPI 내장 smoke-test HTML.

운영 프론트는 `front/`의 Vite 앱을 사용하지만, 백엔드만 띄운 상태에서도 인증,
문서 업로드, RAG 검색, 분석 실행을 빠르게 확인할 수 있도록 아주 작은 HTML UI를
제공한다. `app.api.main`에서 분리해 라우팅 코드가 길어지는 것을 막는다.
"""

TEST_UI_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>AX Delivery Planner Test UI</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 40px; max-width: 920px; }
    section { border: 1px solid #ddd; padding: 20px; margin-bottom: 20px; border-radius: 10px; }
    label { display:block; margin: 8px 0 4px; font-weight: 600; }
    input, button { padding: 8px; margin-bottom: 8px; }
    button { cursor: pointer; }
    pre { background:#111; color:#eee; padding:16px; overflow:auto; min-height:120px; }
  </style>
</head>
<body>
  <h1>AX Delivery Planner Test UI</h1>
  <section>
    <h2>0. Local API Key</h2>
    <label>APP_API_KEY(optional)</label>
    <input id="apiKey" type="password" placeholder="local-test-key" style="width: 300px" />
    <label>User Role</label>
    <input id="userRole" type="text" value="admin" style="width: 120px" />
    <button onclick="saveApiKey()">Save</button>
  </section>
  <section>
    <h2>1. 회사명 기반 DB 생성</h2>
    <label>Company Name</label>
    <input id="bootstrapCompanyName" type="text" value="삼성전자" style="width: 300px" />
    <label>Official URL</label>
    <input id="officialUrl" type="text" placeholder="https://..." style="width: 640px" />
    <button onclick="bootstrapCompany()">Bootstrap Company</button>
  </section>
  <section>
    <h2>2. 문서 업로드 + RAG 색인</h2>
    <label>Company ID</label>
    <input id="companyId" type="number" value="1" />
    <label>Process ID(optional)</label>
    <input id="processId" type="number" placeholder="optional" />
    <label>File</label>
    <input id="file" type="file" />
    <button onclick="ingest()">Upload & Index</button>
  </section>
  <section>
    <h2>3. RAG 검색 확인</h2>
    <label>Query</label>
    <input id="ragQuery" type="text" value="SOP 검색 작업표준서" style="width: 420px" />
    <button onclick="ragSearch()">Search RAG</button>
  </section>
  <section>
    <h2>4. 분석 실행</h2>
    <label>Project ID(optional)</label>
    <input id="projectId" type="number" placeholder="optional" />
    <label>Company ID(optional)</label>
    <input id="analysisCompanyId" type="number" placeholder="optional" />
    <button onclick="runAnalysis()">Run Analysis</button>
  </section>
  <pre id="output">ready</pre>
<script>
function saveApiKey() {
  localStorage.setItem('AX_APP_API_KEY', document.getElementById('apiKey').value || '');
  localStorage.setItem('AX_USER_ROLE', document.getElementById('userRole').value || 'analyst');
  document.getElementById('output').textContent = 'saved';
}
async function show(promise) {
  const out = document.getElementById('output');
  out.textContent = 'loading...';
  try { const res = await promise; const data = await res.json(); out.textContent = JSON.stringify(data, null, 2); }
  catch (e) { out.textContent = String(e); }
}
function authHeaders(json=true) {
  const key = localStorage.getItem('AX_APP_API_KEY') || '';
  const role = localStorage.getItem('AX_USER_ROLE') || 'analyst';
  const headers = json ? {'Content-Type':'application/json'} : {};
  if (key) headers['X-API-Key'] = key;
  if (role) headers['X-User-Role'] = role;
  return headers;
}
function bootstrapCompany() {
  const companyName = document.getElementById('bootstrapCompanyName').value;
  const officialUrl = document.getElementById('officialUrl').value;
  show(fetch('/companies/bootstrap', {method: 'POST', headers: authHeaders(), body: JSON.stringify({company_name: companyName, official_urls: officialUrl ? [officialUrl] : [], create_project: true, index: true, thread_id: 'bootstrap-supervisor-ui'})}));
}
function ingest() {
  const fd = new FormData();
  fd.append('company_id', document.getElementById('companyId').value);
  const processId = document.getElementById('processId').value;
  if (processId) fd.append('process_id', processId);
  fd.append('file', document.getElementById('file').files[0]);
  show(fetch('/documents/ingest', {method:'POST', headers: authHeaders(false), body: fd}));
}
function ragSearch() {
  const q = encodeURIComponent(document.getElementById('ragQuery').value);
  const companyId = document.getElementById('companyId').value;
  show(fetch(`/rag/search?query=${q}&company_id=${companyId}`, {headers: authHeaders(false)}));
}
function runAnalysis() {
  const projectId = document.getElementById('projectId').value;
  const companyId = document.getElementById('analysisCompanyId').value;
  const params = new URLSearchParams({auto_approve: 'true'});
  if (projectId) params.append('project_id', projectId);
  if (companyId) params.append('company_id', companyId);
  show(fetch(`/analysis/run?${params.toString()}`, {method:'POST', headers: authHeaders(false)}));
}
</script>
</body>
</html>
"""

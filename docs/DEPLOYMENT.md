# Deployment Guide

본 문서는 AX Delivery Planner를 로컬 PoC가 아니라 최소 운영형 MVP로 실행하기 위한 배포 기준을 정리한다.

## 1. 필수 환경변수

`.env` 예시:

```env
POSTGRES_USER=axplanner
POSTGRES_PASSWORD=change-me
POSTGRES_DB=axplanner
DATABASE_URL=postgresql+psycopg://axplanner:change-me@postgres:5432/axplanner

OPENAI_API_KEY=<SET_OPENAI_API_KEY>
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

VLLM_BASE_URL=http://host.docker.internal:8000/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=google/gemma-2-9b-it

DART_API_KEY=<SET_DART_API_KEY>
APP_API_KEY=<SET_LOCAL_API_KEY>
APP_JWT_SECRET=<SET_32_BYTE_OR_LONGER_SECRET>
APP_JWT_ALGORITHM=HS256
APP_JWT_EXP_MINUTES=480

STORAGE_BACKEND=local
LOCAL_STORAGE_DIR=storage
# STORAGE_BACKEND=s3 또는 minio 사용 시
S3_ENDPOINT_URL=http://minio:9000
S3_BUCKET=ax-documents
S3_ACCESS_KEY_ID=<SET_ACCESS_KEY>
S3_SECRET_ACCESS_KEY=<SET_SECRET_KEY>
S3_REGION_NAME=ap-northeast-2

APP_ENV=production
```

## 2. 실행

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## 3. DB 초기화 및 migration

컨테이너 기동 후 1회 실행한다.

```bash
docker compose -f docker-compose.prod.yml exec api python -m app.db.init_pgvector
docker compose -f docker-compose.prod.yml exec api python -m app.db.create_tables
docker compose -f docker-compose.prod.yml exec api python -m app.db.migrate_operational_hardening
```

## 4. 인증

### 4.1 API Key 기반

```bash
-H "X-API-Key: $APP_API_KEY"
-H "X-User-Role: admin"
```

### 4.2 로컬 사용자 등록 및 로그인

최초 admin 사용자는 API Key + admin role로 생성한다.

```bash
curl -X POST http://localhost:8001/auth/register \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: admin" \
  -d '{"username":"admin","password":"change-this-password","role":"admin"}'
```

로그인:

```bash
curl -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"change-this-password"}'
```

응답의 `access_token`을 이후 API에 사용한다.

```bash
-H "Authorization: Bearer <access_token>"
```

## 5. API 호출

```bash
curl -X POST http://localhost:8001/companies/bootstrap \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{
    "company_name": "삼성전자",
    "stock_code": "005930",
    "official_urls": [
      "https://www.samsung.com/sec/about-us/company-info/",
      "https://www.samsung.com/sec/about-us/business-area/",
      "https://www.samsung.com/sec/sustainability/overview/"
    ],
    "create_project": true,
    "index": true
  }'
```

## 6. Role 기준

| Role | 접근 가능한 문서 보안등급 |
|---|---|
| viewer | public, public_official |
| analyst | public, public_official, internal |
| manager | public, public_official, internal, confidential |
| admin | all |

`/rag/reindex`는 admin만 허용한다. `/reviews/apply-ranking`은 manager/admin만 허용한다.

## 7. 문서 저장소

문서 업로드 시 원본 파일은 `STORAGE_BACKEND`에 따라 local 또는 S3/MinIO에 저장된다. DB에는 다음 metadata가 저장된다.

- file_storage_uri
- original_filename
- file_size_bytes
- file_checksum_sha256
- uploaded_by_user_id

local 기본 경로는 `LOCAL_STORAGE_DIR=storage`이다. 운영 배포에서는 S3/MinIO를 권장한다.

## 8. 모니터링

Health check:

```bash
curl http://localhost:8001/health
```

Prometheus text format metrics:

```bash
curl http://localhost:8001/metrics
```

API 요청 로그는 JSON line 형태로 stdout에 출력된다.

## 9. 운영 전 점검

```bash
pytest
```

## 10. 아직 남은 운영 과제

- OAuth/SSO 연동
- 조직/프로젝트별 세분화 권한 테이블
- 운영용 React/Vue wizard UI
- HTTPS reverse proxy
- Prometheus/Grafana 대시보드와 alert rule
- 법무 검토 기반 한국 AI 기본법 조항별 compliance mapping 최종화

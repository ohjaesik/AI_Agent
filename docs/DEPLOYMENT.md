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

## 4. API 호출

`APP_API_KEY`가 설정된 경우 보호 API는 `X-API-Key`가 필요하다. 역할은 `X-User-Role`로 넘긴다.

```bash
curl -X POST http://localhost:8001/companies/bootstrap \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $APP_API_KEY" \
  -H "X-User-Role: admin" \
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

## 5. Role 기준

| Role | 접근 가능한 문서 보안등급 |
|---|---|
| viewer | public, public_official |
| analyst | public, public_official, internal |
| manager | public, public_official, internal, confidential |
| admin | all |

`/rag/reindex`는 admin만 허용한다. `/reviews/apply-ranking`은 manager/admin만 허용한다.

## 6. 운영 전 점검

```bash
pytest
```

```bash
curl http://localhost:8001/health
```

## 7. 아직 남은 운영 과제

- JWT/OAuth 기반 사용자 인증
- 사용자/조직/프로젝트별 권한 테이블
- 운영용 wizard UI
- S3/MinIO 기반 문서 파일 저장
- HTTPS reverse proxy
- Prometheus/Grafana 등 모니터링
- 법무 검토 기반 조항별 compliance mapping

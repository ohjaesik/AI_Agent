# app/db/migrate_operational_hardening.py

"""운영 안정성 강화를 위한 DB migration script.

문서 보안 등급, allowed roles, audit/security metadata처럼 운영 통제에 필요한 구조를
추가한다.
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.database import engine


DDL = """
CREATE TABLE IF NOT EXISTS app_users (
  id SERIAL PRIMARY KEY,
  username VARCHAR(100) NOT NULL,
  password_hash TEXT NOT NULL,
  role VARCHAR(50) NOT NULL DEFAULT 'analyst',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_app_users_username
ON app_users (username);

ALTER TABLE IF EXISTS business_processes
ADD COLUMN IF NOT EXISTS discovery_metadata JSONB;

ALTER TABLE IF EXISTS process_documents
ADD COLUMN IF NOT EXISTS source_url TEXT;

ALTER TABLE IF EXISTS process_documents
ADD COLUMN IF NOT EXISTS allowed_roles JSONB;

ALTER TABLE IF EXISTS process_documents
ADD COLUMN IF NOT EXISTS file_storage_uri TEXT;

ALTER TABLE IF EXISTS process_documents
ADD COLUMN IF NOT EXISTS original_filename VARCHAR(255);

ALTER TABLE IF EXISTS process_documents
ADD COLUMN IF NOT EXISTS file_size_bytes INTEGER;

ALTER TABLE IF EXISTS process_documents
ADD COLUMN IF NOT EXISTS file_checksum_sha256 VARCHAR(64);

ALTER TABLE IF EXISTS process_documents
ADD COLUMN IF NOT EXISTS uploaded_by_user_id VARCHAR(100);

-- Backfill source_url for official URL documents created before the column existed.
UPDATE process_documents
SET source_url = substring(content from '공식 URL: ([^\n]+)')
WHERE source_url IS NULL
  AND document_type = 'official_url'
  AND content LIKE '공식 URL:%';

-- Existing environments may already contain duplicate company names from pre-idempotency bootstrap runs.
-- Do not delete companies because dependent rows may exist. Rename older duplicates except the first row.
WITH ranked_companies AS (
  SELECT id, name, ROW_NUMBER() OVER (PARTITION BY name ORDER BY id) AS rn
  FROM companies
)
UPDATE companies c
SET name = c.name || ' #' || c.id
FROM ranked_companies r
WHERE c.id = r.id
  AND r.rn > 1;

-- Remove exact duplicate rows before creating unique indexes.
DELETE FROM departments a
USING departments b
WHERE a.id > b.id
  AND a.company_id = b.company_id
  AND a.name = b.name;

DELETE FROM systems a
USING systems b
WHERE a.id > b.id
  AND a.company_id = b.company_id
  AND a.name = b.name;

DELETE FROM business_processes a
USING business_processes b
WHERE a.id > b.id
  AND a.company_id = b.company_id
  AND a.name = b.name
  AND COALESCE(a.candidate_agent_name, '') = COALESCE(b.candidate_agent_name, '');

DELETE FROM analysis_projects a
USING analysis_projects b
WHERE a.id > b.id
  AND a.company_id = b.company_id
  AND a.title = b.title;

DELETE FROM document_chunks a
USING document_chunks b
WHERE a.id > b.id
  AND a.document_id = b.document_id
  AND a.chunk_index = b.chunk_index;

DELETE FROM process_documents a
USING process_documents b
WHERE a.id > b.id
  AND a.company_id = b.company_id
  AND a.document_type = b.document_type
  AND COALESCE(a.source_url, '') <> ''
  AND a.source_url = b.source_url;

CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_name
ON companies (name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_departments_company_name
ON departments (company_id, name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_systems_company_name
ON systems (company_id, name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_processes_company_name_agent
ON business_processes (company_id, name, COALESCE(candidate_agent_name, ''));

CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_projects_company_title
ON analysis_projects (company_id, title);

CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_company_type_source_url
ON process_documents (company_id, document_type, source_url)
WHERE source_url IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_document_index
ON document_chunks (document_id, chunk_index);
"""


def migrate_operational_hardening() -> None:
    """운영 안정성에 필요한 컬럼, index, constraint DDL을 idempotent하게 적용한다."""
    with engine.begin() as conn:
        conn.execute(text(DDL))


def main() -> None:
    """해당 모듈을 script로 실행했을 때 호출되는 진입점이다."""
    migrate_operational_hardening()
    print("Operational hardening migration completed.")


if __name__ == "__main__":
    main()

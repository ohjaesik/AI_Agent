# app/storage/file_store.py

"""원본 문서 파일 저장소 abstraction.

local filesystem 또는 S3/MinIO backend에 업로드 파일을 저장하고, DB에는 저장 위치를
metadata로 남길 수 있게 한다.
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings


@dataclass(frozen=True)
class StoredFile:
    """StoredFile 클래스. 원본 문서 파일 저장소 abstraction.에서 사용하는 구조화된 데이터/동작 단위다."""
    storage_uri: str
    original_filename: str
    size_bytes: int
    checksum_sha256: str
    content_type: str | None = None


def sha256_file(path: Path) -> str:
    """sha256_file 함수. 원본 문서 파일 저장소 abstraction. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_filename(filename: str | None, fallback: str = "document") -> str:
    """safe_filename 함수. 원본 문서 파일 저장소 abstraction. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    raw = (filename or fallback).strip() or fallback
    keep = []
    for char in raw:
        if char.isalnum() or char in {".", "-", "_", " ", "(", ")"}:
            keep.append(char)
        else:
            keep.append("_")
    return "".join(keep)[:180]


def build_object_key(company_id: int, original_filename: str) -> str:
    """build_object_key 함수. 입력 state나 domain 객체를 조합해 downstream에서 사용할 구조화된 payload를 만든다."""
    return f"documents/company_{company_id}/{uuid4().hex}_{safe_filename(original_filename)}"


def save_local_file(source_path: Path, company_id: int, original_filename: str) -> StoredFile:
    """save_local_file 함수. 분석 결과나 사용자 결정을 DB 또는 파일에 저장한다."""
    settings = get_settings()
    object_key = build_object_key(company_id=company_id, original_filename=original_filename)
    destination = Path(settings.local_storage_dir) / object_key
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)

    return StoredFile(
        storage_uri=f"local://{destination.as_posix()}",
        original_filename=original_filename,
        size_bytes=destination.stat().st_size,
        checksum_sha256=sha256_file(destination),
        content_type=mimetypes.guess_type(original_filename)[0],
    )


def save_s3_file(source_path: Path, company_id: int, original_filename: str) -> StoredFile:
    """save_s3_file 함수. 분석 결과나 사용자 결정을 DB 또는 파일에 저장한다."""
    import boto3

    settings = get_settings()
    if not settings.s3_bucket:
        raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3.")

    object_key = build_object_key(company_id=company_id, original_filename=original_filename)
    content_type = mimetypes.guess_type(original_filename)[0]
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region_name,
    )

    extra_args = {"ContentType": content_type} if content_type else None
    if extra_args:
        client.upload_file(str(source_path), settings.s3_bucket, object_key, ExtraArgs=extra_args)
    else:
        client.upload_file(str(source_path), settings.s3_bucket, object_key)

    return StoredFile(
        storage_uri=f"s3://{settings.s3_bucket}/{object_key}",
        original_filename=original_filename,
        size_bytes=source_path.stat().st_size,
        checksum_sha256=sha256_file(source_path),
        content_type=content_type,
    )


def save_original_file(source_path: str | Path, company_id: int, original_filename: str | None = None) -> StoredFile:
    """save_original_file 함수. 분석 결과나 사용자 결정을 DB 또는 파일에 저장한다."""
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(path)

    filename = safe_filename(original_filename or path.name)
    backend = get_settings().storage_backend.lower()

    if backend == "local":
        return save_local_file(source_path=path, company_id=company_id, original_filename=filename)
    if backend in {"s3", "minio"}:
        return save_s3_file(source_path=path, company_id=company_id, original_filename=filename)

    raise ValueError(f"Unsupported STORAGE_BACKEND: {backend}")

# AX Delivery Planner API 실행용 production image 정의.
# FastAPI 서버와 LangGraph workflow 실행에 필요한 Python dependency만 설치한다.
FROM python:3.12-slim

# Python bytecode/cache 생성을 줄이고, container log가 바로 출력되도록 설정한다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# build-essential은 일부 Python wheel build에 필요하고, curl은 container health/debug에 쓴다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# dependency layer를 먼저 만들어 코드 변경 시 Docker build cache를 최대한 재사용한다.
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# 런타임에 필요한 앱 코드, 운영 문서, 기본 설정 예시만 image에 포함한다.
COPY app ./app
COPY docs ./docs
COPY README.md ./.env.example ./

# 보고서/DOCX 등 실행 산출물이 저장될 mount point를 미리 만든다.
RUN mkdir -p outputs

# FastAPI 기본 노출 port. docker-compose.prod.yml도 같은 port를 사용한다.
EXPOSE 8001

# API 서버 진입점. LangGraph workflow는 FastAPI endpoint 내부에서 호출된다.
CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8001"]

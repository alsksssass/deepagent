# Multi-stage build for Deep Agents AWS Batch (Debian Slim-based)
# Stage 1: Builder
FROM python:3.11-slim AS builder

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치 (빌드 도구)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 복사
COPY requirements.txt .

# PATH에 Python 패키지 경로 추가 (경고 방지)
ENV PATH=/root/.local/bin:$PATH

# requirements.txt에서 로컬 경로, editable 패키지, 주석 제거 및 필수 패키지만 설치
# requirements.txt에서 로컬 경로, editable 패키지, 주석 제거 및 필수 패키지만 설치
# uv를 사용하여 설치 속도 개선
RUN pip install uv && \
    grep -v "^-e " requirements.txt | \
    grep -v "^#" | \
    grep -v "@ file:///" | \
    grep -v "^$" > requirements-docker.txt && \
    echo "📦 Filtered requirements:" && \
    head -20 requirements-docker.txt && \
    uv pip install --system --no-cache-dir -r requirements-docker.txt && \
    echo "✅ Dependencies installed"

# Stage 2: Runtime
FROM python:3.11-slim

# 메타데이터
LABEL maintainer="Deep Agents Team"
LABEL description="Deep Agents Code Analysis for AWS Batch (ARM64 Optimized)"
LABEL version="1.1.0"

# 작업 디렉토리 설정
WORKDIR /app

# 런타임 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    libpq5 \
    libgomp1 \
    cloc \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지를 builder 스테이지에서 복사 (uv --system 설치 경로)
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# PATH 설정 (기본값 유지)
ENV PATH=/usr/local/bin:$PATH

# 애플리케이션 코드 복사
COPY . .

# 환경 변수 설정 (기본값)
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV DATA_DIR=/app/data
ENV LOG_LEVEL=INFO

# AWS Batch 환경 변수 (런타임에 오버라이드됨)
# USER_ID, GIT_URLS, TARGET_USER는 AWS Batch Job Definition에서 설정

# 데이터 디렉토리 생성 및 권한 설정
# 보안을 위해 non-root 유저 생성 및 사용 (홈 디렉토리 생성 포함)
RUN groupadd -r appuser && \
    useradd -r -g appuser -m -d /home/appuser -s /bin/bash appuser && \
    mkdir -p /app/data /app/logs && \
    chown -R appuser:appuser /app /home/appuser

# 도구 설치 확인 (디버깅용)
RUN echo "🔍 Verifying installed tools..." && \
    cloc --version && \
    radon --version && \
    echo "✅ All tools installed successfully"

# User 전환
USER appuser

# 헬스체크 (옵션)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# 실행 스크립트
ENTRYPOINT ["python", "main.py", "--batch-mode"]

# 기본 CMD (오버라이드 가능)
CMD []

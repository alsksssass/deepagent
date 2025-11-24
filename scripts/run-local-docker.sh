#!/bin/bash

# 로컬 Docker 실행 스크립트
# submit-batch-job.sh와 유사한 인터페이스로 로컬에서 Docker 컨테이너 실행
# 사용법: ./scripts/run-local-docker.sh USER_ID GIT_URLS [TARGET_USER]

set -e

# 인자 확인
USER_ID=$1
GIT_URLS=$2
TARGET_USER=${3:-""}

if [ -z "$USER_ID" ] || [ -z "$GIT_URLS" ]; then
    echo "사용법: $0 USER_ID GIT_URLS [TARGET_USER]"
    echo ""
    echo "예시:"
    echo "  단일 레포: $0 123e4567-e89b-12d3-a456-426614174000 'git@github.com:user/repo.git'"
    echo "  다중 레포: $0 123e4567-e89b-12d3-a456-426614174000 'git@github.com:user/repo1.git,git@github.com:user/repo2.git'"
    echo "  특정 유저: $0 123e4567-e89b-12d3-a456-426614174000 'git@github.com:user/repo.git' user@example.com"
    exit 1
fi

echo "============================================================"
echo "🐳 Deep Agents 로컬 Docker 실행"
echo "============================================================"
echo ""

# 스크립트 디렉토리
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# .env 파일 확인
if [ ! -f .env ]; then
    echo "❌ .env 파일이 없습니다"
    echo ""
    echo "💡 .env 파일을 생성하세요. .env.complete를 참고하세요:"
    echo "   cp .env.complete .env"
    echo "   # 필요한 값 수정"
    exit 1
fi

# .env 파일 로드
echo "📋 .env 파일에서 환경 변수 로드 중..."
set -a
source .env
set +a
echo "✅ 환경 변수 로드 완료"
echo ""

# 필수 환경 변수 검증
echo "🔍 필수 환경 변수 확인..."
MISSING_VARS=()

if [ -z "$AWS_ACCESS_KEY_ID" ]; then
    MISSING_VARS+=("AWS_ACCESS_KEY_ID")
fi
if [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    MISSING_VARS+=("AWS_SECRET_ACCESS_KEY")
fi
if [ -z "$AWS_BEDROCK_MODEL_ID_SONNET" ]; then
    MISSING_VARS+=("AWS_BEDROCK_MODEL_ID_SONNET")
fi
if [ -z "$AWS_BEDROCK_MODEL_ID_HAIKU" ]; then
    MISSING_VARS+=("AWS_BEDROCK_MODEL_ID_HAIKU")
fi
if [ -z "$POSTGRES_HOST" ]; then
    MISSING_VARS+=("POSTGRES_HOST")
fi
if [ -z "$POSTGRES_PASSWORD" ]; then
    MISSING_VARS+=("POSTGRES_PASSWORD")
fi

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "❌ 필수 환경 변수가 누락되었습니다:"
    for var in "${MISSING_VARS[@]}"; do
        echo "   - $var"
    done
    echo ""
    exit 1
fi

# 기본값 설정
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-northeast-2}"
export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION}}"
export AWS_BEDROCK_REGION="${AWS_BEDROCK_REGION:-us-east-1}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_DB="${POSTGRES_DB:-sesami}"
export POSTGRES_USER="${POSTGRES_USER:-sesami}"
export STORAGE_BACKEND="${STORAGE_BACKEND:-s3}"
export S3_BUCKET_NAME="${S3_BUCKET_NAME:-}"
export S3_REGION="${S3_REGION:-${AWS_REGION}}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
export DATA_DIR="${DATA_DIR:-./data}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export ENABLE_DEBUG_LOGGING="${ENABLE_DEBUG_LOGGING:-true}"
export ENABLE_SUBAGENT_DEBUG_LOGGING="${ENABLE_SUBAGENT_DEBUG_LOGGING:-false}"

# STORAGE_BACKEND에 따라 동적으로 IP 설정
# s3이면 배치 모드(프라이빗 IP), local이면 로컬 모드(공개 IP)
EC2_PUBLIC_IP="${EC2_PUBLIC_IP:-13.125.186.57}"
EC2_PRIVATE_IP="${EC2_PRIVATE_IP:-172.31.41.218}"

if [ -z "$NEO4J_URI" ]; then
    if [ "$STORAGE_BACKEND" = "s3" ]; then
        # 배치 모드: 프라이빗 IP 사용
        export NEO4J_URI="bolt://${EC2_PRIVATE_IP}:7687"
    else
        # 로컬 모드: 공개 IP 사용
        export NEO4J_URI="bolt://${EC2_PUBLIC_IP}:7687"
    fi
fi

if [ -z "$CHROMADB_HOST" ]; then
    if [ "$STORAGE_BACKEND" = "s3" ]; then
        # 배치 모드: 프라이빗 IP 사용
        export CHROMADB_HOST="${EC2_PRIVATE_IP}"
    else
        # 로컬 모드: 공개 IP 사용
        export CHROMADB_HOST="${EC2_PUBLIC_IP}"
    fi
fi

# 기본값 설정 (명시적으로 설정되지 않은 경우)
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"
export CHROMADB_PORT="${CHROMADB_PORT:-8000}"
export CHROMADB_PERSIST_DIR="${CHROMADB_PERSIST_DIR:-./data/chroma_db}"
export CHROMADB_AUTH_TOKEN="${CHROMADB_AUTH_TOKEN:-}"
export GRAPH_DB_BACKEND="${GRAPH_DB_BACKEND:-neo4j}"
export VECTOR_DB_BACKEND="${VECTOR_DB_BACKEND:-chromadb}"

# 실행 파라미터 설정
export USER_ID
export GIT_URLS
export TARGET_USER

echo "📋 실행 설정:"
echo "   User ID: $USER_ID"
echo "   Git URLs: $GIT_URLS"
echo "   Target User: ${TARGET_USER:-전체 유저}"
echo "   Storage Backend: $STORAGE_BACKEND"
if [ "$STORAGE_BACKEND" = "s3" ]; then
    echo "   모드: 배치 모드 (프라이빗 IP 사용)"
    echo "   S3 Bucket: $S3_BUCKET_NAME"
    echo "   S3 Region: $S3_REGION"
else
    echo "   모드: 로컬 모드 (공개 IP 사용)"
fi
echo "   Neo4j URI: $NEO4J_URI"
echo "   ChromaDB Host: $CHROMADB_HOST:$CHROMADB_PORT"
echo "   PostgreSQL Host: $POSTGRES_HOST"
echo ""

# Docker 이미지 확인
IMAGE_NAME="deep-agents"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_NAME="deep-agents-local-$(date +%s)"

echo "🔍 Docker 이미지 확인..."
if ! docker images $IMAGE_NAME:$IMAGE_TAG | grep -q $IMAGE_NAME; then
    echo "⚠️  Docker 이미지를 찾을 수 없습니다: $IMAGE_NAME:$IMAGE_TAG"
    echo "   이미지를 빌드하시겠습니까?"
    read -p "빌드하시겠습니까? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "📦 Docker 이미지 빌드 중..."
        docker build \
            --platform linux/amd64 \
            --tag $IMAGE_NAME:$IMAGE_TAG \
            --file Dockerfile \
            .
        
        if [ $? -ne 0 ]; then
            echo "❌ Docker 이미지 빌드 실패"
            exit 1
        fi
        echo "✅ Docker 이미지 빌드 완료"
    else
        echo "❌ Docker 이미지가 필요합니다"
        exit 1
    fi
fi

echo "✅ Docker 이미지 확인 완료"
echo ""

# 기존 컨테이너 정리
echo "🧹 기존 테스트 컨테이너 정리..."
docker rm -f $CONTAINER_NAME 2>/dev/null || true
echo ""

# 데이터 디렉토리 생성
mkdir -p ./data ./logs

# Docker 컨테이너 실행
echo "🚀 Docker 컨테이너 실행..."
echo "   Container: $CONTAINER_NAME"
echo "   Image: $IMAGE_NAME:$IMAGE_TAG"
echo ""

# 환경 변수 배열 구성
ENV_ARGS=(
    -e USER_ID="$USER_ID"
    -e GIT_URLS="$GIT_URLS"
    -e TARGET_USER="$TARGET_USER"
    -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID"
    -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY"
    -e AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION"
    -e AWS_REGION="$AWS_REGION"
    -e AWS_BEDROCK_REGION="$AWS_BEDROCK_REGION"
    -e AWS_BEDROCK_MODEL_ID_SONNET="$AWS_BEDROCK_MODEL_ID_SONNET"
    -e AWS_BEDROCK_MODEL_ID_HAIKU="$AWS_BEDROCK_MODEL_ID_HAIKU"
    -e POSTGRES_HOST="$POSTGRES_HOST"
    -e POSTGRES_PORT="$POSTGRES_PORT"
    -e POSTGRES_DB="$POSTGRES_DB"
    -e POSTGRES_USER="$POSTGRES_USER"
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
    -e POSTGRES_ECHO="${POSTGRES_ECHO:-false}"
    -e NEO4J_URI="$NEO4J_URI"
    -e NEO4J_USER="$NEO4J_USER"
    -e NEO4J_PASSWORD="$NEO4J_PASSWORD"
    -e CHROMADB_HOST="$CHROMADB_HOST"
    -e CHROMADB_PORT="$CHROMADB_PORT"
    -e CHROMADB_PERSIST_DIR="${CHROMADB_PERSIST_DIR}"
    -e CHROMADB_AUTH_TOKEN="$CHROMADB_AUTH_TOKEN"
    -e STORAGE_BACKEND="$STORAGE_BACKEND"
    -e S3_BUCKET_NAME="$S3_BUCKET_NAME"
    -e S3_REGION="$S3_REGION"
    -e S3_LIFECYCLE_DAYS="${S3_LIFECYCLE_DAYS:-30}"
    -e GRAPH_DB_BACKEND="$GRAPH_DB_BACKEND"
    -e VECTOR_DB_BACKEND="$VECTOR_DB_BACKEND"
    -e DATA_DIR=/app/data
    -e LOG_LEVEL="$LOG_LEVEL"
    -e ENABLE_DEBUG_LOGGING="$ENABLE_DEBUG_LOGGING"
    -e ENABLE_SUBAGENT_DEBUG_LOGGING="$ENABLE_SUBAGENT_DEBUG_LOGGING"
    -e PYTHONUNBUFFERED=1
    -e TOKENIZERS_PARALLELISM="$TOKENIZERS_PARALLELISM"
)

# 네트워크 모드 설정
# 로컬 Neo4j/ChromaDB 접근을 위해 host 네트워크 사용 (옵션)
NETWORK_MODE="${NETWORK_MODE:-bridge}"

if [ "$NETWORK_MODE" = "host" ]; then
    echo "ℹ️  Host 네트워크 모드 사용 (로컬 서비스 접근)"
    NETWORK_ARG="--network host"
else
    NETWORK_ARG=""
fi

# Docker 컨테이너 실행
docker run \
    --name $CONTAINER_NAME \
    --rm \
    $NETWORK_ARG \
    "${ENV_ARGS[@]}" \
    -v "$(pwd)/data:/app/data" \
    -v "$(pwd)/logs:/app/logs" \
    $IMAGE_NAME:$IMAGE_TAG \
    --batch-mode

EXIT_CODE=$?

echo ""
echo "============================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 로컬 Docker 실행 성공"
else
    echo "❌ 로컬 Docker 실행 실패 (Exit Code: $EXIT_CODE)"
fi
echo "============================================================"
echo ""

# 로그 확인 안내
echo "💡 로그 확인:"
echo "   파일 로그: cat ./logs/deep_agents.log"
echo "   실시간 로그: tail -f ./logs/deep_agents.log"
echo ""

# 데이터 확인 안내
if [ "$STORAGE_BACKEND" = "s3" ]; then
    echo "💡 데이터 확인 (S3):"
    echo "   S3 버킷: s3://$S3_BUCKET_NAME/analyze/"
    echo "   AWS CLI: aws s3 ls s3://$S3_BUCKET_NAME/analyze/ --recursive"
else
    echo "💡 데이터 확인 (로컬):"
    echo "   분석 결과: ls -la ./data/analyze/"
fi
echo ""

# 실패한 경우 상세 정보 출력
if [ $EXIT_CODE -ne 0 ]; then
    echo "🔍 디버깅 정보:"
    echo "   1. 로그 파일 확인: cat ./logs/deep_agents.log"
    echo "   2. 환경 변수 확인: cat .env"
    echo "   3. Docker 이미지 확인: docker images $IMAGE_NAME:$IMAGE_TAG"
    echo "   4. 컨테이너 재실행 (디버그 모드):"
    echo "      docker run -it --rm \\"
    echo "        --name ${CONTAINER_NAME}-debug \\"
    echo "        \"\${ENV_ARGS[@]}\" \\"
    echo "        -v \"\$(pwd)/data:/app/data\" \\"
    echo "        -v \"\$(pwd)/logs:/app/logs\" \\"
    echo "        $IMAGE_NAME:$IMAGE_TAG \\"
    echo "        /bin/bash"
    echo ""
fi

exit $EXIT_CODE


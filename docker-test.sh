#!/bin/bash

# Docker Test Script for Deep Agents
# Docker 이미지 로컬 테스트

set -e  # 에러 발생 시 중단

echo "============================================================"
echo "🧪 Deep Agents Docker Test"
echo "============================================================"
echo ""

# 변수 설정
IMAGE_NAME="deep-agents"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_NAME="deep-agents-test"

# 환경 변수 로드 (.env 파일이 있으면)
if [ -f .env ]; then
    echo "📋 .env 파일에서 환경 변수 로드 중..."
    export $(cat .env | grep -v '^#' | xargs)
    echo "✅ 환경 변수 로드 완료"
    echo ""
fi

# 필수 환경 변수 확인
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

echo "   USER_ID: ${USER_ID:-(설정 안 됨)}"
echo "   GIT_URLS: ${GIT_URLS:-(설정 안 됨)}"
echo "   POSTGRES_HOST: ${POSTGRES_HOST:-(설정 안 됨)}"
echo ""

# USER_ID가 없으면 생성
if [ -z "$USER_ID" ]; then
    if command -v uuidgen &> /dev/null; then
        export USER_ID=$(uuidgen)
    else
        export USER_ID="00000000-0000-0000-0000-000000000001"
    fi
    echo "⚠️  USER_ID가 설정되지 않아 테스트용 UUID를 생성했습니다: $USER_ID"
    echo ""
fi

# GIT_URLS가 없으면 테스트용 URL 설정
if [ -z "$GIT_URLS" ]; then
    export GIT_URLS="https://github.com/test/docker-test-repo"
    echo "⚠️  GIT_URLS가 설정되지 않아 테스트용 URL을 사용합니다: $GIT_URLS"
    echo ""
fi

# 기본값 설정
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-northeast-2}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_DB="${POSTGRES_DB:-sesami}"
export POSTGRES_USER="${POSTGRES_USER:-sesami}"
export NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"
export CHROMADB_HOST="${CHROMADB_HOST:-localhost}"
export CHROMADB_PORT="${CHROMADB_PORT:-8000}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

# 기존 컨테이너 정리
echo "🧹 기존 테스트 컨테이너 정리..."
docker rm -f $CONTAINER_NAME 2>/dev/null || true
echo ""

# Docker 이미지 확인
echo "🔍 Docker 이미지 확인..."
if ! docker images $IMAGE_NAME:$IMAGE_TAG | grep -q $IMAGE_NAME; then
    echo "❌ Docker 이미지를 찾을 수 없습니다: $IMAGE_NAME:$IMAGE_TAG"
    echo "   먼저 이미지를 빌드하세요: ./docker-build.sh"
    exit 1
fi
echo "✅ Docker 이미지 확인 완료"
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
    -e AWS_BEDROCK_MODEL_ID_SONNET="$AWS_BEDROCK_MODEL_ID_SONNET"
    -e AWS_BEDROCK_MODEL_ID_HAIKU="$AWS_BEDROCK_MODEL_ID_HAIKU"
    -e POSTGRES_HOST="$POSTGRES_HOST"
    -e POSTGRES_PORT="$POSTGRES_PORT"
    -e POSTGRES_DB="$POSTGRES_DB"
    -e POSTGRES_USER="$POSTGRES_USER"
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
    -e NEO4J_URI="$NEO4J_URI"
    -e NEO4J_USER="$NEO4J_USER"
    -e NEO4J_PASSWORD="$NEO4J_PASSWORD"
    -e CHROMADB_HOST="$CHROMADB_HOST"
    -e CHROMADB_PORT="$CHROMADB_PORT"
    -e DATA_DIR=/app/data
    -e LOG_LEVEL="$LOG_LEVEL"
    -e PYTHONUNBUFFERED=1
    -e TOKENIZERS_PARALLELISM=false
)

docker run \
    --name $CONTAINER_NAME \
    --rm \
    "${ENV_ARGS[@]}" \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/logs:/app/logs \
    $IMAGE_NAME:$IMAGE_TAG

EXIT_CODE=$?

echo ""
echo "============================================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Docker Test PASSED"
else
    echo "❌ Docker Test FAILED (Exit Code: $EXIT_CODE)"
fi
echo "============================================================"
echo ""

# 로그 확인 안내
echo "💡 로그 확인:"
echo "   컨테이너 로그: docker logs $CONTAINER_NAME (이미 종료된 경우 사용 불가)"
echo "   파일 로그: cat ./logs/deep_agents.log"
echo "   실시간 로그: tail -f ./logs/deep_agents.log"
echo ""

# 데이터 확인 안내
echo "💡 데이터 확인:"
echo "   분석 결과: ls -la ./data/analyze/"
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

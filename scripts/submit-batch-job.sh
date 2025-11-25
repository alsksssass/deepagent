#!/bin/bash

# AWS Batch Job 제출 스크립트
# 사용법: ./submit-batch-job.sh [USER_ID] [GIT_URLS] [TARGET_USER] [TASK_IDS] [MAIN_TASK_ID]

set -e

# 스크립트 디렉토리
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# 인자 확인 (옵셔널)
USER_ID=$1
GIT_URLS=$2
TARGET_USER=${3:-""}
TASK_IDS=${4:-""}
MAIN_TASK_ID=${5:-""}

# .env 파일 로드
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# USER_ID가 없으면 생성
if [ -z "$USER_ID" ]; then
    if command -v uuidgen &> /dev/null; then
        export USER_ID=$(uuidgen)
    else
        export USER_ID="00000000-0000-0000-0000-000000000001"
    fi
    echo "⚠️  USER_ID가 설정되지 않아 테스트용 UUID를 생성했습니다: $USER_ID"
fi

# GIT_URLS가 없으면 테스트용 URL 설정
if [ -z "$GIT_URLS" ]; then
    export GIT_URLS="git@github.com:smj53/david.git,git@github.com:alsksssass/david.git"
    echo "⚠️  GIT_URLS가 설정되지 않아 테스트용 URL을 사용합니다: $GIT_URLS"
fi

echo "============================================================"
echo "🚀 AWS Batch Job 제출"
echo "============================================================"
echo ""

# TASK_IDS와 MAIN_TASK_ID가 없으면 자동 생성 및 DB 레코드 생성
if [ -z "$TASK_IDS" ] || [ -z "$MAIN_TASK_ID" ]; then
    echo "📋 TASK_IDS 또는 MAIN_TASK_ID가 없어 자동 생성 및 DB 레코드 생성 중..."
    echo ""
    
    # Python 실행 경로 결정 (가상환경 우선)
    PYTHON_CMD="python3"
    if [ -f "$PROJECT_DIR/.venv/bin/python3" ]; then
        PYTHON_CMD="$PROJECT_DIR/.venv/bin/python3"
    elif [ -f "$PROJECT_DIR/venv/bin/python3" ]; then
        PYTHON_CMD="$PROJECT_DIR/venv/bin/python3"
    elif command -v poetry &> /dev/null; then
        PYTHON_CMD="poetry run python3"
    fi
    
    # create_test_tasks.py 실행
    TASK_OUTPUT=$($PYTHON_CMD "$SCRIPT_DIR/create_test_tasks.py" \
        --user-id "$USER_ID" \
        --git-urls "$GIT_URLS" \
        --export 2>&1)
    
    if [ $? -ne 0 ]; then
        echo "❌ Task 생성 실패:"
        echo "$TASK_OUTPUT"
        exit 1
    fi
    
    # 환경변수 추출
    MAIN_TASK_ID=$(echo "$TASK_OUTPUT" | grep "export MAIN_TASK_ID=" | sed "s/export MAIN_TASK_ID='\(.*\)'/\1/")
    TASK_IDS=$(echo "$TASK_OUTPUT" | grep "export TASK_IDS=" | sed "s/export TASK_IDS='\(.*\)'/\1/")
    
    export MAIN_TASK_ID
    export TASK_IDS
    
    echo "$TASK_OUTPUT"
    echo ""
    echo "✅ Task 생성 완료"
    echo "   MAIN_TASK_ID: $MAIN_TASK_ID"
    echo "   TASK_IDS: $TASK_IDS"
    echo ""
fi

# AWS 설정
AWS_REGION="${S3_REGION:-ap-northeast-2}"
JOB_QUEUE_NAME="deep-agents-queue"
JOB_DEFINITION_NAME="deep-agents-job"
JOB_NAME="deep-agents-$(date +%Y%m%d-%H%M%S)"

echo "📋 Job 정보:"
echo "   Job Name: $JOB_NAME"
echo "   User ID: $USER_ID"
echo "   Git URLs: $GIT_URLS"
echo "   Task IDs: $TASK_IDS"
echo "   Main Task ID: $MAIN_TASK_ID"
echo "   Target User: ${TARGET_USER:-All users}"
echo "   Job Queue: $JOB_QUEUE_NAME"
echo "   Job Definition: $JOB_DEFINITION_NAME"
echo ""

# 환경 변수 오버라이드 구성
ENV_OVERRIDES="[
  {\"name\": \"USER_ID\", \"value\": \"$USER_ID\"},
  {\"name\": \"GIT_URLS\", \"value\": \"$GIT_URLS\"},
  {\"name\": \"TASK_IDS\", \"value\": \"$TASK_IDS\"},
  {\"name\": \"MAIN_TASK_ID\", \"value\": \"$MAIN_TASK_ID\"}"

if [ -n "$TARGET_USER" ]; then
    ENV_OVERRIDES="$ENV_OVERRIDES,
  {\"name\": \"TARGET_USER\", \"value\": \"$TARGET_USER\"}"
fi

ENV_OVERRIDES="$ENV_OVERRIDES
]"

echo "🚀 Job 제출 중..."

# Job 제출
JOB_ID=$(aws batch submit-job \
    --job-name "$JOB_NAME" \
    --job-queue "$JOB_QUEUE_NAME" \
    --job-definition "$JOB_DEFINITION_NAME" \
    --container-overrides "{\"environment\": $ENV_OVERRIDES}" \
    --region "$AWS_REGION" \
    --query 'jobId' \
    --output text)

if [ $? -eq 0 ]; then
    echo "✅ Job 제출 성공!"
    echo ""
    echo "============================================================"
    echo "📊 Job 정보"
    echo "============================================================"
    echo "   Job ID: $JOB_ID"
    echo "   Job Name: $JOB_NAME"
    echo ""
    echo "💡 Job 모니터링:"
    echo "   상태 확인: aws batch describe-jobs --jobs $JOB_ID --region $AWS_REGION"
    echo "   로그 확인: aws logs tail /aws/batch/deep-agents --follow --region $AWS_REGION"
    echo ""
    echo "   AWS 콘솔: https://console.aws.amazon.com/batch/home?region=$AWS_REGION#jobs/detail/$JOB_ID"
    echo ""
else
    echo "❌ Job 제출 실패"
    exit 1
fi

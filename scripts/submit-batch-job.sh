#!/bin/bash

# AWS Batch Job 제출 스크립트
# 사용법: ./submit-batch-job.sh USER_ID GIT_URLS [TARGET_USER]

set -e

# 인자 확인
USER_ID=$1
GIT_URLS=$2
TARGET_USER=${3:-""}

if [ -z "$USER_ID" ] || [ -z "$GIT_URLS" ]; then
    echo "사용법: $0 USER_ID GIT_URLS [TARGET_USER]"
    echo ""
    echo "예시:"
    echo "  단일 레포: $0 123e4567-e89b-12d3-a456-426614174000 'https://github.com/user/repo'"
    echo "  다중 레포: $0 123e4567-e89b-12d3-a456-426614174000 'https://github.com/user/repo1,https://github.com/user/repo2'"
    echo "  특정 유저: $0 123e4567-e89b-12d3-a456-426614174000 'https://github.com/user/repo' user@example.com"
    exit 1
fi

echo "============================================================"
echo "🚀 AWS Batch Job 제출"
echo "============================================================"
echo ""

# .env 파일 로드
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
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
echo "   Target User: ${TARGET_USER:-All users}"
echo "   Job Queue: $JOB_QUEUE_NAME"
echo "   Job Definition: $JOB_DEFINITION_NAME"
echo ""

# 환경 변수 오버라이드 구성
ENV_OVERRIDES="[
  {\"name\": \"USER_ID\", \"value\": \"$USER_ID\"},
  {\"name\": \"GIT_URLS\", \"value\": \"$GIT_URLS\"}"

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

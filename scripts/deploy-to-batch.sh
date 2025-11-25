#!/bin/bash

# 완전 자동화 배포 스크립트
# Docker 빌드 → ECR 푸시 → Job Definition 등록을 한 번에 실행

set -e

echo "============================================================"
echo "🚀 Deep Agents AWS Batch 완전 자동 배포"
echo "============================================================"
echo ""

# 스크립트 디렉토리
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# .env 파일 로드
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# AWS 계정 정보
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="${S3_REGION:-ap-northeast-2}"
ECR_REPO_NAME="deep-agents"
export ECR_REPOSITORY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"
export AWS_REGION

echo "📋 배포 정보:"
echo "   AWS Account: $AWS_ACCOUNT_ID"
echo "   AWS Region: $AWS_REGION"
echo "   ECR Repository: $ECR_REPOSITORY"
echo ""

# Step 1: Docker 빌드 및 ECR 푸시
echo "============================================================"
echo "📦 Step 1/2: Docker 이미지 빌드 및 ECR 푸시"
echo "============================================================"
echo ""

./docker-build.sh

if [ $? -ne 0 ]; then
    echo "❌ Docker 빌드 실패"
    exit 1
fi

echo ""

# Step 2: 기존 Job Definition 삭제
echo "============================================================"
echo "🧹 Step 2/3: 기존 Job Definition 삭제"
echo "============================================================"
echo ""

JOB_DEF_NAME="deep-agents-job"

# ACTIVE 상태인 Job Definition ARN 목록 조회
echo "🔍 ACTIVE 상태의 Job Definition 조회 중..."
ARNS=$(aws batch describe-job-definitions \
    --job-definition-name "$JOB_DEF_NAME" \
    --status ACTIVE \
    --region $AWS_REGION \
    --query 'jobDefinitions[*].jobDefinitionArn' \
    --output text 2>/dev/null || echo "")

if [ -z "$ARNS" ] || [ "$ARNS" == "None" ]; then
    echo "✅ 삭제할 ACTIVE Job Definition이 없습니다."
else
    # 공백/탭을 줄바꿈으로 변환하여 배열로 저장
    IFS=$'\t\n' read -ra ARN_LIST <<< "$ARNS"
    
    COUNT=${#ARN_LIST[@]}
    echo "📋 총 $COUNT 개의 Job Definition을 삭제(Deregister)합니다."
    echo ""
    
    for arn in "${ARN_LIST[@]}"; do
        echo "🗑️  Deregistering: $arn"
        aws batch deregister-job-definition \
            --job-definition "$arn" \
            --region $AWS_REGION > /dev/null
        
        if [ $? -eq 0 ]; then
            echo "   ✅ 완료"
        else
            echo "   ⚠️  실패 (계속 진행)"
        fi
    done
    
    echo "✅ 기존 Job Definition 삭제 완료"
fi

echo ""

# Step 3: Job Definition 등록
echo "============================================================"
echo "📝 Step 3/3: Job Definition 등록"
echo "============================================================"
echo ""

./scripts/register-job-definition.sh

if [ $? -ne 0 ]; then
    echo "❌ Job Definition 등록 실패"
    exit 1
fi

echo ""
echo "============================================================"
echo "✅ 배포 완료!"
echo "============================================================"
echo ""
echo "💡 Job 제출 방법:"
echo "   ./scripts/submit-batch-job.sh USER_ID 'GIT_URLS' [TARGET_USER]"
echo ""
echo "예시:"
echo "   ./scripts/submit-batch-job.sh 123e4567-e89b-12d3-a456-426614174000 'https://github.com/user/repo'"
echo ""

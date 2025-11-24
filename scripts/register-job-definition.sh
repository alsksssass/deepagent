#!/bin/bash

# Job Definition 등록 스크립트
# Docker 이미지를 ECR에 푸시한 후 Job Definition을 등록합니다

set -e

echo "============================================================"
echo "📝 AWS Batch Job Definition 등록"
echo "============================================================"
echo ""

# .env 파일 로드
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# AWS 계정 정보
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="${S3_REGION:-ap-northeast-2}"
ECR_REPO_NAME="deep-agents"
ECR_REPOSITORY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

echo "📋 설정 정보:"
echo "   AWS Account: $AWS_ACCOUNT_ID"
echo "   AWS Region: $AWS_REGION"
echo "   ECR Repository: $ECR_REPOSITORY"
echo "   Image Tag: $IMAGE_TAG"
echo ""

# Job Definition 파일 확인
if [ ! -f "aws-batch-job-definition.json" ]; then
    echo "❌ aws-batch-job-definition.json 파일을 찾을 수 없습니다"
    echo "   먼저 ./setup-aws-batch.sh를 실행하세요"
    exit 1
fi

# 최신 이미지 URI로 업데이트
IMAGE_URI="$ECR_REPOSITORY:$IMAGE_TAG"

echo "🔨 Job Definition 등록 중..."
echo "   Image: $IMAGE_URI"
echo ""

# Job Definition 등록 (JSON 파일 그대로 사용)
aws batch register-job-definition \
    --cli-input-json file://aws-batch-job-definition.json \
    --region $AWS_REGION

if [ $? -eq 0 ]; then
    echo "✅ Job Definition 등록 완료"
    
    # 최신 버전 확인
    LATEST_REVISION=$(aws batch describe-job-definitions \
        --job-definition-name deep-agents-job \
        --status ACTIVE \
        --region $AWS_REGION \
        --query 'jobDefinitions[0].revision' \
        --output text)
    
    echo "   Job Definition: deep-agents-job:$LATEST_REVISION"
else
    echo "❌ Job Definition 등록 실패"
    exit 1
fi

echo ""
echo "============================================================"
echo "✅ 등록 완료"
echo "============================================================"
echo ""
echo "💡 다음 단계:"
echo "   테스트 Job 제출: ./scripts/test-batch-job.sh"
echo "   또는 직접 제출: ./scripts/submit-batch-job.sh USER_ID 'GIT_URLS' [TARGET_USER]"
echo ""
echo "📋 환경 변수 확인:"
echo "   - AWS_BEDROCK_REGION: ${AWS_BEDROCK_REGION:-us-east-1}"
echo "   - NEO4J_URI: ${NEO4J_URI:-bolt://172.31.41.218:7687}"
echo "   - CHROMADB_HOST: ${CHROMADB_HOST:-172.31.41.218}"
echo ""

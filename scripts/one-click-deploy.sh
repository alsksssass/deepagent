#!/bin/bash

# 원큐 배포 스크립트
# AWS Batch 리소스 생성부터 Job 제출까지 한 번에 실행

set -e

echo "============================================================"
echo "🚀 Deep Agents 원큐 배포 시작"
echo "============================================================"
echo ""

# 스크립트 디렉토리
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# .env 파일 확인
if [ ! -f .env ]; then
    echo "❌ .env 파일을 찾을 수 없습니다"
    echo "   .env.example을 복사하여 .env 파일을 생성하세요"
    exit 1
fi

# .env 파일 로드
export $(grep -v '^#' .env | xargs)

# 필수 환경 변수 확인
echo "🔍 필수 환경 변수 확인 중..."
MISSING_VARS=()

if [ -z "$AWS_BEDROCK_REGION" ]; then
    echo "⚠️  AWS_BEDROCK_REGION이 설정되지 않았습니다. 기본값(us-east-1)을 사용합니다."
    export AWS_BEDROCK_REGION="${AWS_BEDROCK_REGION:-us-east-1}"
fi

if [ -z "$NEO4J_URI" ]; then
    echo "⚠️  NEO4J_URI가 설정되지 않았습니다. 기본값(bolt://172.31.41.218:7687)을 사용합니다."
    export NEO4J_URI="${NEO4J_URI:-bolt://172.31.41.218:7687}"
fi

if [ -z "$CHROMADB_HOST" ]; then
    echo "⚠️  CHROMADB_HOST가 설정되지 않았습니다. 기본값(172.31.41.218)을 사용합니다."
    export CHROMADB_HOST="${CHROMADB_HOST:-172.31.41.218}"
fi

echo "✅ 환경 변수 확인 완료"
echo "   AWS_BEDROCK_REGION: ${AWS_BEDROCK_REGION:-us-east-1}"
echo "   NEO4J_URI: ${NEO4J_URI:-bolt://172.31.41.218:7687}"
echo "   CHROMADB_HOST: ${CHROMADB_HOST:-172.31.41.218}"
echo ""

# AWS 자격 증명 확인
echo "🔐 AWS 자격 증명 확인 중..."
if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "❌ AWS 자격 증명이 설정되지 않았습니다"
    echo "   'aws configure' 명령어로 자격 증명을 설정하세요"
    exit 1
fi
echo "✅ AWS 자격 증명 확인 완료"
echo ""

# Step 1: AWS Batch 리소스 생성
echo "============================================================"
echo "📦 Step 1/3: AWS Batch 리소스 생성"
echo "============================================================"
echo ""

if [ -f "scripts/setup-aws-batch.sh" ]; then
    ./scripts/setup-aws-batch.sh
else
    echo "⚠️  setup-aws-batch.sh를 찾을 수 없습니다. 건너뜁니다."
fi

echo ""

# Step 2: Docker 빌드 및 배포
echo "============================================================"
echo "🐳 Step 2/3: Docker 이미지 빌드 및 배포"
echo "============================================================"
echo ""

if [ -f "scripts/deploy-to-batch.sh" ]; then
    ./scripts/deploy-to-batch.sh
else
    echo "❌ deploy-to-batch.sh를 찾을 수 없습니다"
    exit 1
fi

echo ""

# Step 3: 테스트 Job 제출 (옵션)
echo "============================================================"
echo "🧪 Step 3/3: 테스트 Job 제출 (옵션)"
echo "============================================================"
echo ""

echo ""
echo "============================================================"
echo "✅ 원큐 배포 완료!"
echo "============================================================"
echo ""
echo "📋 생성된 리소스:"
echo "   - ECR Repository"
echo "   - IAM Role"
echo "   - Compute Environment"
echo "   - Job Queue"
echo "   - Job Definition"
echo "   - Docker Image (ECR에 푸시됨)"
echo ""
echo "💡 다음 단계:"
echo "   테스트 Job 제출: ./scripts/test-batch-job.sh"
echo "   또는 직접 제출: ./scripts/submit-batch-job.sh USER_ID 'GIT_URLS' [TARGET_USER]"
echo ""
echo "📋 주요 환경 변수:"
echo "   - AWS_BEDROCK_REGION: ${AWS_BEDROCK_REGION:-us-east-1} (Bedrock API 리전)"
echo "   - AWS_DEFAULT_REGION: ${AWS_DEFAULT_REGION:-ap-northeast-2} (기타 AWS 서비스 리전)"
echo "   - NEO4J_URI: ${NEO4J_URI:-bolt://172.31.41.218:7687} (프라이빗 IP 사용)"
echo "   - CHROMADB_HOST: ${CHROMADB_HOST:-172.31.41.218} (프라이빗 IP 사용)"
echo ""

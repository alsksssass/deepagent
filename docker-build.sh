#!/bin/bash

# Docker Build Script for Deep Agents
# Docker 이미지 빌드 및 AWS ECR 푸시

set -e  # 에러 발생 시 중단

echo "============================================================"
echo "🐳 Deep Agents Docker Build"
echo "============================================================"
echo ""

# 변수 설정
IMAGE_NAME="deep-agents"
IMAGE_TAG="${IMAGE_TAG:-latest}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
ECR_REPOSITORY="${ECR_REPOSITORY:-}"  # 예: 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/deep-agents

# 1. Docker 이미지 빌드
echo "📦 Step 1: Building Docker image..."
echo "   Image: $IMAGE_NAME:$IMAGE_TAG"
echo ""

docker build \
    --platform linux/amd64 \
    --tag $IMAGE_NAME:$IMAGE_TAG \
    --file Dockerfile \
    .

if [ $? -eq 0 ]; then
    echo "✅ Docker 이미지 빌드 성공"
else
    echo "❌ Docker 이미지 빌드 실패"
    exit 1
fi

echo ""

# 2. Docker 이미지 정보 확인
echo "📊 Step 2: Docker image info"
docker images $IMAGE_NAME:$IMAGE_TAG

echo ""

# 3. 이미지 크기 확인
IMAGE_SIZE=$(docker images $IMAGE_NAME:$IMAGE_TAG --format "{{.Size}}")
echo "📏 Image size: $IMAGE_SIZE"

echo ""

# 4. ECR 푸시 (옵션)
if [ -n "$ECR_REPOSITORY" ]; then
    echo "📤 Step 3: Pushing to AWS ECR..."
    echo "   ECR Repository: $ECR_REPOSITORY"
    echo ""

    # ECR 로그인
    echo "🔐 Logging in to ECR..."
    aws ecr get-login-password --region $AWS_REGION | \
        docker login --username AWS --password-stdin $ECR_REPOSITORY

    if [ $? -ne 0 ]; then
        echo "❌ ECR 로그인 실패"
        exit 1
    fi

    echo "✅ ECR 로그인 성공"
    echo ""

    # 이미지 태그
    echo "🏷️  Tagging image..."
    docker tag $IMAGE_NAME:$IMAGE_TAG $ECR_REPOSITORY:$IMAGE_TAG

    # 이미지 푸시
    echo "📤 Pushing image to ECR..."
    docker push $ECR_REPOSITORY:$IMAGE_TAG

    if [ $? -eq 0 ]; then
        echo "✅ ECR 푸시 성공"
        echo "   Image URI: $ECR_REPOSITORY:$IMAGE_TAG"
    else
        echo "❌ ECR 푸시 실패"
        exit 1
    fi
else
    echo "ℹ️  ECR_REPOSITORY 환경 변수가 설정되지 않아 ECR 푸시를 건너뜁니다"
    echo "   ECR 푸시를 원하시면 다음과 같이 실행하세요:"
    echo "   export ECR_REPOSITORY=123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/deep-agents"
    echo "   ./docker-build.sh"
fi

echo ""
echo "============================================================"
echo "✅ Docker Build Complete"
echo "============================================================"
echo ""
echo "💡 다음 단계:"
echo "   로컬 테스트: ./docker-test.sh"
echo "   로컬 테스트: ./scripts/local-test.sh"
echo "   AWS Batch: AWS Batch Job Definition에서 이미지 URI 사용"
echo ""

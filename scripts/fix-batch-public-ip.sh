#!/bin/bash

# AWS Batch Compute Environment Public IP 활성화 스크립트
# Job ID 5ec78b43-56d2-4f13-978a-53740eaeb29e 문제 해결

set -e

echo "============================================================"
echo "🔧 AWS Batch Public IP 활성화"
echo "============================================================"
echo ""

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
COMPUTE_ENV_NAME="deep-agents-compute"
SECURITY_GROUP="sg-0d09f4a3e612ae6d3"

# Internet Gateway를 사용하는 서브넷 식별
echo "🔍 Internet Gateway 사용 서브넷 확인 중..."
IGW_SUBNETS=""

for SUBNET in subnet-075cea44bae81e973 subnet-0497c14682eb53623 subnet-0a0cc4ceb1c1b27dc subnet-0119ff3b1be2361ff; do
  echo "   확인 중: $SUBNET"
  
  # 라우팅 테이블에서 Internet Gateway 확인
  HAS_IGW=$(aws ec2 describe-route-tables \
    --filters "Name=association.subnet-id,Values=$SUBNET" \
    --region $AWS_REGION \
    --query 'RouteTables[0].Routes[?contains(GatewayId, `igw-`)]' \
    --output text 2>/dev/null || echo "")
  
  if [ -n "$HAS_IGW" ] && [ "$HAS_IGW" != "None" ]; then
    echo "   ✅ Internet Gateway 사용: $SUBNET"
    IGW_SUBNETS="$IGW_SUBNETS,$SUBNET"
  else
    echo "   ❌ Internet Gateway 없음: $SUBNET"
  fi
done

# 앞의 쉼표 제거
IGW_SUBNETS=$(echo $IGW_SUBNETS | sed 's/^,//')

if [ -z "$IGW_SUBNETS" ]; then
  echo "❌ Internet Gateway를 사용하는 서브넷을 찾을 수 없습니다"
  echo "   서브넷의 라우팅 테이블에 Internet Gateway를 추가하세요"
  exit 1
fi

echo ""
echo "✅ Internet Gateway 사용 서브넷: $IGW_SUBNETS"
echo ""

# Compute Environment 업데이트
echo "🔨 Compute Environment 업데이트 중..."
echo "   서브넷: $IGW_SUBNETS"
echo "   보안 그룹: $SECURITY_GROUP"
echo ""

# Job Queue 비활성화 (필요 시)
echo "📋 Job Queue 상태 확인 중..."
QUEUE_STATUS=$(aws batch describe-job-queues \
  --job-queues deep-agents-queue \
  --region $AWS_REGION \
  --query 'jobQueues[0].state' \
  --output text 2>/dev/null || echo "DISABLED")

if [ "$QUEUE_STATUS" = "ENABLED" ]; then
  echo "   Job Queue 비활성화 중..."
  aws batch update-job-queue \
    --job-queue-name deep-agents-queue \
    --state DISABLED \
    --region $AWS_REGION
  echo "   ⏳ Job Queue 비활성화 대기 중..."
  sleep 10
fi

# Compute Environment 업데이트
echo "🔨 Compute Environment 업데이트 중..."
aws batch update-compute-environment \
  --compute-environment-name $COMPUTE_ENV_NAME \
  --compute-resources "type=FARGATE,maxvCpus=16,subnets=$IGW_SUBNETS,securityGroupIds=$SECURITY_GROUP" \
  --region $AWS_REGION

echo "✅ Compute Environment 업데이트 완료"
echo "⏳ Compute Environment 활성화 대기 중..."

# Compute Environment가 VALID 상태가 될 때까지 대기
for i in {1..30}; do
  STATUS=$(aws batch describe-compute-environments \
    --compute-environments $COMPUTE_ENV_NAME \
    --region $AWS_REGION \
    --query 'computeEnvironments[0].status' \
    --output text)
  
  if [ "$STATUS" = "VALID" ]; then
    echo "✅ Compute Environment 활성화 완료"
    break
  fi
  
  echo "   상태: $STATUS (${i}/30)"
  sleep 5
done

# Job Queue 재활성화
if [ "$QUEUE_STATUS" = "ENABLED" ]; then
  echo ""
  echo "📋 Job Queue 재활성화 중..."
  aws batch update-job-queue \
    --job-queue-name deep-agents-queue \
    --state ENABLED \
    --region $AWS_REGION
  echo "✅ Job Queue 재활성화 완료"
fi

echo ""
echo "============================================================"
echo "✅ Public IP 활성화 완료!"
echo "============================================================"
echo ""
echo "📋 변경 사항:"
echo "   - Compute Environment가 Internet Gateway 사용 서브넷만 사용"
echo "   - Fargate 태스크에 Public IP 자동 할당"
echo "   - ECR, Git, Bedrock API 접근 가능"
echo ""
echo "💡 다음 단계:"
echo "   테스트 Job 제출: ./scripts/submit-batch-job.sh USER_ID 'GIT_URLS' [TARGET_USER]"
echo ""


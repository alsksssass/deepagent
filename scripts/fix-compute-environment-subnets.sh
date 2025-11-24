#!/bin/bash
# Compute Environment를 환경 변수와 일치시키기

set -e

AWS_REGION="ap-northeast-2"
COMPUTE_ENV_NAME="deep-agents-compute"
SECURITY_GROUP="sg-0d09f4a3e612ae6d3"

# ECR VPC Endpoint 지원 서브넷만 사용 (환경 변수와 일치)
SUBNETS="subnet-075cea44bae81e973,subnet-0497c14682eb53623,subnet-0a0cc4ceb1c1b27dc"

echo "============================================================"
echo "🔧 Compute Environment 서브넷 수정"
echo "============================================================"
echo ""
echo "📋 변경 사항:"
echo "   현재: 4개 서브넷 (subnet-0119ff3b1be2361ff 포함)"
echo "   변경: 3개 서브넷 (ECR VPC Endpoint 지원 서브넷만)"
echo "   서브넷: $SUBNETS"
echo ""

# Job Queue 비활성화
echo "📋 Job Queue 비활성화 중..."
QUEUE_STATUS=$(aws batch describe-job-queues \
  --job-queues deep-agents-queue \
  --region $AWS_REGION \
  --query 'jobQueues[0].state' \
  --output text 2>/dev/null || echo "DISABLED")

if [ "$QUEUE_STATUS" = "ENABLED" ]; then
  echo "   Job Queue 비활성화 중..."
  aws batch update-job-queue \
    --job-queue deep-agents-queue \
    --state DISABLED \
    --region $AWS_REGION
  echo "   ⏳ Job Queue 비활성화 대기 중..."
  sleep 10
else
  echo "   Job Queue가 이미 비활성화되어 있음"
fi

# Compute Environment 업데이트
echo "🔨 Compute Environment 업데이트 중..."
# Fargate는 type을 제외하고 업데이트해야 함
cat > /tmp/compute-resources-update.json << EOF
{
  "maxvCpus": 16,
  "subnets": [
    "subnet-075cea44bae81e973",
    "subnet-0497c14682eb53623",
    "subnet-0a0cc4ceb1c1b27dc"
  ],
  "securityGroupIds": [
    "$SECURITY_GROUP"
  ]
}
EOF

aws batch update-compute-environment \
  --compute-environment $COMPUTE_ENV_NAME \
  --compute-resources file:///tmp/compute-resources-update.json \
  --region $AWS_REGION

echo "✅ 업데이트 완료"
echo "⏳ 활성화 대기 중..."

# 활성화 대기
for i in {1..30}; do
  STATUS=$(aws batch describe-compute-environments \
    --compute-environments $COMPUTE_ENV_NAME \
    --region $AWS_REGION \
    --query 'computeEnvironments[0].status' \
    --output text)
  
  if [ "$STATUS" = "VALID" ]; then
    echo "✅ 활성화 완료"
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
    --job-queue deep-agents-queue \
    --state ENABLED \
    --region $AWS_REGION
  echo "✅ Job Queue 재활성화 완료"
fi

echo ""
echo "============================================================"
echo "✅ Compute Environment 서브넷 수정 완료!"
echo "============================================================"
echo ""
echo "📋 변경 사항:"
echo "   - subnet-0119ff3b1be2361ff 제외 (ECR VPC Endpoint 미지원)"
echo "   - ECR VPC Endpoint 지원 서브넷만 사용"
echo "   - 환경 변수와 일치"
echo ""

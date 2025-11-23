#!/bin/bash

# US-East-1 리소스 정리 스크립트
# 실수로 생성된 us-east-1 리전의 AWS Batch 및 ECR 리소스를 삭제합니다.

set -e

REGION="us-east-1"
JOB_QUEUE="deep-agents-queue"
COMPUTE_ENV="deep-agents-compute"
JOB_DEF="deep-agents-job"
ECR_REPO="deep-agents"

echo "============================================================"
echo "🧹 US-East-1 리소스 정리 시작"
echo "============================================================"
echo "   Region: $REGION"
echo ""

# 1. Job Queue 삭제
echo "🗑️  Step 1: Job Queue 삭제 ($JOB_QUEUE)"
if aws batch describe-job-queues --job-queues $JOB_QUEUE --region $REGION --query 'jobQueues[0].jobQueueName' --output text 2>/dev/null | grep -q "$JOB_QUEUE"; then
    # 상태 확인
    STATUS=$(aws batch describe-job-queues --job-queues $JOB_QUEUE --region $REGION --query 'jobQueues[0].status' --output text)
    STATE=$(aws batch describe-job-queues --job-queues $JOB_QUEUE --region $REGION --query 'jobQueues[0].state' --output text)
    
    echo "   현재 상태: $STATUS ($STATE)"
    
    if [ "$STATUS" == "DELETING" ]; then
        echo "   이미 삭제 중입니다. 대기합니다..."
    elif [ "$STATE" == "ENABLED" ] || [ "$STATUS" == "UPDATING" ]; then
        echo "   Job Queue 비활성화 중..."
        # 에러 무시 (이미 처리 중일 수 있음)
        aws batch update-job-queue --job-queue $JOB_QUEUE --state DISABLED --region $REGION >/dev/null 2>&1 || true
        
        echo "   Job Queue 비활성화 대기 중..."
        while true; do
            CURRENT_STATUS=$(aws batch describe-job-queues --job-queues $JOB_QUEUE --region $REGION --query 'jobQueues[0].status' --output text)
            if [ "$CURRENT_STATUS" == "VALID" ] || [ "$CURRENT_STATUS" == "INVALID" ]; then
                break
            fi
            echo "   상태: $CURRENT_STATUS (대기 중...)"
            sleep 2
        done
    fi
    
    if [ "$STATUS" != "DELETING" ]; then
        echo "   Job Queue 삭제 중..."
        aws batch delete-job-queue --job-queue $JOB_QUEUE --region $REGION >/dev/null 2>&1 || true
    fi
    
    echo "   Job Queue 삭제 확인 중..."
    while true; do
        if ! aws batch describe-job-queues --job-queues $JOB_QUEUE --region $REGION --query 'jobQueues[0].jobQueueName' --output text 2>/dev/null | grep -q "$JOB_QUEUE"; then
            break
        fi
        echo "   Job Queue가 아직 존재합니다. 대기 중..."
        sleep 5
    done
    echo "   ✅ Job Queue 삭제 완료"
else
    echo "   ℹ️  Job Queue가 존재하지 않습니다."
fi
echo ""

# 2. Compute Environment 삭제
echo "🗑️  Step 2: Compute Environment 삭제 ($COMPUTE_ENV)"
if aws batch describe-compute-environments --compute-environments $COMPUTE_ENV --region $REGION --query 'computeEnvironments[0].computeEnvironmentName' --output text 2>/dev/null | grep -q "$COMPUTE_ENV"; then
    echo "   Compute Environment 비활성화 중..."
    aws batch update-compute-environment --compute-environment $COMPUTE_ENV --state DISABLED --region $REGION >/dev/null
    
    echo "   Compute Environment 비활성화 대기 중..."
    while true; do
        STATUS=$(aws batch describe-compute-environments --compute-environments $COMPUTE_ENV --region $REGION --query 'computeEnvironments[0].status' --output text)
        if [ "$STATUS" != "UPDATING" ]; then
            break
        fi
        sleep 2
    done
    
    echo "   Compute Environment 삭제 중..."
    aws batch delete-compute-environment --compute-environment $COMPUTE_ENV --region $REGION >/dev/null
    echo "   ✅ Compute Environment 삭제 완료"
else
    echo "   ℹ️  Compute Environment가 존재하지 않습니다."
fi
echo ""

# 3. Job Definitions 삭제
echo "🗑️  Step 3: Job Definitions 삭제 ($JOB_DEF)"
ARNS=$(aws batch describe-job-definitions --job-definition-name $JOB_DEF --status ACTIVE --region $REGION --query 'jobDefinitions[*].jobDefinitionArn' --output text)

if [ -n "$ARNS" ] && [ "$ARNS" != "None" ]; then
    for ARN in $ARNS; do
        echo "   Deregistering: $ARN"
        aws batch deregister-job-definition --job-definition $ARN --region $REGION >/dev/null
    done
    echo "   ✅ Job Definitions 삭제 완료"
else
    echo "   ℹ️  삭제할 Job Definition이 없습니다."
fi
echo ""

# 4. ECR Repository 삭제
echo "🗑️  Step 4: ECR Repository 삭제 ($ECR_REPO)"
if aws ecr describe-repositories --repository-names $ECR_REPO --region $REGION >/dev/null 2>&1; then
    echo "   ECR Repository 강제 삭제 중 (이미지 포함)..."
    aws ecr delete-repository --repository-name $ECR_REPO --region $REGION --force >/dev/null
    echo "   ✅ ECR Repository 삭제 완료"
else
    echo "   ℹ️  ECR Repository가 존재하지 않습니다."
fi

echo ""
echo "============================================================"
echo "✅ US-East-1 정리 완료!"
echo "============================================================"

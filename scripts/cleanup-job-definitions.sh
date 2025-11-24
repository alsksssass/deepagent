#!/bin/bash

# AWS Batch Job Definition 정리 스크립트
# deep-agents-job의 모든 ACTIVE 리비전을 비활성화(Deregister)합니다.

JOB_DEF_NAME="deep-agents-job"

echo "============================================================"
echo "🧹 AWS Batch Job Definition 정리: $JOB_DEF_NAME"
echo "============================================================"

# ACTIVE 상태인 Job Definition ARN 목록 조회
echo "🔍 ACTIVE 상태의 Job Definition 조회 중..."
ARNS=$(aws batch describe-job-definitions \
    --job-definition-name "$JOB_DEF_NAME" \
    --status ACTIVE \
    --query 'jobDefinitions[*].jobDefinitionArn' \
    --output text)

if [ -z "$ARNS" ]; then
    echo "✅ 삭제할 ACTIVE Job Definition이 없습니다."
    exit 0
fi

# 공백/탭을 줄바꿈으로 변환하여 배열로 저장
IFS=$'\t\n' read -ra ARN_LIST <<< "$ARNS"

COUNT=${#ARN_LIST[@]}
echo "📋 총 $COUNT 개의 Job Definition을 삭제(Deregister)합니다."
echo ""

for arn in "${ARN_LIST[@]}"; do
    echo "🗑️  Deregistering: $arn"
    aws batch deregister-job-definition --job-definition "$arn" > /dev/null
    
    if [ $? -eq 0 ]; then
        echo "   ✅ 완료"
    else
        echo "   ❌ 실패"
    fi
done

echo ""
echo "============================================================"
echo "✅ 정리 완료"
echo "============================================================"

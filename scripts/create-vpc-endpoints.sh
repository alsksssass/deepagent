#!/bin/bash

# VPC 엔드포인트 생성 스크립트
# Fargate가 ECR에 접근할 수 있도록 VPC 엔드포인트 생성

set -e

echo "============================================================"
echo "🔗 VPC 엔드포인트 생성"
echo "============================================================"
echo ""

# .env 파일 로드
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

AWS_REGION="${S3_REGION:-ap-northeast-2}"

echo "📋 설정 정보:"
echo "   Region: $AWS_REGION"
echo ""

# VPC ID 가져오기
if [ -n "$AWS_VPC_ID" ]; then
    VPC_ID="$AWS_VPC_ID"
    echo "   VPC ID (from .env): $VPC_ID"
else
    VPC_ID=$(aws ec2 describe-vpcs \
        --filters "Name=isDefault,Values=true" \
        --region $AWS_REGION \
        --query 'Vpcs[0].VpcId' \
        --output text)
    echo "   VPC ID (auto-detected): $VPC_ID"
fi

# 서브넷 가져오기
if [ -n "$AWS_SUBNET_IDS" ]; then
    # 쉼표로 구분된 문자열을 공백으로 변환하여 배열로 처리 가능하게 함 (AWS CLI는 공백 구분 선호)
    SUBNETS=$(echo "$AWS_SUBNET_IDS" | tr ',' ' ')
    echo "   Subnets (from .env): $SUBNETS"
else
    SUBNETS=$(aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --region $AWS_REGION \
        --query 'Subnets[*].SubnetId' \
        --output text)
    echo "   Subnets (auto-detected): $SUBNETS"
fi

# Security Group 가져오기
SECURITY_GROUP=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=default" \
    --region $AWS_REGION \
    --query 'SecurityGroups[0].GroupId' \
    --output text)

echo "   Security Group: $SECURITY_GROUP"
echo ""

# 1. ECR Docker 엔드포인트
echo "============================================================"
echo "📦 Step 1/3: ECR Docker 엔드포인트 생성"
echo "============================================================"

ECR_DKR_ENDPOINT=$(aws ec2 describe-vpc-endpoints \
    --region $AWS_REGION \
    --filters "Name=service-name,Values=com.amazonaws.${AWS_REGION}.ecr.dkr" "Name=vpc-id,Values=$VPC_ID" \
    --query 'VpcEndpoints[0].VpcEndpointId' \
    --output text 2>/dev/null || echo "None")

if [ "$ECR_DKR_ENDPOINT" != "None" ] && [ -n "$ECR_DKR_ENDPOINT" ]; then
    echo "ℹ️  ECR Docker 엔드포인트가 이미 존재합니다: $ECR_DKR_ENDPOINT"
else
    echo "🔨 ECR Docker 엔드포인트 생성 중..."
    aws ec2 create-vpc-endpoint \
        --vpc-id $VPC_ID \
        --vpc-endpoint-type Interface \
        --service-name com.amazonaws.${AWS_REGION}.ecr.dkr \
        --subnet-ids $SUBNETS \
        --security-group-ids $SECURITY_GROUP \
        --region $AWS_REGION \
        --private-dns-enabled
    echo "✅ ECR Docker 엔드포인트 생성 완료"
fi

echo ""

# 2. ECR API 엔드포인트
echo "============================================================"
echo "🔧 Step 2/3: ECR API 엔드포인트 생성"
echo "============================================================"

ECR_API_ENDPOINT=$(aws ec2 describe-vpc-endpoints \
    --region $AWS_REGION \
    --filters "Name=service-name,Values=com.amazonaws.${AWS_REGION}.ecr.api" "Name=vpc-id,Values=$VPC_ID" \
    --query 'VpcEndpoints[0].VpcEndpointId' \
    --output text 2>/dev/null || echo "None")

if [ "$ECR_API_ENDPOINT" != "None" ] && [ -n "$ECR_API_ENDPOINT" ]; then
    echo "ℹ️  ECR API 엔드포인트가 이미 존재합니다: $ECR_API_ENDPOINT"
else
    echo "🔨 ECR API 엔드포인트 생성 중..."
    aws ec2 create-vpc-endpoint \
        --vpc-id $VPC_ID \
        --vpc-endpoint-type Interface \
        --service-name com.amazonaws.${AWS_REGION}.ecr.api \
        --subnet-ids $SUBNETS \
        --security-group-ids $SECURITY_GROUP \
        --region $AWS_REGION \
        --private-dns-enabled
    echo "✅ ECR API 엔드포인트 생성 완료"
fi

echo ""

# 3. S3 Gateway 엔드포인트
echo "============================================================"
echo "📁 Step 3/3: S3 Gateway 엔드포인트 생성"
echo "============================================================"

S3_ENDPOINT=$(aws ec2 describe-vpc-endpoints \
    --region $AWS_REGION \
    --filters "Name=service-name,Values=com.amazonaws.${AWS_REGION}.s3" "Name=vpc-id,Values=$VPC_ID" \
    --query 'VpcEndpoints[0].VpcEndpointId' \
    --output text 2>/dev/null || echo "None")

if [ "$S3_ENDPOINT" != "None" ] && [ -n "$S3_ENDPOINT" ]; then
    echo "ℹ️  S3 Gateway 엔드포인트가 이미 존재합니다: $S3_ENDPOINT"
else
    echo "🔨 S3 Gateway 엔드포인트 생성 중..."
    
    # Route Table ID 가져오기
    ROUTE_TABLE_ID=$(aws ec2 describe-route-tables \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --region $AWS_REGION \
        --query 'RouteTables[0].RouteTableId' \
        --output text)
    
    aws ec2 create-vpc-endpoint \
        --vpc-id $VPC_ID \
        --vpc-endpoint-type Gateway \
        --service-name com.amazonaws.${AWS_REGION}.s3 \
        --route-table-ids $ROUTE_TABLE_ID \
        --region $AWS_REGION
    echo "✅ S3 Gateway 엔드포인트 생성 완료"
fi

echo ""

# 4. CloudWatch Logs 엔드포인트
echo "============================================================"
echo "📝 Step 4/4: CloudWatch Logs 엔드포인트 생성"
echo "============================================================"

LOGS_ENDPOINT=$(aws ec2 describe-vpc-endpoints \
    --region $AWS_REGION \
    --filters "Name=service-name,Values=com.amazonaws.${AWS_REGION}.logs" "Name=vpc-id,Values=$VPC_ID" \
    --query 'VpcEndpoints[0].VpcEndpointId' \
    --output text 2>/dev/null || echo "None")

if [ "$LOGS_ENDPOINT" != "None" ] && [ -n "$LOGS_ENDPOINT" ]; then
    echo "ℹ️  CloudWatch Logs 엔드포인트가 이미 존재합니다: $LOGS_ENDPOINT"
else
    echo "🔨 CloudWatch Logs 엔드포인트 생성 중..."
    aws ec2 create-vpc-endpoint \
        --vpc-id $VPC_ID \
        --vpc-endpoint-type Interface \
        --service-name com.amazonaws.${AWS_REGION}.logs \
        --subnet-ids $SUBNETS \
        --security-group-ids $SECURITY_GROUP \
        --region $AWS_REGION \
        --private-dns-enabled
    echo "✅ CloudWatch Logs 엔드포인트 생성 완료"
fi

echo ""
echo "============================================================"
echo "✅ VPC 엔드포인트 생성 완료!"
echo "============================================================"
echo ""
echo "💡 다음 단계:"
echo "   1. 엔드포인트가 'available' 상태가 될 때까지 대기 (약 2-3분)"
echo "   2. Job 재제출: ./scripts/submit-batch-job.sh USER_ID 'GIT_URLS'"
echo ""

#!/bin/bash

# 서브넷을 Public 서브넷으로 전환하고 NAT Gateway 비활성화 스크립트

set -e

echo "============================================================"
echo "🌐 Public 서브넷 전환 및 NAT Gateway 비활성화"
echo "============================================================"
echo ""

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
VPC_ID="vpc-0c5660c688254bb41"
IGW_ID="igw-037a3a7833fdd61f0"
NAT_GW_ID="nat-18c66589956b2bbb4"
SUBNETS=("subnet-075cea44bae81e973" "subnet-0497c14682eb53623" "subnet-0a0cc4ceb1c1b27dc" "subnet-0119ff3b1be2361ff")

echo "📋 현재 상태 확인 중..."
echo ""

# 1. 모든 서브넷의 라우팅 테이블 확인
echo "🔍 서브넷 라우팅 테이블 확인 중..."
declare -A SUBNET_RTBS

for SUBNET in "${SUBNETS[@]}"; do
    echo "   확인 중: $SUBNET"
    
    # 서브넷에 연결된 라우팅 테이블 찾기
    RTB_ID=$(aws ec2 describe-route-tables \
        --filters "Name=association.subnet-id,Values=$SUBNET" \
        --region $AWS_REGION \
        --query 'RouteTables[0].RouteTableId' \
        --output text 2>/dev/null || echo "")
    
    if [ -z "$RTB_ID" ] || [ "$RTB_ID" = "None" ]; then
        # 서브넷에 명시적 라우팅 테이블이 없으면 Internet Gateway 사용 라우팅 테이블 찾기
        RTB_ID=$(aws ec2 describe-route-tables \
            --filters "Name=vpc-id,Values=$VPC_ID" \
            --region $AWS_REGION \
            --query 'RouteTables[?Routes[?GatewayId==`'$IGW_ID'`]].RouteTableId | [0]' \
            --output text 2>/dev/null || echo "")
        
        # Internet Gateway 라우팅 테이블이 없으면 서브넷에 연결
        if [ -z "$RTB_ID" ] || [ "$RTB_ID" = "None" ]; then
            # Internet Gateway 사용 라우팅 테이블 생성 또는 기존 것 사용
            RTB_ID="rtb-0e5f894769963979e"  # 이미 Internet Gateway 사용하는 라우팅 테이블
        fi
    fi
    
    if [ -n "$RTB_ID" ] && [ "$RTB_ID" != "None" ]; then
        SUBNET_RTBS[$SUBNET]=$RTB_ID
        echo "   ✅ 라우팅 테이블: $RTB_ID"
        
        # 현재 라우팅 확인
        CURRENT_GW=$(aws ec2 describe-route-tables \
            --route-table-ids $RTB_ID \
            --region $AWS_REGION \
            --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`].GatewayId' \
            --output text 2>/dev/null || echo "")
        
        if [[ "$CURRENT_GW" == *"igw-"* ]]; then
            echo "   ✅ Internet Gateway 사용 중"
        elif [[ "$CURRENT_GW" == *"nat-"* ]]; then
            echo "   ⚠️  NAT Gateway 사용 중: $CURRENT_GW"
        else
            echo "   ⚠️  기본 라우팅 없음"
        fi
    else
        echo "   ❌ 라우팅 테이블을 찾을 수 없음"
    fi
    echo ""
done

# 2. NAT Gateway를 사용하는 라우팅 테이블을 Internet Gateway로 변경
echo "🔧 라우팅 테이블 업데이트 중..."
echo ""

for SUBNET in "${SUBNETS[@]}"; do
    RTB_ID=${SUBNET_RTBS[$SUBNET]}
    
    if [ -z "$RTB_ID" ] || [ "$RTB_ID" = "None" ]; then
        echo "   ⏭️  $SUBNET: 라우팅 테이블 없음, 건너뜀"
        continue
    fi
    
    echo "   처리 중: $SUBNET (RTB: $RTB_ID)"
    
    # 현재 0.0.0.0/0 라우팅 확인
    CURRENT_ROUTE=$(aws ec2 describe-route-tables \
        --route-table-ids $RTB_ID \
        --region $AWS_REGION \
        --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`]' \
        --output json)
    
    CURRENT_GW=$(echo "$CURRENT_ROUTE" | jq -r '.[0].GatewayId // empty' 2>/dev/null || echo "")
    
    if [[ "$CURRENT_GW" == *"igw-"* ]]; then
        echo "   ✅ 이미 Internet Gateway 사용 중"
    elif [[ "$CURRENT_GW" == *"nat-"* ]]; then
        echo "   🔄 NAT Gateway → Internet Gateway 변경 중..."
        
        # 기존 NAT Gateway 라우팅 삭제
        aws ec2 delete-route \
            --route-table-id $RTB_ID \
            --destination-cidr-block 0.0.0.0/0 \
            --region $AWS_REGION 2>/dev/null || true
        
        # Internet Gateway 라우팅 추가
        aws ec2 create-route \
            --route-table-id $RTB_ID \
            --destination-cidr-block 0.0.0.0/0 \
            --gateway-id $IGW_ID \
            --region $AWS_REGION
        
        echo "   ✅ Internet Gateway로 변경 완료"
    else
        echo "   ➕ Internet Gateway 라우팅 추가 중..."
        
        # Internet Gateway 라우팅 추가
        aws ec2 create-route \
            --route-table-id $RTB_ID \
            --destination-cidr-block 0.0.0.0/0 \
            --gateway-id $IGW_ID \
            --region $AWS_REGION 2>/dev/null || true
        
        echo "   ✅ Internet Gateway 라우팅 추가 완료"
    fi
    echo ""
done

# 3. Compute Environment 업데이트 (모든 서브넷 사용 가능)
echo "🔨 Compute Environment 업데이트 중..."
echo ""

ALL_SUBNETS=$(IFS=','; echo "${SUBNETS[*]}")
SECURITY_GROUP="sg-0d09f4a3e612ae6d3"

# Job Queue 비활성화
echo "📋 Job Queue 비활성화 중..."
QUEUE_STATUS=$(aws batch describe-job-queues \
    --job-queues deep-agents-queue \
    --region $AWS_REGION \
    --query 'jobQueues[0].state' \
    --output text 2>/dev/null || echo "DISABLED")

if [ "$QUEUE_STATUS" = "ENABLED" ]; then
    aws batch update-job-queue \
        --job-queue-name deep-agents-queue \
        --state DISABLED \
        --region $AWS_REGION
    echo "   ⏳ Job Queue 비활성화 대기 중..."
    sleep 10
fi

# Compute Environment 업데이트
echo "   서브넷: $ALL_SUBNETS"
aws batch update-compute-environment \
    --compute-environment-name deep-agents-compute \
    --compute-resources "type=FARGATE,maxvCpus=16,subnets=$ALL_SUBNETS,securityGroupIds=$SECURITY_GROUP" \
    --region $AWS_REGION

echo "✅ Compute Environment 업데이트 완료"
echo "⏳ Compute Environment 활성화 대기 중..."

for i in {1..30}; do
    STATUS=$(aws batch describe-compute-environments \
        --compute-environments deep-agents-compute \
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

# 4. NAT Gateway 삭제 (비용 절감)
echo ""
echo "============================================================"
echo "💰 NAT Gateway 삭제 (비용 절감)"
echo "============================================================"
echo ""

echo "⚠️  NAT Gateway를 삭제하면 월 약 $32.40 비용이 절감됩니다"
echo "   삭제하시겠습니까? (y/N)"
read -r CONFIRM

if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
    echo "🗑️  NAT Gateway 삭제 중: $NAT_GW_ID"
    
    # NAT Gateway 삭제
    aws ec2 delete-nat-gateway \
        --nat-gateway-id $NAT_GW_ID \
        --region $AWS_REGION
    
    echo "✅ NAT Gateway 삭제 요청 완료"
    echo "   ⏳ NAT Gateway가 완전히 삭제될 때까지 몇 분 소요될 수 있습니다"
    echo "   삭제 상태 확인: aws ec2 describe-nat-gateways --nat-gateway-ids $NAT_GW_ID --region $AWS_REGION"
else
    echo "⏭️  NAT Gateway 삭제 취소됨"
    echo "   나중에 수동으로 삭제: aws ec2 delete-nat-gateway --nat-gateway-id $NAT_GW_ID --region $AWS_REGION"
fi

echo ""
echo "============================================================"
echo "✅ Public 서브넷 전환 완료!"
echo "============================================================"
echo ""
echo "📋 변경 사항:"
echo "   - 모든 서브넷이 Internet Gateway 사용"
echo "   - Compute Environment가 모든 서브넷 사용 가능"
echo "   - Fargate 태스크에 Public IP 자동 할당"
echo "   - NAT Gateway 삭제 (비용 절감)"
echo ""
echo "💡 다음 단계:"
echo "   테스트 Job 제출: ./scripts/submit-batch-job.sh USER_ID 'GIT_URLS' [TARGET_USER]"
echo ""


#!/bin/bash

# 네트워크 연결 문제 해결 스크립트
# Security Group 아웃바운드 규칙 확인 및 수정
# NAT Gateway 확인

set -e

echo "============================================================"
echo "🔧 네트워크 연결 문제 해결"
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

if [ "$VPC_ID" = "None" ] || [ -z "$VPC_ID" ]; then
    echo "❌ VPC를 찾을 수 없습니다"
    exit 1
fi

# Security Group 가져오기 (기본 SG)
SECURITY_GROUP=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=default" \
    --region $AWS_REGION \
    --query 'SecurityGroups[0].GroupId' \
    --output text)

echo "   Security Group: $SECURITY_GROUP"
echo ""

# 1. Security Group 아웃바운드 규칙 확인
echo "============================================================"
echo "📋 Step 1: Security Group 아웃바운드 규칙 확인"
echo "============================================================"
echo ""

OUTBOUND_RULES=$(aws ec2 describe-security-groups \
    --group-ids "$SECURITY_GROUP" \
    --region $AWS_REGION \
    --query 'SecurityGroups[0].IpPermissionsEgress' \
    --output json)

echo "현재 아웃바운드 규칙:"
echo "$OUTBOUND_RULES" | jq '.' || echo "$OUTBOUND_RULES"
echo ""

# HTTPS(443) 포트 허용 여부 확인
HTTPS_ALLOWED=$(echo "$OUTBOUND_RULES" | jq -r '.[] | select(.FromPort == 443 or (.FromPort == null and .IpProtocol == "-1")) | .FromPort' | head -1)

if [ -n "$HTTPS_ALLOWED" ] || echo "$OUTBOUND_RULES" | jq -e '.[] | select(.IpProtocol == "-1")' > /dev/null 2>&1; then
    echo "✅ HTTPS(443) 포트가 이미 허용되어 있습니다"
else
    echo "⚠️  HTTPS(443) 포트가 허용되지 않았습니다"
    echo ""
    read -p "HTTPS(443) 포트를 허용하는 아웃바운드 규칙을 추가하시겠습니까? (y/N): " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🔨 HTTPS(443) 아웃바운드 규칙 추가 중..."
        aws ec2 authorize-security-group-egress \
            --group-id "$SECURITY_GROUP" \
            --ip-permissions IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges='[{CidrIp=0.0.0.0/0,Description="Allow HTTPS to GitHub and external services"}]' \
            --region $AWS_REGION
        
        echo "✅ HTTPS(443) 아웃바운드 규칙 추가 완료"
    else
        echo "❌ 규칙 추가 취소됨"
    fi
fi

echo ""

# 2. NAT Gateway 확인
echo "============================================================"
echo "📋 Step 2: NAT Gateway 확인"
echo "============================================================"
echo ""

NAT_GATEWAYS=$(aws ec2 describe-nat-gateways \
    --filter "Name=vpc-id,Values=$VPC_ID" \
    --region $AWS_REGION \
    --query 'NatGateways[?State==`available`]' \
    --output json)

NAT_COUNT=$(echo "$NAT_GATEWAYS" | jq '. | length')

if [ "$NAT_COUNT" -gt 0 ]; then
    echo "✅ NAT Gateway가 $NAT_COUNT개 있습니다:"
    echo "$NAT_GATEWAYS" | jq -r '.[] | "   - \(.NatGatewayId) (Subnet: \(.SubnetId))"'
else
    echo "⚠️  NAT Gateway가 없습니다"
    echo ""
    echo "💡 NAT Gateway가 없으면 프라이빗 서브넷에서 인터넷으로 나갈 수 없습니다."
    echo "   GitHub.com에 접근하려면 다음 중 하나가 필요합니다:"
    echo "   1. NAT Gateway 생성 (권장)"
    echo "   2. 퍼블릭 서브넷 사용 (Compute Environment의 서브넷을 퍼블릭 서브넷으로 변경)"
    echo ""
    echo "   NAT Gateway 생성 방법:"
    echo "   - AWS 콘솔: VPC > NAT Gateways > Create NAT Gateway"
    echo "   - 또는 AWS CLI로 생성 가능"
fi

echo ""

# 3. 서브넷 확인
echo "============================================================"
echo "📋 Step 3: 서브넷 확인"
echo "============================================================"
echo ""

if [ -n "$AWS_SUBNET_IDS" ]; then
    SUBNETS=$(echo "$AWS_SUBNET_IDS" | tr ',' ' ')
    echo "   사용 중인 서브넷 (from .env): $SUBNETS"
else
    SUBNETS=$(aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --region $AWS_REGION \
        --query 'Subnets[*].SubnetId' \
        --output text)
    echo "   VPC의 모든 서브넷: $SUBNETS"
fi

echo ""
echo "서브넷 정보:"
for SUBNET_ID in $SUBNETS; do
    SUBNET_INFO=$(aws ec2 describe-subnets \
        --subnet-ids "$SUBNET_ID" \
        --region $AWS_REGION \
        --query 'Subnets[0]' \
        --output json)
    
    SUBNET_NAME=$(echo "$SUBNET_INFO" | jq -r '.Tags[]? | select(.Key=="Name") | .Value // "N/A"')
    IS_PUBLIC=$(echo "$SUBNET_INFO" | jq -r '.MapPublicIpOnLaunch // false')
    CIDR=$(echo "$SUBNET_INFO" | jq -r '.CidrBlock')
    
    if [ "$IS_PUBLIC" = "true" ]; then
        TYPE="퍼블릭"
    else
        TYPE="프라이빗"
    fi
    
    echo "   - $SUBNET_ID ($SUBNET_NAME)"
    echo "     Type: $TYPE"
    echo "     CIDR: $CIDR"
done

echo ""
echo "============================================================"
echo "✅ 네트워크 연결 확인 완료"
echo "============================================================"
echo ""
echo "💡 다음 단계:"
echo "   1. Security Group 아웃바운드 규칙이 HTTPS(443)를 허용하는지 확인"
echo "   2. 프라이빗 서브넷을 사용하는 경우 NAT Gateway가 있는지 확인"
echo "   3. 퍼블릭 서브넷을 사용하는 경우 인터넷 게이트웨이가 연결되어 있는지 확인"
echo ""


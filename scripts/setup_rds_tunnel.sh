#!/bin/bash
# RDS PostgreSQL SSH 터널링 설정 스크립트
# 용도: 포트 5432가 차단된 환경에서 RDS 접속

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}RDS PostgreSQL 터널링 설정${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""

# 환경 변수
RDS_ENDPOINT="sesami.chques8mawha.ap-northeast-2.rds.amazonaws.com"
RDS_PORT="5432"
LOCAL_PORT="5433"  # 로컬에서 사용할 포트 (5432 대신)

echo -e "${YELLOW}현재 상황:${NC}"
echo "  - 통신사에서 포트 5432 차단"
echo "  - RDS 인스턴스: $RDS_ENDPOINT"
echo "  - 해결책: SSH 터널링 또는 AWS SSM"
echo ""

# 방법 1: EC2가 있는 경우
echo -e "${GREEN}방법 1: EC2 Bastion Host를 통한 SSH 터널${NC}"
echo "----------------------------------------"
echo ""
echo "1. EC2 인스턴스 필요 (같은 VPC 또는 VPC 피어링)"
echo "2. EC2 보안 그룹에서 RDS 5432 포트 허용"
echo "3. 로컬에서 SSH 터널 생성:"
echo ""
echo -e "${YELLOW}ssh -i ~/.ssh/your-key.pem -L $LOCAL_PORT:$RDS_ENDPOINT:$RDS_PORT ec2-user@YOUR-EC2-IP -N${NC}"
echo ""
echo "4. 연결 테스트:"
echo ""
echo -e "${YELLOW}psql -h localhost -p $LOCAL_PORT -U sesami -d sesami${NC}"
echo ""
echo "또는 Python:"
cat << 'PYTHON_EXAMPLE'
```python
import psycopg2
conn = psycopg2.connect(
    host='localhost',
    port=5433,
    database='sesami',
    user='sesami',
    password='AsSeDIsPqOdQWE'
)
```
PYTHON_EXAMPLE
echo ""

# 방법 2: AWS Systems Manager
echo -e "${GREEN}방법 2: AWS Systems Manager (권장, EC2 불필요)${NC}"
echo "----------------------------------------"
echo ""
echo "1. VPC 내 EC2 인스턴스에 SSM Agent 설치"
echo "2. IAM 역할 부여: AmazonSSMManagedInstanceCore"
echo "3. Session Manager로 포트 포워딩:"
echo ""
echo -e "${YELLOW}aws ssm start-session \\${NC}"
echo -e "${YELLOW}  --target i-YOUR-INSTANCE-ID \\${NC}"
echo -e "${YELLOW}  --document-name AWS-StartPortForwardingSessionToRemoteHost \\${NC}"
echo -e "${YELLOW}  --parameters '{\"host\":[\"$RDS_ENDPOINT\"],\"portNumber\":[\"$RDS_PORT\"],\"localPortNumber\":[\"$LOCAL_PORT\"]}' \\${NC}"
echo -e "${YELLOW}  --region ap-northeast-2${NC}"
echo ""

# 방법 3: RDS Proxy (프로덕션 권장)
echo -e "${GREEN}방법 3: RDS Proxy 생성 (프로덕션 환경 권장)${NC}"
echo "----------------------------------------"
echo ""
echo "1. AWS Console → RDS → Proxies → Create proxy"
echo "2. Target: sesami 데이터베이스 선택"
echo "3. VPC 및 보안 그룹 설정"
echo "4. Secrets Manager에 자격증명 저장"
echo "5. Proxy 엔드포인트 사용 (다른 포트 매핑 가능)"
echo ""

# 방법 4: CloudFlare Tunnel (무료)
echo -e "${GREEN}방법 4: CloudFlare Tunnel (개발 환경용)${NC}"
echo "----------------------------------------"
echo ""
echo "1. CloudFlare 계정 생성 (무료)"
echo "2. cloudflared 설치"
echo "3. Tunnel 생성 및 RDS 연결"
echo "4. 로컬 포트로 접근"
echo ""

# 즉시 사용 가능한 임시 해결책
echo -e "${GREEN}방법 5: 다른 클라우드 VM 경유 (임시 해결책)${NC}"
echo "----------------------------------------"
echo ""
echo "1. Google Cloud / Azure / Oracle Cloud 무료 VM 생성"
echo "2. VM에서 SSH 터널 설정"
echo "3. VM이 AWS RDS로 연결 (클라우드 간 연결은 보통 허용됨)"
echo ""

echo ""
echo -e "${RED}⚠️  주의사항:${NC}"
echo "  - SSH 터널은 연결이 유지되는 동안만 작동"
echo "  - 백그라운드 실행: 명령어 뒤에 '&' 추가"
echo "  - 종료: fg 후 Ctrl+C 또는 kill 명령"
echo ""

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}추가 정보가 필요하면 문의하세요${NC}"
echo -e "${GREEN}======================================${NC}"

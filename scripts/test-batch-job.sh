#!/bin/bash

# 테스트 실행 스크립트
# 샘플 데이터로 AWS Batch Job을 제출하고 모니터링

set -e

# 종료 시 정리 함수
cleanup() {
    if [ -n "$LOG_TAIL_PID" ]; then
        kill $LOG_TAIL_PID 2>/dev/null || true
    fi
    exit 0
}

# 시그널 핸들러 등록
trap cleanup SIGINT SIGTERM

echo "============================================================"
echo "🧪 Deep Agents AWS Batch 테스트"
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

# AWS 설정
AWS_REGION="${S3_REGION:-ap-northeast-2}"
AWS_BEDROCK_REGION="${AWS_BEDROCK_REGION:-us-east-1}"

echo "📋 테스트 설정:"
echo "   AWS Region: $AWS_REGION (S3, ECR, Batch 등)"
echo "   Bedrock Region: $AWS_BEDROCK_REGION (Bedrock API)"
echo ""

# 테스트 데이터
TEST_USER_ID="00000000-0000-0000-0000-000000000001"
TEST_GIT_URL="git@github.com:smj53/david.git,git@github.com:alsksssass/david.git"
TEST_TARGET_USER=""

echo "🧪 테스트 Job 정보:"
echo "   User ID: $TEST_USER_ID (테스트용 UUID)"
echo "   Git URL: $TEST_GIT_URL"
echo "   Target User: ${TEST_TARGET_USER:-전체 유저}"
echo ""
echo "📋 환경 변수 확인:"
echo "   NEO4J_URI: ${NEO4J_URI:-bolt://172.31.41.218:7687}"
echo "   CHROMADB_HOST: ${CHROMADB_HOST:-172.31.41.218}"
echo ""

read -p "이 설정으로 테스트 Job을 제출하시겠습니까? (y/N): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 테스트 취소됨"
    exit 0
fi

echo ""
echo "============================================================"
echo "🚀 테스트 Job 제출"
echo "============================================================"
echo ""

# Job 제출
if [ -f "scripts/submit-batch-job.sh" ]; then
    JOB_OUTPUT=$(./scripts/submit-batch-job.sh "$TEST_USER_ID" "$TEST_GIT_URL" 2>&1)
    echo "$JOB_OUTPUT"
    
    # Job ID 추출
    JOB_ID=$(echo "$JOB_OUTPUT" | grep "Job ID:" | awk '{print $3}')
    
    if [ -z "$JOB_ID" ]; then
        echo "❌ Job ID를 찾을 수 없습니다"
        exit 1
    fi
    
    echo ""
    echo "============================================================"
    echo "📊 Job 모니터링 (실시간 로그 출력)"
    echo "============================================================"
    echo ""
    echo "💡 Ctrl+C를 눌러 종료할 수 있습니다"
    echo ""
    
    LOG_STREAM=""
    LOG_TAIL_PID=""
    LAST_TOKEN=""
    ITERATION=0
    
    # 무한 루프로 상태 및 로그 모니터링
    while true; do
        ITERATION=$((ITERATION + 1))
        
        # Job 상태 확인
        STATUS=$(aws batch describe-jobs \
            --jobs "$JOB_ID" \
            --region "$AWS_REGION" \
            --query 'jobs[0].status' \
            --output text 2>/dev/null || echo "UNKNOWN")
        
        # 로그 스트림 확인 (아직 없으면 계속 확인)
        if [ -z "$LOG_STREAM" ] || [ "$LOG_STREAM" = "None" ]; then
            LOG_STREAM=$(aws batch describe-jobs \
                --jobs "$JOB_ID" \
                --region "$AWS_REGION" \
                --query 'jobs[0].container.logStreamName' \
                --output text 2>/dev/null || echo "")
            
            if [ -n "$LOG_STREAM" ] && [ "$LOG_STREAM" != "None" ] && [ "$LOG_STREAM" != "" ]; then
                echo "============================================================"
                echo "📄 로그 스트림 발견: $LOG_STREAM"
                echo "============================================================"
                echo ""
                echo "실시간 로그 출력 시작..."
                echo ""
            fi
        fi
        
        # 로그 스트림이 있으면 로그 출력
        if [ -n "$LOG_STREAM" ] && [ "$LOG_STREAM" != "None" ] && [ "$LOG_STREAM" != "" ]; then
            # 로그 이벤트 가져오기 (한 번의 호출로 로그와 nextToken 모두 가져오기)
            if [ -z "$LAST_TOKEN" ]; then
                # 첫 로드: 모든 로그 가져오기
                LOG_RESPONSE=$(aws logs get-log-events \
                    --log-group-name /aws/batch/deep-agents \
                    --log-stream-name "$LOG_STREAM" \
                    --region "$AWS_REGION" \
                    --output json 2>/dev/null || echo "{}")
            else
                # 증분 로드: 새 로그만 가져오기
                LOG_RESPONSE=$(aws logs get-log-events \
                    --log-group-name /aws/batch/deep-agents \
                    --log-stream-name "$LOG_STREAM" \
                    --region "$AWS_REGION" \
                    --next-token "$LAST_TOKEN" \
                    --output json 2>/dev/null || echo "{}")
            fi
            
            # 로그 메시지 추출 및 출력 (jq가 있으면 사용, 없으면 query 사용)
            if command -v jq &> /dev/null; then
                LOG_OUTPUT=$(echo "$LOG_RESPONSE" | jq -r '.events[]?.message // empty' 2>/dev/null || echo "")
                NEW_TOKEN=$(echo "$LOG_RESPONSE" | jq -r '.nextToken // empty' 2>/dev/null || echo "")
            else
                # jq가 없으면 query 파라미터 사용
                if [ -z "$LAST_TOKEN" ]; then
                    LOG_OUTPUT=$(aws logs get-log-events \
                        --log-group-name /aws/batch/deep-agents \
                        --log-stream-name "$LOG_STREAM" \
                        --region "$AWS_REGION" \
                        --query 'events[*].message' \
                        --output text 2>/dev/null | sed 's/\t/\n/g' || echo "")
                    NEW_TOKEN=$(aws logs get-log-events \
                        --log-group-name /aws/batch/deep-agents \
                        --log-stream-name "$LOG_STREAM" \
                        --region "$AWS_REGION" \
                        --query 'nextToken' \
                        --output text 2>/dev/null || echo "")
                else
                    LOG_OUTPUT=$(aws logs get-log-events \
                        --log-group-name /aws/batch/deep-agents \
                        --log-stream-name "$LOG_STREAM" \
                        --region "$AWS_REGION" \
                        --next-token "$LAST_TOKEN" \
                        --query 'events[*].message' \
                        --output text 2>/dev/null | sed 's/\t/\n/g' || echo "")
                    NEW_TOKEN=$(aws logs get-log-events \
                        --log-group-name /aws/batch/deep-agents \
                        --log-stream-name "$LOG_STREAM" \
                        --region "$AWS_REGION" \
                        --next-token "$LAST_TOKEN" \
                        --query 'nextToken' \
                        --output text 2>/dev/null || echo "")
                fi
            fi
            
            if [ -n "$LOG_OUTPUT" ]; then
                echo "$LOG_OUTPUT"
            fi
            
            # nextToken 업데이트
            if [ -n "$NEW_TOKEN" ] && [ "$NEW_TOKEN" != "None" ]; then
                LAST_TOKEN="$NEW_TOKEN"
            fi
        else
            # 로그 스트림이 아직 없으면 상태만 표시
            if [ $((ITERATION % 6)) -eq 0 ]; then  # 12초마다 한 번만 표시
                echo "[$(date +%H:%M:%S)] Job 상태: $STATUS (로그 스트림 대기 중...)"
            fi
        fi
        
        # Job 상태에 따른 처리
        case "$STATUS" in
            SUCCEEDED)
                echo ""
                echo "============================================================"
                echo "✅ Job 성공!"
                echo "============================================================"
                echo ""
                echo "🌐 AWS 콘솔:"
                echo "   https://console.aws.amazon.com/batch/home?region=$AWS_REGION#jobs/detail/$JOB_ID"
                cleanup
                ;;
            FAILED)
                echo ""
                echo "============================================================"
                echo "❌ Job 실패"
                echo "============================================================"
                echo ""
                echo "📄 상세 정보:"
                aws batch describe-jobs \
                    --jobs "$JOB_ID" \
                    --region "$AWS_REGION" \
                    --query 'jobs[0].{Status:status,StatusReason:statusReason,Container:container}' \
                    --output json
                echo ""
                echo "🌐 AWS 콘솔:"
                echo "   https://console.aws.amazon.com/batch/home?region=$AWS_REGION#jobs/detail/$JOB_ID"
                cleanup
                exit 1
                ;;
        esac
        
        # 짧은 간격으로 폴링 (로그 실시간성 향상)
        sleep 2
    done
    
else
    echo "❌ submit-batch-job.sh를 찾을 수 없습니다"
    exit 1
fi

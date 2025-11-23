#!/bin/bash

# AWS Batch 완전 자동화 설정 스크립트
# .env 파일에서 설정을 읽어 AWS 리소스를 자동으로 생성합니다

set -e

echo "============================================================"
echo "🚀 AWS Batch 자동 설정"
echo "============================================================"
echo ""

# .env 파일 로드
if [ -f .env ]; then
    echo "📄 .env 파일 로드 중..."
    export $(grep -v '^#' .env | xargs)
    echo "✅ .env 파일 로드 완료"
else
    echo "❌ .env 파일을 찾을 수 없습니다"
    echo "   .env.example을 복사하여 .env 파일을 생성하세요"
    exit 1
fi

echo ""

# AWS 자격 증명 확인
echo "🔐 AWS 자격 증명 확인 중..."
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")

if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "❌ AWS 자격 증명이 설정되지 않았습니다"
    echo "   'aws configure' 명령어로 자격 증명을 설정하세요"
    exit 1
fi

echo "✅ AWS 계정 ID: $AWS_ACCOUNT_ID"
echo ""

# 환경 변수 설정
AWS_REGION="${S3_REGION:-ap-northeast-2}"
ECR_REPO_NAME="deep-agents"
ECR_REPOSITORY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"
IAM_ROLE_NAME="DeepAgentsBatchRole"
COMPUTE_ENV_NAME="deep-agents-compute"
JOB_QUEUE_NAME="deep-agents-queue"
JOB_DEFINITION_NAME="deep-agents-job"

echo "📋 설정 정보:"
echo "   AWS Region: $AWS_REGION"
echo "   ECR Repository: $ECR_REPOSITORY"
echo "   IAM Role: $IAM_ROLE_NAME"
echo "   Compute Environment: $COMPUTE_ENV_NAME"
echo "   Job Queue: $JOB_QUEUE_NAME"
echo ""

# 1. ECR 레포지토리 생성
echo "============================================================"
echo "📦 Step 1: ECR 레포지토리 생성"
echo "============================================================"

if aws ecr describe-repositories --repository-names $ECR_REPO_NAME --region $AWS_REGION >/dev/null 2>&1; then
    echo "ℹ️  ECR 레포지토리가 이미 존재합니다: $ECR_REPO_NAME"
else
    echo "🔨 ECR 레포지토리 생성 중..."
    aws ecr create-repository \
        --repository-name $ECR_REPO_NAME \
        --region $AWS_REGION \
        --image-scanning-configuration scanOnPush=true \
        --encryption-configuration encryptionType=AES256
    
    echo "✅ ECR 레포지토리 생성 완료"
fi

echo ""

# 2. IAM Role 생성
echo "============================================================"
echo "🔑 Step 2: IAM Role 생성"
echo "============================================================"

if aws iam get-role --role-name $IAM_ROLE_NAME >/dev/null 2>&1; then
    echo "ℹ️  IAM Role이 이미 존재합니다: $IAM_ROLE_NAME"
else
    echo "🔨 IAM Role 생성 중..."
    
    # Trust Policy 생성
    cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    # Role 생성
    aws iam create-role \
        --role-name $IAM_ROLE_NAME \
        --assume-role-policy-document file:///tmp/trust-policy.json \
        --description "Role for Deep Agents AWS Batch jobs"
    
    # 필수 정책 연결
    aws iam attach-role-policy \
        --role-name $IAM_ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
    
    aws iam attach-role-policy \
        --role-name $IAM_ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
    
    # Bedrock 정책 생성 및 연결
    cat > /tmp/bedrock-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "logs:CreateLogGroup"
      ],
      "Resource": "*"
    }
  ]
}
EOF

    BEDROCK_POLICY_ARN=$(aws iam create-policy \
        --policy-name DeepAgentsBedrockPolicy \
        --policy-document file:///tmp/bedrock-policy.json \
        --query 'Policy.Arn' \
        --output text 2>/dev/null || echo "")
    
    if [ -n "$BEDROCK_POLICY_ARN" ]; then
        aws iam attach-role-policy \
            --role-name $IAM_ROLE_NAME \
            --policy-arn $BEDROCK_POLICY_ARN
    else
        # 이미 존재하는 경우
        BEDROCK_POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/DeepAgentsBedrockPolicy"
        aws iam attach-role-policy \
            --role-name $IAM_ROLE_NAME \
            --policy-arn $BEDROCK_POLICY_ARN 2>/dev/null || true
    fi
    
    echo "✅ IAM Role 생성 완료"
    echo "   Role ARN: arn:aws:iam::${AWS_ACCOUNT_ID}:role/${IAM_ROLE_NAME}"
    
    # Role이 전파될 때까지 대기
    echo "⏳ IAM Role 전파 대기 중 (10초)..."
    sleep 10
fi

echo ""

# 3. Compute Environment 생성
echo "============================================================"
echo "💻 Step 3: Compute Environment 생성"
echo "============================================================"

if aws batch describe-compute-environments --compute-environments $COMPUTE_ENV_NAME --region $AWS_REGION --query 'computeEnvironments[0].computeEnvironmentName' --output text 2>/dev/null | grep -q "$COMPUTE_ENV_NAME"; then
    echo "ℹ️  Compute Environment가 이미 존재합니다: $COMPUTE_ENV_NAME"
else
    echo "🔍 VPC 및 서브넷 정보 가져오는 중..."
    
    # VPC ID 설정
    if [ -n "$AWS_VPC_ID" ]; then
        VPC_ID="$AWS_VPC_ID"
        echo "   VPC ID (from .env): $VPC_ID"
    else
        # 기본 VPC 가져오기
        VPC_ID=$(aws ec2 describe-vpcs \
            --filters "Name=isDefault,Values=true" \
            --region $AWS_REGION \
            --query 'Vpcs[0].VpcId' \
            --output text)
            
        echo "   VPC ID (auto-detected): $VPC_ID"
    fi
    
    if [ "$VPC_ID" = "None" ] || [ -z "$VPC_ID" ]; then
        echo "❌ VPC를 찾을 수 없습니다"
        echo "   .env 파일에 AWS_VPC_ID를 설정하거나 기본 VPC가 있는지 확인하세요"
        exit 1
    fi
    
    # 서브넷 설정
    if [ -n "$AWS_SUBNET_IDS" ]; then
        SUBNETS="$AWS_SUBNET_IDS"
        echo "   Subnets (from .env): $SUBNETS"
    else
        # VPC의 서브넷 가져오기 (쉼표로 구분)
        SUBNETS=$(aws ec2 describe-subnets \
            --filters "Name=vpc-id,Values=$VPC_ID" \
            --region $AWS_REGION \
            --query 'Subnets[*].SubnetId' \
            --output text | tr '\t' ',')
        echo "   Subnets (auto-detected): $SUBNETS"
    fi
    
    if [ -z "$SUBNETS" ]; then
        echo "❌ 서브넷을 찾을 수 없습니다"
        exit 1
    fi
    
    # Security Group 가져오기 (기본 SG)
    SECURITY_GROUP=$(aws ec2 describe-security-groups \
        --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=default" \
        --region $AWS_REGION \
        --query 'SecurityGroups[0].GroupId' \
        --output text)
    
    echo "   Security Group: $SECURITY_GROUP"
    
    echo "🔨 Compute Environment 생성 중..."
    aws batch create-compute-environment \
        --compute-environment-name $COMPUTE_ENV_NAME \
        --type MANAGED \
        --state ENABLED \
        --compute-resources "type=FARGATE,maxvCpus=16,subnets=$SUBNETS,securityGroupIds=$SECURITY_GROUP" \
        --region $AWS_REGION
    
    echo "✅ Compute Environment 생성 완료"
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
fi

echo ""

# 4. Job Queue 생성
echo "============================================================"
echo "📋 Step 4: Job Queue 생성"
echo "============================================================"

if aws batch describe-job-queues --job-queues $JOB_QUEUE_NAME --region $AWS_REGION --query 'jobQueues[0].jobQueueName' --output text 2>/dev/null | grep -q "$JOB_QUEUE_NAME"; then
    echo "ℹ️  Job Queue가 이미 존재합니다: $JOB_QUEUE_NAME"
else
    echo "🔨 Job Queue 생성 중..."
    aws batch create-job-queue \
        --job-queue-name $JOB_QUEUE_NAME \
        --state ENABLED \
        --priority 1 \
        --compute-environment-order order=1,computeEnvironment=$COMPUTE_ENV_NAME \
        --region $AWS_REGION
    
    echo "✅ Job Queue 생성 완료"
fi

echo ""

# 5. Job Definition 템플릿 생성
echo "============================================================"
echo "📝 Step 5: Job Definition 템플릿 생성"
echo "============================================================"

cat > aws-batch-job-definition.json <<EOF
{
  "jobDefinitionName": "$JOB_DEFINITION_NAME",
  "type": "container",
  "platformCapabilities": ["FARGATE"],
  "containerProperties": {
    "image": "$ECR_REPOSITORY:latest",
    "jobRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${IAM_ROLE_NAME}",
    "executionRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${IAM_ROLE_NAME}",
    "resourceRequirements": [
      {
        "type": "VCPU",
        "value": "4"
      },
      {
        "type": "MEMORY",
        "value": "16384"
      }
    ],
    "environment": [
      {
        "name": "AWS_DEFAULT_REGION",
        "value": "$AWS_REGION"
      },
      {
        "name": "AWS_REGION",
        "value": "${AWS_REGION:-ap-northeast-2}"
      },
      {
        "name": "AWS_BEDROCK_REGION",
        "value": "${AWS_BEDROCK_REGION:-us-east-1}"
      },
      {
        "name": "AWS_BEDROCK_MODEL_ID_SONNET",
        "value": "${AWS_BEDROCK_MODEL_ID_SONNET:-us.anthropic.claude-3-5-sonnet-20241022-v2:0}"
      },
      {
        "name": "AWS_BEDROCK_MODEL_ID_HAIKU",
        "value": "${AWS_BEDROCK_MODEL_ID_HAIKU:-us.anthropic.claude-3-haiku-20240307-v1:0}"
      },
      {
        "name": "STORAGE_BACKEND",
        "value": "${STORAGE_BACKEND:-s3}"
      },
      {
        "name": "S3_BUCKET_NAME",
        "value": "${S3_BUCKET_NAME:-amazon-sagemaker-712111072528-ap-northeast-2-ac414db573cc}"
      },
      {
        "name": "S3_REGION",
        "value": "${S3_REGION:-ap-northeast-2}"
      },
      {
        "name": "S3_LIFECYCLE_DAYS",
        "value": "${S3_LIFECYCLE_DAYS:-30}"
      },
      {
        "name": "LOCAL_DATA_DIR",
        "value": "${LOCAL_DATA_DIR:-./data}"
      },
      {
        "name": "GRAPH_DB_BACKEND",
        "value": "${GRAPH_DB_BACKEND:-neo4j}"
      },
      {
        "name": "NEO4J_URI",
        "value": "${NEO4J_URI:-bolt://172.31.41.218:7687}"
      },
      {
        "name": "NEO4J_USER",
        "value": "${NEO4J_USER:-neo4j}"
      },
      {
        "name": "NEO4J_PASSWORD",
        "value": "${NEO4J_PASSWORD:-password}"
      },
      {
        "name": "VECTOR_DB_BACKEND",
        "value": "${VECTOR_DB_BACKEND:-chromadb}"
      },
      {
        "name": "CHROMADB_HOST",
        "value": "${CHROMADB_HOST:-172.31.41.218}"
      },
      {
        "name": "CHROMADB_PORT",
        "value": "${CHROMADB_PORT:-8000}"
      },
      {
        "name": "CHROMADB_PERSIST_DIR",
        "value": "${CHROMADB_PERSIST_DIR:-./data/chroma_db}"
      },
      {
        "name": "CHROMADB_AUTH_TOKEN",
        "value": "${CHROMADB_AUTH_TOKEN:-}"
      },
      {
        "name": "TOKENIZERS_PARALLELISM",
        "value": "${TOKENIZERS_PARALLELISM:-false}"
      },
      {
        "name": "ENABLE_DEBUG_LOGGING",
        "value": "${ENABLE_DEBUG_LOGGING:-true}"
      },
      {
        "name": "ENABLE_SUBAGENT_DEBUG_LOGGING",
        "value": "${ENABLE_SUBAGENT_DEBUG_LOGGING:-true}"
      },
      {
        "name": "POSTGRES_HOST",
        "value": "${POSTGRES_HOST:-sesami.chques8mawha.ap-northeast-2.rds.amazonaws.com}"
      },
      {
        "name": "POSTGRES_PORT",
        "value": "${POSTGRES_PORT:-5432}"
      },
      {
        "name": "POSTGRES_DB",
        "value": "${POSTGRES_DB:-sesami}"
      },
      {
        "name": "POSTGRES_USER",
        "value": "${POSTGRES_USER:-sesami}"
      },
      {
        "name": "POSTGRES_PASSWORD",
        "value": "${POSTGRES_PASSWORD:-AsSeDIsPqOdQWE}"
      },
      {
        "name": "POSTGRES_ECHO",
        "value": "${POSTGRES_ECHO:-false}"
      },
      {
        "name": "DATA_DIR",
        "value": "${DATA_DIR:-/app/data}"
      },
      {
        "name": "LOG_LEVEL",
        "value": "${LOG_LEVEL:-INFO}"
      },
      {
        "name": "PYTHONUNBUFFERED",
        "value": "${PYTHONUNBUFFERED:-1}"
      }
    ],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/aws/batch/deep-agents",
        "awslogs-region": "$AWS_REGION",
        "awslogs-stream-prefix": "deep-agents",
        "awslogs-create-group": "true"
      }
    }
  }
}
EOF

echo "✅ Job Definition 템플릿 생성 완료: aws-batch-job-definition.json"

echo ""
echo "============================================================"
echo "✅ AWS Batch 설정 완료!"
echo "============================================================"
echo ""
echo "📋 생성된 리소스:"
echo "   ECR Repository: $ECR_REPOSITORY"
echo "   IAM Role: arn:aws:iam::${AWS_ACCOUNT_ID}:role/${IAM_ROLE_NAME}"
echo "   Compute Environment: $COMPUTE_ENV_NAME"
echo "   Job Queue: $JOB_QUEUE_NAME"
echo "   Job Definition Template: aws-batch-job-definition.json"
echo ""
echo "💡 다음 단계:"
echo "   1. Docker 이미지 빌드 및 ECR 푸시:"
echo "      export ECR_REPOSITORY=$ECR_REPOSITORY"
echo "      ./docker-build.sh"
echo ""
echo "   2. Job Definition 등록:"
echo "      ./register-job-definition.sh"
echo ""
echo "   3. Job 제출:"
echo "      ./submit-batch-job.sh USER_ID 'GIT_URLS' [TARGET_USER]"
echo ""

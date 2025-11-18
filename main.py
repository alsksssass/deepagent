"""
Deep Agents Code Analysis - Main Entry Point

LangChain Deep Agents 기반 Git 코드 분석 시스템
"""

import asyncio
import logging
import sys
from pathlib import Path
from argparse import ArgumentParser
from dotenv import load_dotenv
import os

from langchain_aws import ChatBedrockConverse

from core.orchestrator.orchestrator import DeepAgentOrchestrator
from core.state import AgentState

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/deep_agents.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)


def load_environment():
    """
    환경 변수 로드 및 검증
    """
    load_dotenv()

    # TOKENIZERS_PARALLELISM 설정 (fork 경고 방지)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    logger.debug(f"🔧 TOKENIZERS_PARALLELISM={os.getenv('TOKENIZERS_PARALLELISM')}")

    required_vars = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_BEDROCK_MODEL_ID_SONNET",
        "AWS_BEDROCK_MODEL_ID_HAIKU",
    ]

    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        logger.error(f"❌ 필수 환경 변수 누락: {', '.join(missing_vars)}")
        logger.error("   .env 파일을 확인하세요 (.env.example 참고)")
        sys.exit(1)

    logger.info("✅ 환경 변수 로드 완료")


def create_llms() -> tuple[ChatBedrockConverse, ChatBedrockConverse]:
    """
    AWS Bedrock LLM 인스턴스 생성

    Returns:
        (sonnet_llm, haiku_llm)
    """
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    sonnet_model_id = os.getenv("AWS_BEDROCK_MODEL_ID_SONNET")
    haiku_model_id = os.getenv("AWS_BEDROCK_MODEL_ID_HAIKU")

    logger.info(f"🤖 LLM 초기화")
    logger.info(f"   Region: {region}")
    logger.info(f"   Sonnet: {sonnet_model_id}")
    logger.info(f"   Haiku: {haiku_model_id}")

    sonnet_llm = ChatBedrockConverse(
        model=sonnet_model_id,
        region_name=region,
        temperature=0.0,
        max_tokens=4096,
    )

    haiku_llm = ChatBedrockConverse(
        model=haiku_model_id,
        region_name=region,
        temperature=0.0,
        max_tokens=4096,
    )

    return sonnet_llm, haiku_llm


async def main_async(args):
    """
    비동기 메인 함수
    """
    logger.info("=" * 60)
    logger.info("🚀 Deep Agents Code Analysis")
    logger.info("=" * 60)

    # 환경 변수 로드
    load_environment()

    # LLM 생성
    sonnet_llm, haiku_llm = create_llms()

    # 데이터 디렉토리 설정
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    # Skill Charts 경로 설정 (프로젝트 루트 기준)
    skill_charts_path = os.getenv("SKILL_CHARTS_PATH")
    if not skill_charts_path:
        # 프로젝트 루트 기준으로 찾기
        project_root = Path(__file__).parent
        skill_charts_path = str(project_root / "skill_charts.csv")
        if not Path(skill_charts_path).exists():
            logger.warning(f"⚠️ Skill Charts 파일 없음: {skill_charts_path}")

    # Neo4j 설정
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    # Orchestrator 생성
    orchestrator = DeepAgentOrchestrator(
        sonnet_llm=sonnet_llm,
        haiku_llm=haiku_llm,
        data_dir=data_dir,
        skill_charts_path=skill_charts_path,
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
    )

    # 분석 실행
    final_state = await orchestrator.run(
        git_url=args.git_url,
        target_user=args.target_user,
    )

    # 결과 출력
    logger.info("=" * 60)
    logger.info("📊 분석 완료")
    logger.info("=" * 60)

    if final_state.get("error_message"):
        logger.error(f"❌ 에러: {final_state['error_message']}")
        sys.exit(1)
    else:
        logger.info(f"✅ 작업 UUID: {final_state['task_uuid']}")
        logger.info(f"📂 기본 경로: {final_state['base_path']}")

        if final_state.get("final_report_path"):
            logger.info(f"📄 최종 리포트: {final_state['final_report_path']}")

        if final_state.get("todo_list"):
            logger.info(f"📋 실행된 작업 수: {len(final_state['todo_list'])}")

    logger.info("=" * 60)


def main():
    """
    동기 메인 함수 (CLI 진입점)
    """
    parser = ArgumentParser(description="Deep Agents Code Analysis")

    parser.add_argument(
        "--git-url",
        type=str,
        required=True,
        help="분석할 Git 레포지토리 URL (예: https://github.com/user/repo.git)",
    )

    parser.add_argument(
        "--target-user",
        type=str,
        default=None,
        help="분석 대상 특정 유저 이메일 (예: user@example.com). 미지정 시 전체 유저 분석",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨 설정",
    )

    args = parser.parse_args()

    # 로그 레벨 설정
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # 로그 디렉토리 생성
    Path("logs").mkdir(exist_ok=True)

    # 비동기 실행
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        logger.info("\n⚠️  사용자에 의해 중단됨")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"❌ 예외 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

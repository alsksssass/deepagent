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
import uuid

from langchain_aws import ChatBedrockConverse

from core.orchestrator.orchestrator import DeepAgentOrchestrator
from core.state import AgentState
from agents.repo_synthesizer import RepoSynthesizerAgent, RepoSynthesizerContext
from shared.storage import ResultStore

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
    # Bedrock은 us-east-1 리전 사용 (모델 지원이 가장 많음)
    bedrock_region = os.getenv("AWS_BEDROCK_REGION", "us-east-1")
    sonnet_model_id = os.getenv("AWS_BEDROCK_MODEL_ID_SONNET")
    haiku_model_id = os.getenv("AWS_BEDROCK_MODEL_ID_HAIKU")

    logger.info(f"🤖 LLM 초기화")
    logger.info(f"   Bedrock Region: {bedrock_region}")
    logger.info(f"   Sonnet: {sonnet_model_id}")
    logger.info(f"   Haiku: {haiku_model_id}")

    sonnet_llm = ChatBedrockConverse(
        model=sonnet_model_id,
        region_name=bedrock_region,
        temperature=0.0,
        max_tokens=4096,
        # timeout 파라미터는 Bedrock Converse API에서 지원하지 않음
    )

    haiku_llm = ChatBedrockConverse(
        model=haiku_model_id,
        region_name=bedrock_region,
        temperature=0.0,
        max_tokens=4096,
        # timeout 파라미터는 Bedrock Converse API에서 지원하지 않음
    )

    return sonnet_llm, haiku_llm


async def analyze_multiple_repos(
    orchestrator: DeepAgentOrchestrator,
    git_urls: list[str],
    target_user: str | None,
    data_dir: Path,
) -> dict:
    """
    여러 레포지토리 분석 + 종합 (옵션 1: 최상위 레벨 반복)

    Args:
        orchestrator: DeepAgentOrchestrator 인스턴스
        git_urls: Git 레포지토리 URL 리스트
        target_user: 특정 유저 이메일
        data_dir: 데이터 디렉토리

    Returns:
        종합 결과 딕셔너리
    """
    logger.info("=" * 60)
    is_single = len(git_urls) == 1
    logger.info(f"🚀 {'Single' if is_single else 'Multi'}-Repository Analysis")
    logger.info("=" * 60)
    logger.info(f"   레포지토리 수: {len(git_urls)}개")
    logger.info(f"   Target User: {target_user if target_user else '전체 유저'}")
    logger.info("")

    # 메인 task UUID 생성 (종합 결과용)
    import uuid
    from shared.storage import create_storage_backend
    from shared.config import settings
    
    main_task_uuid = str(uuid.uuid4())
    
    # shared/storage를 통해 메인 경로 생성
    if settings.STORAGE_BACKEND.value == "local":
        main_base_path = data_dir / "analyze_multi" / main_task_uuid
        main_base_path.mkdir(parents=True, exist_ok=True)
    else:  # S3
        # S3 환경: 문자열 경로만 관리
        main_base_path = f"analyze_multi/{main_task_uuid}"

    logger.info(f"📂 종합 결과 경로: {main_base_path}")
    logger.info("")

    # 1. 각 레포지토리 병렬 분석 (각각 setup → plan → execute → finalize)
    logger.info(f"📦 {len(git_urls)}개 레포지토리 병렬 분석 시작...")
    logger.info("")

    # 멀티 분석 모드: 각 레포 결과를 analyze_multi/{main_task_uuid}/repos/{repo_task_uuid}/에 저장
    repo_results = await asyncio.gather(
        *[
            orchestrator.run(
                git_url, 
                target_user,
                main_task_uuid=main_task_uuid,
                main_base_path=main_base_path
            ) 
            for git_url in git_urls
        ],
        return_exceptions=True
    )

    # 결과 정리
    successful_results = []
    failed_results = []

    for i, result in enumerate(repo_results):
        git_url = git_urls[i]

        if isinstance(result, Exception):
            logger.error(f"❌ {git_url}: {result}")
            failed_results.append({
                "git_url": git_url,
                "error_message": str(result),
            })
        else:
            if result.get("error_message"):
                logger.error(f"❌ {git_url}: {result.get('error_message')}")
                failed_results.append({
                    "git_url": git_url,
                    "error_message": result.get("error_message"),
                })
            else:
                logger.info(f"✅ {git_url}: 분석 완료")
                successful_results.append(result)

    logger.info("")
    logger.info(f"📊 레포지토리 분석 완료: 성공 {len(successful_results)}개, 실패 {len(failed_results)}개")
    logger.info("")

    # 2. 종합 agent 실행
    if successful_results:
        logger.info("🔬 종합 분석 시작...")

        synthesizer = RepoSynthesizerAgent()
        synthesis_context = RepoSynthesizerContext(
            task_uuid=main_task_uuid,
            main_task_uuid=main_task_uuid,
            main_base_path=str(main_base_path),
            repo_results=successful_results,
            target_user=target_user,
        )

        synthesis_response = await synthesizer.run(synthesis_context)

        logger.info("✅ 종합 분석 완료")
        logger.info(f"   종합 리포트: {synthesis_response.synthesis_report_path}")

        store = ResultStore(main_task_uuid, main_base_path)
        store.save_result("repo_synthesizer", synthesis_response)

        # 종합 분석 결과 DB 저장
        if orchestrator.db_writer and orchestrator.user_id:
            try:
                from shared.graph_db import AnalysisStatus
                import uuid as uuid_module

                # 대표 레포지토리 URL (첫 번째 성공한 레포)
                representative_url = (
                    successful_results[0].get("git_url") 
                    if successful_results and successful_results[0].get("git_url")
                    else git_urls[0]
                )

                await orchestrator.db_writer.save_final_analysis(
                    user_id=orchestrator.user_id,
                    repository_url=representative_url,
                    result=synthesis_response.model_dump(),  # RepoSynthesizerResponse
                    main_task_uuid=uuid_module.UUID(main_task_uuid),
                    status=AnalysisStatus.COMPLETED,
                    error_message=None
                )
                logger.info(f"📊 종합 분석 결과 DB 저장 완료: {main_task_uuid}")
            except Exception as e:
                logger.warning(f"⚠️ 종합 분석 결과 DB 저장 실패: {e}")

        return {
            "main_task_uuid": main_task_uuid,
            "main_base_path": str(main_base_path),
            "total_repos": len(git_urls),
            "successful_repos": len(successful_results),
            "failed_repos": len(failed_results),
            "repo_results": successful_results,
            "failed_results": failed_results,
            "synthesis": synthesis_response.model_dump(),
        }
    else:
        logger.error("❌ 분석 성공한 레포지토리가 없습니다.")
        return {
            "main_task_uuid": main_task_uuid,
            "main_base_path": str(main_base_path),
            "total_repos": len(git_urls),
            "successful_repos": 0,
            "failed_repos": len(failed_results),
            "failed_results": failed_results,
            "error_message": "모든 레포지토리 분석 실패",
        }


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

    # Neo4j 설정 (Settings를 통해 동적 IP 설정 적용)
    from shared.config import settings
    neo4j_uri = os.getenv("NEO4J_URI") or settings.NEO4J_URI
    neo4j_user = os.getenv("NEO4J_USER", settings.NEO4J_USER)
    neo4j_password = os.getenv("NEO4J_PASSWORD", settings.NEO4J_PASSWORD)

    # Orchestrator 생성
    orchestrator = DeepAgentOrchestrator(
        sonnet_llm=sonnet_llm,
        haiku_llm=haiku_llm,
        data_dir=data_dir,
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
    )

    # 단일/다중 레포 처리 (모두 종합 결과 생성)
    git_urls = args.git_urls if hasattr(args, 'git_urls') and args.git_urls else [args.git_url]

    # 모든 경우에 analyze_multiple_repos 사용 (1개든 N개든 동일하게 처리)
    final_result = await analyze_multiple_repos(
        orchestrator=orchestrator,
        git_urls=git_urls,
        target_user=args.target_user,
        data_dir=data_dir,
    )

    # 결과 출력
    logger.info("=" * 60)
    logger.info(f"📊 {'Single' if len(git_urls) == 1 else 'Multi'}-Repository 분석 완료")
    logger.info("=" * 60)

    if final_result.get("error_message"):
        logger.error(f"❌ 에러: {final_result['error_message']}")
        sys.exit(1)
    else:
        logger.info(f"✅ 메인 Task UUID: {final_result['main_task_uuid']}")
        logger.info(f"📂 종합 결과 경로: {final_result['main_base_path']}")
        logger.info(f"📦 레포지토리: 성공 {final_result['successful_repos']}개 / 실패 {final_result['failed_repos']}개")

        if final_result.get("synthesis"):
            synthesis = final_result["synthesis"]
            logger.info(f"📊 총 커밋: {synthesis.get('total_commits', 0):,}개")
            logger.info(f"📊 총 파일: {synthesis.get('total_files', 0):,}개")
            logger.info(f"📄 종합 리포트: {synthesis.get('synthesis_report_path')}")

    logger.info("=" * 60)


async def main_batch_mode():
    """
    AWS Batch 모드 메인 함수

    환경 변수에서 설정을 읽어 단일/다중 레포지토리 분석 실행
    - USER_ID: 사용자 UUID (필수)
    - GIT_URLS: Git 레포지토리 URL (필수, 쉼표 구분으로 다중 레포 지원)
      예: "https://github.com/user/repo1" (단일)
      예: "https://github.com/user/repo1,https://github.com/user/repo2" (다중)
    - TARGET_USER: 특정 유저 이메일 (옵셔널)
    """
    logger.info("==" * 30)
    logger.info("🚀 Deep Agents Batch Mode")
    logger.info("==" * 30)

    # 환경 변수 로드
    load_environment()

    # 필수 환경 변수 검증
    user_id_str = os.getenv("USER_ID")
    git_urls_str = os.getenv("GIT_URLS")

    if not user_id_str:
        logger.error("❌ USER_ID 환경 변수가 설정되지 않았습니다")
        sys.exit(1)

    if not git_urls_str:
        logger.error("❌ GIT_URLS 환경 변수가 설정되지 않았습니다")
        sys.exit(1)

    # UUID 변환
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError as e:
        logger.error(f"❌ USER_ID 형식이 올바르지 않습니다: {user_id_str}")
        sys.exit(1)

    # Git URLs 파싱 (쉼표로 구분)
    git_urls = [url.strip() for url in git_urls_str.split(",") if url.strip()]

    if not git_urls:
        logger.error("❌ GIT_URLS가 비어있습니다")
        sys.exit(1)

    # 옵셔널 환경 변수
    target_user = os.getenv("TARGET_USER")
    is_multi_repo = len(git_urls) > 1

    logger.info(f"📋 Batch 설정:")
    logger.info(f"   USER_ID: {user_id}")
    logger.info(f"   모드: {'다중 레포지토리' if is_multi_repo else '단일 레포지토리'}")
    logger.info(f"   레포지토리 수: {len(git_urls)}개")
    for i, url in enumerate(git_urls, 1):
        logger.info(f"   [{i}] {url}")
    logger.info(f"   TARGET_USER: {target_user if target_user else '전체 유저'}")
    logger.info("")

    # LLM 생성
    sonnet_llm, haiku_llm = create_llms()

    # 데이터 디렉토리 설정
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    # Neo4j 설정 (Settings를 통해 동적 IP 설정 적용)
    from shared.config import settings
    neo4j_uri = os.getenv("NEO4J_URI") or settings.NEO4J_URI
    neo4j_user = os.getenv("NEO4J_USER", settings.NEO4J_USER)
    neo4j_password = os.getenv("NEO4J_PASSWORD", settings.NEO4J_PASSWORD)

    # AnalysisDBWriter 초기화
    logger.info("🔧 AnalysisDBWriter 초기화 중...")
    try:
        from shared.graph_db import AnalysisDBWriter

        db_writer = await AnalysisDBWriter.initialize(
            echo=False,
            create_tables=False  # 프로덕션에서는 테이블이 이미 존재
        )
        logger.info("✅ DB Writer 초기화 완료\n")
    except Exception as e:
        logger.error(f"❌ DB Writer 초기화 실패: {e}")
        sys.exit(1)

    # Orchestrator 생성 (DB Writer 포함)
    orchestrator = DeepAgentOrchestrator(
        sonnet_llm=sonnet_llm,
        haiku_llm=haiku_llm,
        data_dir=data_dir,
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        user_id=user_id,
        db_writer=db_writer,
    )

    # 단일/다중 레포지토리 분석 실행 (모두 analyze_multiple_repos로 통합)
    try:
        logger.info(f"🚀 레포지토리 분석 시작: {len(git_urls)}개")
        final_result = await analyze_multiple_repos(
            orchestrator=orchestrator,
            git_urls=git_urls,
            target_user=target_user,
            data_dir=data_dir,
        )

        # 결과 출력
        logger.info("==" * 30)
        logger.info("📊 Batch 분석 완료")
        logger.info("==" * 30)

        if final_result.get("error_message"):
            logger.error(f"❌ 에러: {final_result['error_message']}")
            sys.exit(1)
        else:
            # 통합된 결과 출력 (단일/다중 모두 동일한 형식)
            logger.info(f"✅ Main Task UUID: {final_result.get('main_task_uuid')}")
            logger.info(f"📂 Main Base Path: {final_result.get('main_base_path')}")
            logger.info(f"📦 성공: {final_result.get('successful_repos', 0)}개 / 실패: {final_result.get('failed_repos', 0)}개")
            if final_result.get("synthesis"):
                synthesis = final_result["synthesis"]
                logger.info(f"📊 총 커밋: {synthesis.get('total_commits', 0):,}개")
                logger.info(f"📊 총 파일: {synthesis.get('total_files', 0):,}개")
            logger.info("==" * 30)

            # 성공 완료 시 명시적 종료
            logger.info("✅ Batch 작업 정상 완료")
            sys.exit(0)

    except Exception as e:
        logger.exception(f"❌ Batch 실행 중 예외 발생: {e}")
        sys.exit(1)

    finally:
        # DB Writer 종료
        await AnalysisDBWriter.close()


def main():
    """
    동기 메인 함수 (CLI 진입점)
    """
    parser = ArgumentParser(description="Deep Agents Code Analysis")

    # Batch 모드 플래그 추가
    parser.add_argument(
        "--batch-mode",
        action="store_true",
        help="AWS Batch 모드로 실행 (환경 변수에서 설정 읽기)",
    )

    # 단일 레포 또는 다중 레포 지원 (상호 배타적, batch-mode가 아닐 때만 필수)
    repo_group = parser.add_mutually_exclusive_group(required=False)
    repo_group.add_argument(
        "--git-url",
        type=str,
        help="분석할 단일 Git 레포지토리 URL (예: https://github.com/user/repo.git)",
    )
    repo_group.add_argument(
        "--git-urls",
        type=str,
        nargs="+",
        help="분석할 여러 Git 레포지토리 URL (공백으로 구분, 예: https://github.com/user/repo1.git https://github.com/user/repo2.git)",
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

    # Batch 모드 분기
    if args.batch_mode:
        logger.info("🔄 Batch 모드로 실행")
        try:
            asyncio.run(main_batch_mode())
        except KeyboardInterrupt:
            logger.info("\n⚠️  사용자에 의해 중단됨")
            sys.exit(0)
        except Exception as e:
            logger.exception(f"❌ Batch 모드 예외 발생: {e}")
            sys.exit(1)
    else:
        # 일반 모드에서는 git-url 또는 git-urls가 필수
        if not args.git_url and not args.git_urls:
            parser.error("--git-url 또는 --git-urls 중 하나는 필수입니다 (--batch-mode가 아닌 경우)")

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

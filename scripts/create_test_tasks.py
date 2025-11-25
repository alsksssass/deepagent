#!/usr/bin/env python3
"""
테스트용 Task ID 생성 및 DB 레코드 생성 스크립트

각 레포 분석용 RepositoryAnalysis와 메인 분석용 Analysis 레코드를 PROCESSING 상태로 생성
"""

import os
import sys
import uuid
import asyncio
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# .env 로드 (선택적)
try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    # dotenv가 없으면 .env 파일을 직접 읽기
    env_file = project_root / ".env"
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

from shared.graph_db import AnalysisDBWriter, AnalysisStatus


async def create_test_tasks(user_id: str, git_urls: list[str], main_task_id: str | None = None) -> tuple[list[str], str]:
    """
    테스트용 Task ID 생성 및 DB 레코드 생성
    
    Args:
        user_id: 사용자 UUID (문자열)
        git_urls: Git 레포지토리 URL 리스트
        main_task_id: 메인 task ID (None이면 자동 생성)
    
    Returns:
        (task_ids 리스트, main_task_id)
    """
    # DB Writer 초기화
    print("🔌 DB 연결 중...")
    try:
        db_writer = await AnalysisDBWriter.initialize(
            echo=False,
            create_tables=False
        )
        print("✅ DB 연결 완료")
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        sys.exit(1)
    
    try:
        user_id_obj = uuid.UUID(user_id)
    except ValueError:
        print(f"❌ 잘못된 USER_ID 형식: {user_id}")
        sys.exit(1)
    
    # MAIN_TASK_ID 생성 (없으면)
    if not main_task_id:
        main_task_id = str(uuid.uuid4())
    main_task_uuid_obj = uuid.UUID(main_task_id)
    
    # 각 레포별 TASK_ID 생성
    task_ids = []
    for git_url in git_urls:
        task_id = str(uuid.uuid4())
        task_ids.append(task_id)
        task_uuid_obj = uuid.UUID(task_id)
        
        # RepositoryAnalysis 레코드 생성 (PROCESSING 상태)
        try:
            await db_writer.save_repository_analysis(
                user_id=user_id_obj,
                repository_url=git_url,
                result={},  # 빈 결과
                task_uuid=task_uuid_obj,
                main_task_uuid=main_task_uuid_obj,
                status=AnalysisStatus.PROCESSING,
                error_message=None
            )
            print(f"✅ 레포 분석 레코드 생성: {task_id} ({git_url})")
        except Exception as e:
            print(f"⚠️  레포 분석 레코드 생성 실패 (이미 존재할 수 있음): {task_id} - {e}")
    
    # Analysis 레코드 생성 (PROCESSING 상태)
    # 대표 레포지토리 URL (첫 번째 레포)
    representative_url = git_urls[0] if git_urls else ""
    
    try:
        await db_writer.save_final_analysis(
            user_id=user_id_obj,
            repository_url=representative_url,
            result={},  # 빈 결과
            main_task_uuid=main_task_uuid_obj,
            status=AnalysisStatus.PROCESSING,
            error_message=None
        )
        print(f"✅ 메인 분석 레코드 생성: {main_task_id}")
    except Exception as e:
        print(f"⚠️  메인 분석 레코드 생성 실패 (이미 존재할 수 있음): {main_task_id} - {e}")
    
    # DB Writer 종료
    await AnalysisDBWriter.close()
    
    return task_ids, main_task_id


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="테스트용 Task ID 생성 및 DB 레코드 생성")
    parser.add_argument("--user-id", required=True, help="사용자 UUID")
    parser.add_argument("--git-urls", required=True, help="Git 레포지토리 URL (쉼표 구분)")
    parser.add_argument("--main-task-id", help="메인 task ID (없으면 자동 생성)")
    parser.add_argument("--export", action="store_true", help="환경변수 export 형식으로 출력")
    
    args = parser.parse_args()
    
    # Git URLs 파싱
    git_urls = [url.strip() for url in args.git_urls.split(",") if url.strip()]
    
    if not git_urls:
        print("❌ GIT_URLS가 비어있습니다")
        sys.exit(1)
    
    print("=" * 60)
    print("🧪 테스트용 Task 생성 및 DB 레코드 생성")
    print("=" * 60)
    print(f"   USER_ID: {args.user_id}")
    print(f"   GIT_URLS: {len(git_urls)}개")
    for i, url in enumerate(git_urls, 1):
        print(f"      [{i}] {url}")
    print()
    
    # 비동기 실행
    task_ids, main_task_id = asyncio.run(
        create_test_tasks(args.user_id, git_urls, args.main_task_id)
    )
    
    print()
    print("=" * 60)
    print("✅ 생성 완료")
    print("=" * 60)
    print(f"   MAIN_TASK_ID: {main_task_id}")
    print(f"   TASK_IDS: {len(task_ids)}개")
    for i, task_id in enumerate(task_ids, 1):
        print(f"      [{i}] {task_id}")
    print()
    
    # Export 형식으로 출력
    if args.export:
        print("# 환경변수 export:")
        print(f"export MAIN_TASK_ID='{main_task_id}'")
        print(f"export TASK_IDS='{','.join(task_ids)}'")
    else:
        print("💡 환경변수로 사용하려면 --export 옵션을 사용하세요:")
        print(f"   export MAIN_TASK_ID='{main_task_id}'")
        print(f"   export TASK_IDS='{','.join(task_ids)}'")


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""
AWS Batch 작업 로그 가져오기 스크립트

Usage:
    # Job ID로 로그 가져오기
    python scripts/fetch_batch_logs.py --job-id 35eaf1c8-99c7-4602-b8b8-635c1140338e

    # Log stream name으로 직접 가져오기
    python scripts/fetch_batch_logs.py --log-stream deep-agents/default/0a89ffc969184b39b1425ff883757e16

    # 출력 파일 지정
    python scripts/fetch_batch_logs.py --job-id <JOB_ID> --output logs/batch_job.log

    # 최근 N개 이벤트만 가져오기
    python scripts/fetch_batch_logs.py --job-id <JOB_ID> --limit 500

    # 특정 키워드 필터링
    python scripts/fetch_batch_logs.py --job-id <JOB_ID> --filter "validation errors"
"""

import argparse
import json
import sys
import re
from datetime import datetime
from pathlib import Path
import subprocess


def run_aws_command(cmd: list) -> dict:
    """AWS CLI 명령 실행"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout) if result.stdout else {}
    except subprocess.CalledProcessError as e:
        print(f"❌ AWS CLI 명령 실패: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ JSON 파싱 실패: {e}", file=sys.stderr)
        sys.exit(1)


def get_log_stream_from_job_id(job_id: str, region: str) -> tuple[str, str]:
    """Job ID로부터 log stream name과 status 가져오기"""
    print(f"🔍 Job ID로 로그 스트림 조회 중: {job_id}")

    cmd = [
        "aws", "batch", "describe-jobs",
        "--jobs", job_id,
        "--region", region,
        "--output", "json"
    ]

    result = run_aws_command(cmd)

    if not result.get("jobs"):
        print(f"❌ Job을 찾을 수 없습니다: {job_id}", file=sys.stderr)
        sys.exit(1)

    job = result["jobs"][0]
    log_stream = job.get("container", {}).get("logStreamName")
    status = job.get("status", "UNKNOWN")

    if not log_stream:
        print(f"❌ 로그 스트림을 찾을 수 없습니다. Job 상태: {status}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ 로그 스트림 발견: {log_stream}")
    print(f"📊 Job 상태: {status}")

    return log_stream, status


def fetch_logs(log_stream: str, region: str, log_group: str = None, limit: int = None) -> list[dict]:
    """CloudWatch Logs에서 로그 이벤트 가져오기"""
    print(f"📥 로그 가져오는 중... (limit: {limit or 'unlimited'})")
    
    # 로그 그룹 자동 감지: log-stream 이름으로 판단
    if not log_group:
        if log_stream.startswith("deep-agents/"):
            log_group = "/aws/batch/deep-agents"
        else:
            log_group = "/aws/batch/job"  # 기본값
    
    print(f"📂 로그 그룹: {log_group}")

    cmd = [
        "aws", "logs", "get-log-events",
        "--log-group-name", log_group,
        "--log-stream-name", log_stream,
        "--region", region,
        "--output", "json"
    ]

    if limit:
        cmd.extend(["--limit", str(limit)])

    result = run_aws_command(cmd)
    events = result.get("events", [])

    print(f"✅ {len(events)}개 로그 이벤트 가져옴")
    return events


def format_log_event(event: dict) -> str:
    """로그 이벤트를 읽기 좋은 형식으로 변환"""
    timestamp = datetime.fromtimestamp(event["timestamp"] / 1000)
    time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    message = event["message"].rstrip()

    return f"[{time_str}] {message}"


def should_include_log(message: str, errors_only: bool = False, min_level: str = None, 
                       filter_keyword: str = None, exclude_patterns: list = None) -> bool:
    """로그 메시지가 필터 조건에 맞는지 확인"""
    message_lower = message.lower()
    
    # 오류만 필터링
    if errors_only:
        error_patterns = [
            r'\bERROR\b',
            r'\bWARNING\b',
            r'\bException\b',
            r'\bTraceback\b',
            r'\bFailed\b',
            r'\bfailed\b',
            r'\b실패\b',
            r'⚠️',
            r'❌',
            r'validation error',
            r'파싱 실패',
            r'분석 실패',
            r'처리 실패',
        ]
        if not any(re.search(pattern, message, re.IGNORECASE) for pattern in error_patterns):
            return False
    
    # 최소 로그 레벨 필터링
    if min_level:
        level_order = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3, 'CRITICAL': 4}
        message_level = None
        for level in ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']:
            if f' - {level} - ' in message or f' - {level} ' in message:
                message_level = level
                break
        
        if message_level:
            if level_order.get(message_level, 0) < level_order.get(min_level, 0):
                return False
    
    # 키워드 필터링
    if filter_keyword:
        if filter_keyword.lower() not in message_lower:
            return False
    
    # 제외 패턴 필터링
    if exclude_patterns:
        for pattern in exclude_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return False
    
    return True


def save_logs(events: list[dict], output_path: Path, filter_keyword: str = None,
              errors_only: bool = False, min_level: str = None, exclude_patterns: list = None):
    """로그를 파일로 저장"""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    filtered_count = 0
    total_count = len(events)
    excluded_count = 0

    with open(output_path, 'w', encoding='utf-8') as f:
        for event in events:
            formatted = format_log_event(event)
            message = event.get("message", "")

            # 필터링 적용
            if should_include_log(message, errors_only, min_level, filter_keyword, exclude_patterns):
                f.write(formatted + '\n')
                filtered_count += 1
            else:
                excluded_count += 1

    # 통계 출력
    stats = []
    if errors_only:
        stats.append("오류/경고만")
    if min_level:
        stats.append(f"최소 레벨: {min_level}")
    if filter_keyword:
        stats.append(f"키워드: '{filter_keyword}'")
    if exclude_patterns:
        stats.append(f"제외 패턴: {len(exclude_patterns)}개")
    
    stats_str = f" ({', '.join(stats)})" if stats else ""
    print(f"📝 로그 저장 완료: {output_path}")
    print(f"   전체: {total_count}개 → 필터링: {filtered_count}개 (제외: {excluded_count}개){stats_str}")


def print_logs(events: list[dict], filter_keyword: str = None, tail: int = None,
               errors_only: bool = False, min_level: str = None, exclude_patterns: list = None):
    """로그를 콘솔에 출력"""
    filtered_events = []

    for event in events:
        formatted = format_log_event(event)
        message = event.get("message", "")

        if should_include_log(message, errors_only, min_level, filter_keyword, exclude_patterns):
            filtered_events.append(formatted)

    # tail 옵션 적용
    if tail and len(filtered_events) > tail:
        print(f"\n... ({len(filtered_events) - tail}개 이벤트 생략) ...\n")
        filtered_events = filtered_events[-tail:]

    for line in filtered_events:
        print(line)

    stats = []
    if errors_only:
        stats.append("오류/경고만")
    if min_level:
        stats.append(f"최소 레벨: {min_level}")
    if filter_keyword:
        stats.append(f"키워드: '{filter_keyword}'")
    
    stats_str = f" ({', '.join(stats)})" if stats else ""
    print(f"\n📊 총 {len(filtered_events)}/{len(events)} 이벤트{stats_str}")


def main():
    parser = argparse.ArgumentParser(
        description="AWS Batch 작업 로그 가져오기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # 입력 옵션
    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument(
        "--job-id",
        help="AWS Batch Job ID"
    )
    input_group.add_argument(
        "--log-stream",
        help="CloudWatch Log Stream 이름"
    )
    
    # 위치 인자로 log-stream 받기
    parser.add_argument(
        "log_stream_positional",
        nargs="?",
        help="CloudWatch Log Stream 이름 (위치 인자)"
    )

    # 출력 옵션
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="로그 저장 파일 경로 (기본값: logs/batch_<timestamp>.log)"
    )

    # 필터링 옵션
    parser.add_argument(
        "--limit",
        type=int,
        help="가져올 최대 이벤트 수"
    )
    parser.add_argument(
        "--filter", "-f",
        help="필터링할 키워드 (대소문자 구분 안함)"
    )
    parser.add_argument(
        "--tail", "-t",
        type=int,
        help="마지막 N개 이벤트만 출력 (콘솔 출력 시)"
    )
    parser.add_argument(
        "--errors-only", "-e",
        action="store_true",
        help="오류/경고만 필터링 (ERROR, WARNING, Exception, Traceback 등, 기본값)"
    )
    parser.add_argument(
        "--min-level",
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help="최소 로그 레벨 (이 레벨 이상만 포함)"
    )
    parser.add_argument(
        "--exclude",
        action="append",
        help="제외할 패턴 (정규식, 여러 번 사용 가능)"
    )

    # AWS 설정
    parser.add_argument(
        "--region",
        default="ap-northeast-2",
        help="AWS 리전 (기본값: ap-northeast-2)"
    )
    parser.add_argument(
        "--log-group",
        help="CloudWatch Log Group 이름 (기본값: 자동 감지)"
    )

    # 출력 모드
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="파일로 저장하지 않고 콘솔에만 출력"
    )
    
    # 기본값: 오류만 필터링 (편의성)
    parser.add_argument(
        "--all",
        action="store_true",
        help="모든 로그 포함 (기본값: --errors-only가 활성화된 경우 비활성화)"
    )

    args = parser.parse_args()
    
    # 기본값: 오류만 필터링 (--all이 없고 다른 필터도 없으면)
    if not args.all and not args.filter and not args.min_level:
        args.errors_only = True
        print("ℹ️  기본값: 오류/경고만 필터링 (--all로 모든 로그 포함 가능)")
    elif args.all:
        # --all이 지정되면 errors_only 비활성화
        args.errors_only = False

    # Log stream 이름 확인
    if args.job_id:
        log_stream, status = get_log_stream_from_job_id(args.job_id, args.region)
    elif args.log_stream:
        log_stream = args.log_stream
        print(f"🔍 로그 스트림: {log_stream}")
    elif args.log_stream_positional:
        log_stream = args.log_stream_positional
        print(f"🔍 로그 스트림: {log_stream}")
    else:
        parser.error("--job-id, --log-stream 또는 위치 인자로 log-stream을 제공해야 합니다.")

    # 로그 가져오기
    events = fetch_logs(log_stream, args.region, args.log_group, args.limit)

    if not events:
        print("⚠️ 로그 이벤트가 없습니다.")
        return

    # 콘솔 출력
    print("\n" + "="*80)
    print("📋 로그 내용")
    print("="*80 + "\n")
    print_logs(events, args.filter, args.tail, args.errors_only, args.min_level, args.exclude)

    # 파일 저장
    if not args.no_save:
        if args.output:
            output_path = args.output
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            job_suffix = args.job_id[:8] if args.job_id else "stream"
            suffix = "_errors" if args.errors_only else ""
            output_path = Path(f"logs/batch_{job_suffix}_{timestamp}{suffix}.log")

        save_logs(events, output_path, args.filter, args.errors_only, args.min_level, args.exclude)
        print(f"\n💾 로그 파일 위치: {output_path.absolute()}")


if __name__ == "__main__":
    main()

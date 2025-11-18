"""
Smart Batching 유틸리티

코드를 균등하게 분배하여 병렬 처리 효율 극대화

이 유틸리티는 전체 코드 샘플을 분석하여 최적의 배치 크기와 개수를 결정하고,
각 배치가 균등한 작업량을 가지도록 분배합니다. 이를 통해 병렬 처리 시
일부 에이전트가 일찍 끝나고 대기하는 시간을 최소화합니다.

주요 알고리즘:
1. 총 코드 수와 목표 배치 크기로 최적 에이전트 수 계산
2. 최대 에이전트 수 제한 적용 (동시성 제어)
3. 기본 배치 크기 계산 (총 코드 ÷ 에이전트 수)
4. 나머지 코드를 앞쪽 배치에 균등 분산
5. dict 형식 코드를 CodeSample Pydantic 모델로 변환
"""

import logging
from typing import List
from .schemas import CodeSample

logger = logging.getLogger(__name__)


class SmartBatcher:
    """
    동적 부하 분산 배치 생성기

    코드 샘플을 균등하게 분배하여 병렬 처리 시 모든 워커 에이전트가
    비슷한 작업량을 가지도록 합니다.
    """

    @staticmethod
    def create_balanced_batches(
        code_samples: List[dict],
        max_agents: int = 50,
        target_batch_size: int = 10
    ) -> List[List[CodeSample]]:
        """
        코드 샘플을 균등하게 분배하여 배치 생성

        Args:
            code_samples: 전체 코드 샘플 (dict 리스트)
                각 dict는 {"code": str, "file": str, "line_start": int, "line_end": int} 형식
            max_agents: 최대 병렬 에이전트 수 (동시성 제어)
                기본값 50 - AWS Bedrock API 동시성 제한 고려
            target_batch_size: 목표 배치 크기 (각 에이전트가 처리할 코드 수)
                기본값 10 - LLM 호출 시간과 병렬 처리 효율의 균형점

        Returns:
            균등 분배된 CodeSample 배치 리스트
            각 배치는 CodeSample 객체의 리스트

        Example:
            >>> samples = [{"code": "...", "file": "test.py", ...} for _ in range(88)]
            >>> batches = SmartBatcher.create_balanced_batches(samples)
            >>> len(batches)  # 9개 배치
            9
            >>> [len(b) for b in batches]  # 균등 분배
            [10, 10, 10, 10, 10, 10, 10, 9, 9]

        알고리즘 상세:
            1. 88개 코드, target_batch_size=10, max_agents=50
            2. 필요 에이전트 수 = ceil(88 / 10) = 9개
            3. 9 <= 50이므로 9개 에이전트 사용
            4. 기본 크기 = 88 ÷ 9 = 9개 (몫)
            5. 나머지 = 88 % 9 = 7개
            6. 앞의 7개 배치는 10개씩 (9+1), 뒤의 2개 배치는 9개씩
            7. 결과: [10, 10, 10, 10, 10, 10, 10, 9, 9]
        """
        total_codes = len(code_samples)

        # 빈 리스트 처리
        if total_codes == 0:
            logger.warning("⚠️ SmartBatcher: 코드 샘플이 없습니다")
            return []

        # 최적 에이전트 수 계산
        # ceil(total_codes / target_batch_size)를 정수 연산으로 구현
        num_agents = min(
            (total_codes + target_batch_size - 1) // target_batch_size,
            max_agents
        )

        logger.info(
            f"🔄 SmartBatcher: {total_codes}개 코드 → {num_agents}개 배치 생성 "
            f"(목표 크기: {target_batch_size}, 최대 에이전트: {max_agents})"
        )

        # 균등 분배 계산
        # 예: 88개를 9개로 나누면 기본 9개씩, 나머지 7개는 앞쪽 배치에 1개씩 추가
        base_size = total_codes // num_agents  # 기본 배치 크기 (몫)
        remainder = total_codes % num_agents   # 나머지 코드 수

        batches = []
        start_idx = 0

        for i in range(num_agents):
            # 나머지를 앞쪽 배치에 1개씩 분산
            # i < remainder이면 기본 크기 + 1, 아니면 기본 크기
            batch_size = base_size + (1 if i < remainder else 0)
            end_idx = start_idx + batch_size

            # dict → CodeSample Pydantic 모델 변환
            batch_codes = [
                CodeSample(
                    code=sample["code"],
                    file=sample.get("file", "unknown"),
                    line_start=sample.get("line_start", 0),
                    line_end=sample.get("line_end", 0),
                )
                for sample in code_samples[start_idx:end_idx]
            ]

            batches.append(batch_codes)

            logger.debug(
                f"  배치 {i}: {len(batch_codes)}개 코드 "
                f"(인덱스 {start_idx}-{end_idx-1})"
            )

            start_idx = end_idx

        # 검증: 모든 코드가 배치에 포함되었는지 확인
        total_batched = sum(len(batch) for batch in batches)
        if total_batched != total_codes:
            logger.error(
                f"❌ SmartBatcher 오류: {total_batched}/{total_codes}개만 배치됨"
            )
        else:
            logger.info(
                f"✅ SmartBatcher: {num_agents}개 배치 생성 완료 "
                f"(균등 분배: {[len(b) for b in batches]})"
            )

        return batches

    @staticmethod
    def get_batch_statistics(batches: List[List[CodeSample]]) -> dict:
        """
        배치 통계 계산 (디버깅 및 모니터링용)

        Args:
            batches: create_balanced_batches로 생성된 배치 리스트

        Returns:
            통계 정보 dict:
            {
                "total_batches": 총 배치 수,
                "total_codes": 총 코드 수,
                "min_batch_size": 최소 배치 크기,
                "max_batch_size": 최대 배치 크기,
                "avg_batch_size": 평균 배치 크기,
                "std_deviation": 표준 편차,
                "is_balanced": 균등 분배 여부 (max - min <= 1)
            }
        """
        if not batches:
            return {
                "total_batches": 0,
                "total_codes": 0,
                "min_batch_size": 0,
                "max_batch_size": 0,
                "avg_batch_size": 0.0,
                "std_deviation": 0.0,
                "is_balanced": True,
            }

        batch_sizes = [len(batch) for batch in batches]
        total_codes = sum(batch_sizes)
        avg_size = total_codes / len(batches)

        # 표준 편차 계산
        variance = sum((size - avg_size) ** 2 for size in batch_sizes) / len(batches)
        std_dev = variance ** 0.5

        # 균등 분배 여부 (최대 - 최소 <= 1이면 균등)
        is_balanced = (max(batch_sizes) - min(batch_sizes)) <= 1

        return {
            "total_batches": len(batches),
            "total_codes": total_codes,
            "min_batch_size": min(batch_sizes),
            "max_batch_size": max(batch_sizes),
            "avg_batch_size": round(avg_size, 2),
            "std_deviation": round(std_dev, 2),
            "is_balanced": is_balanced,
        }

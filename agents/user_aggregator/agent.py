"""UserAggregator Agent - 유저별 커밋 평가 집계 에이전트"""

import logging
import asyncio
import statistics
from typing import Any, Dict, List, Optional
from pathlib import Path

from shared.storage import ResultStore

from .schemas import (
    UserAggregatorContext,
    UserAggregatorResponse,
    QualityStats,
    TechStats,
    ComplexityStats,
    AggregateStats,
)

logger = logging.getLogger(__name__)


class UserAggregatorAgent:
    """
    유저별 커밋 평가 결과를 집계하는 에이전트

    Level 2 병렬 처리:
    - 품질 점수 통계 (평균, 중앙값, 표준편차, 분포)
    - 기술 스택 집계 (상위 기술, 빈도)
    - 복잡도 분포 분석 (low/medium/high 비율)
    """

    async def run(self, context: UserAggregatorContext) -> UserAggregatorResponse:
        """
        유저별 집계 실행

        Args:
            context: UserAggregatorContext (user, commit_evaluations 또는 result_store_path)

        Returns:
            UserAggregatorResponse (status, user, aggregate_stats, error)
        """
        user = context.user or "ALL_USERS"  # None이면 "ALL_USERS"로 표시

        # ResultStore에서 스트리밍으로 로드 (메모리 효율성)
        evaluations = await self._load_evaluations_streaming(context)

        logger.info(f"📊 UserAggregator: {user} ({len(evaluations)}개 커밋) 집계 시작")

        try:
            if not evaluations:
                logger.warning(f"⚠️ UserAggregator: {user} - 평가 결과 없음")
                return UserAggregatorResponse(
                    status="failed",
                    user=user,
                    aggregate_stats=AggregateStats(),
                    error="평가 결과 없음",
                )

            # Level 2: 병렬 집계 (품질, 기술, 복잡도)
            quality_stats, tech_stats, complexity_stats = await asyncio.gather(
                self._aggregate_quality(evaluations),
                self._aggregate_technologies(evaluations),
                self._aggregate_complexity(evaluations),
            )

            # 종합 통계 생성
            aggregate_stats = AggregateStats(
                total_commits=len(evaluations),
                successful_evaluations=sum(
                    1 for e in evaluations if e.get("status") == "success"
                ),
                failed_evaluations=sum(
                    1 for e in evaluations if e.get("status") == "failed"
                ),
                quality_stats=quality_stats,
                tech_stats=tech_stats,
                complexity_stats=complexity_stats,
            )

            logger.info(f"✅ UserAggregator: {user} 집계 완료")

            return UserAggregatorResponse(
                status="success",
                user=user,
                aggregate_stats=aggregate_stats,
                error=None,
            )

        except Exception as e:
            logger.error(f"❌ UserAggregator: {user} - {e}", exc_info=True)
            return UserAggregatorResponse(
                status="failed",
                user=user,
                aggregate_stats=AggregateStats(),
                error=str(e),
            )

    async def _aggregate_quality(self, evaluations: List[Dict[str, Any]]) -> QualityStats:
        """
        품질 점수 통계 집계

        Returns:
            QualityStats (average, median, min, max, std_dev, distribution)
        """

        def _calculate():
            scores = [
                e["quality_score"]
                for e in evaluations
                if e.get("status") == "success" and "quality_score" in e
            ]

            if not scores:
                return QualityStats()

            # 분포 계산 (0-2, 2-4, 4-6, 6-8, 8-10)
            distribution = {
                "0-2": sum(1 for s in scores if 0 <= s < 2),
                "2-4": sum(1 for s in scores if 2 <= s < 4),
                "4-6": sum(1 for s in scores if 4 <= s < 6),
                "6-8": sum(1 for s in scores if 6 <= s < 8),
                "8-10": sum(1 for s in scores if 8 <= s <= 10),
            }

            return QualityStats(
                average_score=round(statistics.mean(scores), 2),
                median_score=round(statistics.median(scores), 2),
                min_score=round(min(scores), 2),
                max_score=round(max(scores), 2),
                std_dev=(
                    round(statistics.stdev(scores), 2) if len(scores) > 1 else 0.0
                ),
                distribution=distribution,
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _calculate)

    async def _aggregate_technologies(
        self, evaluations: List[Dict[str, Any]]
    ) -> TechStats:
        """
        기술 스택 집계

        Returns:
            TechStats (top_technologies, total_unique, frequency)
        """

        def _calculate():
            tech_counter: Dict[str, int] = {}

            for e in evaluations:
                if e.get("status") == "success" and "technologies" in e:
                    for tech in e["technologies"]:
                        tech_counter[tech] = tech_counter.get(tech, 0) + 1

            # 상위 10개 기술 추출
            sorted_techs = sorted(
                tech_counter.items(), key=lambda x: x[1], reverse=True
            )

            return TechStats(
                top_technologies=sorted_techs[:10],
                total_unique_technologies=len(tech_counter),
                technology_frequency=tech_counter,
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _calculate)

    async def _load_evaluations_streaming(
        self, context: UserAggregatorContext
    ) -> List[Dict[str, Any]]:
        """
        CommitEvaluator 결과를 스트리밍으로 로드

        ResultStore에서 배치별로 읽어서 메모리 효율적으로 처리

        Returns:
            평가 결과 리스트
        """
        # Context에서 직접 전달된 경우 (하위 호환성)
        if context.commit_evaluations:
            logger.debug(f"📂 UserAggregator: Context에서 직접 전달된 결과 사용 ({len(context.commit_evaluations)}개)")
            return context.commit_evaluations

        # ResultStore에서 배치 스트리밍 로드
        if not context.result_store_path:
            logger.warning("⚠️ UserAggregator: commit_evaluations와 result_store_path 모두 없음")
            return []

        try:
            # S3 경로인 경우 처리
            if context.result_store_path.startswith("s3://"):
                # s3://bucket/analyze_multi/.../results -> analyze_multi/.../repos/{task_uuid}
                path_parts = context.result_store_path.replace("s3://", "").split("/")
                # bucket 이름 제거 (첫 번째 요소)
                if len(path_parts) > 1:
                    path_parts = path_parts[1:]  # bucket 제거
                    # results 제거 (마지막 요소)
                    if path_parts and path_parts[-1] == "results":
                        path_parts = path_parts[:-1]
                    base_path = "/".join(path_parts)
                    logger.debug(f"🔧 UserAggregator: S3 경로에서 base_path 추출: {context.result_store_path} -> {base_path}")
                else:
                    # 예외 처리: 경로 파싱 실패
                    logger.warning(f"⚠️ UserAggregator: S3 경로 파싱 실패: {context.result_store_path}")
                    base_path = Path(context.result_store_path).parent
            else:
                # 로컬 경로
                base_path = Path(context.result_store_path).parent
            store = ResultStore(context.task_uuid, base_path)
            
            logger.info(f"🔍 UserAggregator 디버깅: task_uuid={context.task_uuid}, base_path={base_path}")
            logger.info(f"   ResultStore results_dir: {store.results_dir}")

            # 배치 결과 스트리밍 로드 (S3/로컬 모두 지원)
            batched_agents = store.list_batched_agents()
            logger.info(f"   📋 배치 에이전트 목록: {batched_agents}")
            
            if "commit_evaluator" not in batched_agents:
                logger.warning(f"⚠️ UserAggregator: commit_evaluator 배치 결과 없음")
                logger.warning(f"   사용 가능한 배치 에이전트: {batched_agents}")
                logger.warning(f"   commit_evaluator 배치 디렉토리 확인: {store.get_batch_dir('commit_evaluator')}")
                return []

            # ResultStore의 load_batched_results를 사용하여 배치 결과 로드 (S3/로컬 모두 지원)
            logger.info(f"📂 UserAggregator: commit_evaluator 배치 결과 스트리밍 로드 시작")
            logger.info(f"   배치 디렉토리: {store.get_batch_dir('commit_evaluator')}")
            all_evaluations = store.load_batched_results("commit_evaluator")

            logger.info(f"✅ UserAggregator: 총 {len(all_evaluations)}개 평가 결과 스트리밍 로드 완료")
            if len(all_evaluations) == 0:
                logger.warning(f"⚠️ UserAggregator: 로드된 평가 결과가 0개입니다. 배치 파일이 비어있을 수 있습니다.")
            return all_evaluations

        except Exception as e:
            logger.error(f"❌ UserAggregator: 스트리밍 로드 실패 - {e}", exc_info=True)
            return []

    async def _aggregate_complexity(
        self, evaluations: List[Dict[str, Any]]
    ) -> ComplexityStats:
        """
        복잡도 분포 집계

        Returns:
            ComplexityStats (low/medium/high/unknown counts, percentages)
        """

        def _calculate():
            complexity_counter = {"low": 0, "medium": 0, "high": 0, "unknown": 0}

            for e in evaluations:
                if e.get("status") == "success" and "complexity" in e:
                    complexity = e["complexity"]
                    if complexity in complexity_counter:
                        complexity_counter[complexity] += 1
                    else:
                        complexity_counter["unknown"] += 1

            total = sum(complexity_counter.values())

            # 백분율 계산
            percentages = {}
            if total > 0:
                for level, count in complexity_counter.items():
                    percentages[level] = round((count / total) * 100, 1)

            return ComplexityStats(
                low_count=complexity_counter["low"],
                medium_count=complexity_counter["medium"],
                high_count=complexity_counter["high"],
                unknown_count=complexity_counter["unknown"],
                percentages=percentages,
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _calculate)

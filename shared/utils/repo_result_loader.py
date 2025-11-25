"""
레포지토리 결과 로드 및 가공 유틸리티

모든 에이전트 결과를 로드하고 필요한 필드만 추출하는 공통 로직 제공
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from shared.storage import ResultStore

# Response 클래스 import
from agents.repo_cloner.schemas import RepoClonerResponse
from agents.static_analyzer.schemas import StaticAnalyzerResponse
from agents.commit_analyzer.schemas import CommitAnalyzerResponse
from agents.code_rag_builder.schemas import CodeRAGBuilderResponse
from agents.user_aggregator.schemas import UserAggregatorResponse
from agents.reporter.schemas import ReporterResponse
from agents.user_skill_profiler.schemas import UserSkillProfilerResponse

logger = logging.getLogger(__name__)


def load_all_agent_results(
    store: ResultStore,
    include_all: bool = False
) -> Dict[str, Any]:
    """
    모든 에이전트 결과를 로드하고 가공
    
    Args:
        store: ResultStore 인스턴스
        include_all: True이면 모든 에이전트 결과 포함, False이면 높은 우선순위만
    
    Returns:
        {
            "reporter_result": {...} or None,
            "user_aggregator_result": {...} or None,
            "static_analyzer_result": {...} or None,
            "commit_analyzer_result": {...} or None,  # include_all=True일 때만
            "code_rag_builder_result": {...} or None,  # include_all=True일 때만
            "repo_cloner_result": {...} or None,  # include_all=True일 때만
        }
    """
    results = {}
    
    # 1. ReporterResponse (높은 우선순위)
    try:
        reporter_response = store.load_result("reporter", ReporterResponse)
        if reporter_response:
            results["reporter_result"] = reporter_response.model_dump()
            logger.debug("✅ Reporter 결과 로드 성공")
    except FileNotFoundError:
        logger.debug("⚠️ Reporter 결과 파일 없음")
        results["reporter_result"] = None
    except Exception as e:
        logger.warning(f"⚠️ Reporter 결과 로드 실패: {e}")
        results["reporter_result"] = None
    
    # 2. UserAggregatorResponse (높은 우선순위)
    try:
        user_agg_response = store.load_result("user_aggregator", UserAggregatorResponse)
        if user_agg_response:
            results["user_aggregator_result"] = user_agg_response.model_dump()
            logger.debug("✅ UserAggregator 결과 로드 성공")
    except FileNotFoundError:
        logger.debug("⚠️ UserAggregator 결과 파일 없음")
        results["user_aggregator_result"] = None
    except Exception as e:
        logger.warning(f"⚠️ UserAggregator 결과 로드 실패: {e}")
        results["user_aggregator_result"] = None
    
    # 3. StaticAnalyzerResponse (높은 우선순위) - 핵심 필드만 추출
    try:
        static_response = store.load_result("static_analyzer", StaticAnalyzerResponse)
        if static_response:
            static_dict = static_response.model_dump()
            # 핵심 정보만 추출
            results["static_analyzer_result"] = {
                "loc_stats": static_dict.get("loc_stats", {}),
                "complexity": static_dict.get("complexity", {}),
                "type_check": static_dict.get("type_check", {}),
            }
            logger.debug("✅ StaticAnalyzer 결과 로드 성공 (핵심 필드만)")
    except FileNotFoundError:
        logger.debug("⚠️ StaticAnalyzer 결과 파일 없음")
        results["static_analyzer_result"] = None
    except Exception as e:
        logger.warning(f"⚠️ StaticAnalyzer 결과 로드 실패: {e}")
        results["static_analyzer_result"] = None
    
    # 4. 나머지 에이전트 (include_all=True일 때만)
    if include_all:
        # CommitAnalyzerResponse
        try:
            commit_analyzer_response = store.load_result("commit_analyzer", CommitAnalyzerResponse)
            if commit_analyzer_response:
                results["commit_analyzer_result"] = commit_analyzer_response.model_dump()
                logger.debug("✅ CommitAnalyzer 결과 로드 성공")
        except FileNotFoundError:
            logger.debug("⚠️ CommitAnalyzer 결과 파일 없음")
            results["commit_analyzer_result"] = None
        except Exception as e:
            logger.warning(f"⚠️ CommitAnalyzer 결과 로드 실패: {e}")
            results["commit_analyzer_result"] = None
        
        # CodeRAGBuilderResponse
        try:
            code_rag_response = store.load_result("code_rag_builder", CodeRAGBuilderResponse)
            if code_rag_response:
                results["code_rag_builder_result"] = code_rag_response.model_dump()
                logger.debug("✅ CodeRAGBuilder 결과 로드 성공")
        except FileNotFoundError:
            logger.debug("⚠️ CodeRAGBuilder 결과 파일 없음")
            results["code_rag_builder_result"] = None
        except Exception as e:
            logger.warning(f"⚠️ CodeRAGBuilder 결과 로드 실패: {e}")
            results["code_rag_builder_result"] = None
        
        # RepoClonerResponse
        try:
            repo_cloner_response = store.load_result("repo_cloner", RepoClonerResponse)
            if repo_cloner_response:
                results["repo_cloner_result"] = repo_cloner_response.model_dump()
                logger.debug("✅ RepoCloner 결과 로드 성공")
        except FileNotFoundError:
            logger.debug("⚠️ RepoCloner 결과 파일 없음")
            results["repo_cloner_result"] = None
        except Exception as e:
            logger.warning(f"⚠️ RepoCloner 결과 로드 실패: {e}")
            results["repo_cloner_result"] = None
    
    return results


def extract_static_analyzer_core_fields(
    static_response: StaticAnalyzerResponse
) -> Dict[str, Any]:
    """
    StaticAnalyzerResponse에서 핵심 필드만 추출
    
    Args:
        static_response: StaticAnalyzerResponse 인스턴스
    
    Returns:
        {
            "loc_stats": {...},
            "complexity": {...},
            "type_check": {...}
        }
    """
    static_dict = static_response.model_dump()
    return {
        "loc_stats": static_dict.get("loc_stats", {}),
        "complexity": static_dict.get("complexity", {}),
        "type_check": static_dict.get("type_check", {}),
    }


def create_repo_summary(
    store: ResultStore,
    git_url: str,
    task_uuid: str,
    base_path: str,
    total_commits: int = 0,
    total_files: int = 0,
    final_report_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    레포지토리 요약 정보 생성 (Analysis.result의 repo_summaries용)
    
    Args:
        store: ResultStore 인스턴스
        git_url: 레포지토리 URL
        task_uuid: 작업 UUID
        base_path: 결과 저장 경로
        total_commits: 총 커밋 수
        total_files: 총 파일 수
        final_report_path: 최종 리포트 경로
    
    Returns:
        레포지토리 요약 딕셔너리
    """
    summary = {
        "git_url": git_url,
        "task_uuid": task_uuid,
        "base_path": base_path,
        "status": "success",
        "total_commits": total_commits,
        "total_files": total_files,
        "final_report_path": final_report_path,
    }
    
    # UserAggregator에서 품질 점수 추출
    try:
        user_agg_response = store.load_result("user_aggregator", UserAggregatorResponse)
        if user_agg_response:
            user_agg = user_agg_response.model_dump()
            if user_agg.get("aggregate_stats"):
                quality_stats = user_agg["aggregate_stats"].get("quality_stats", {})
                quality_score = quality_stats.get("average_score")
                if quality_score is not None:
                    summary["quality_score"] = quality_score
    except Exception as e:
        logger.debug(f"⚠️ 품질 점수 추출 실패: {e}")
    
    # 요약 정보 추가 (핵심 필드만)
    summary_data = {}
    
    # StaticAnalyzer 요약
    try:
        static_response = store.load_result("static_analyzer", StaticAnalyzerResponse)
        if static_response:
            summary_data["static_analysis"] = extract_static_analyzer_core_fields(static_response)
    except Exception:
        pass
    
    # UserSkillProfiler 요약 (상위 5개 스킬만)
    try:
        skill_profile_response = store.load_result("user_skill_profiler", UserSkillProfilerResponse)
        if skill_profile_response:
            skill_dict = skill_profile_response.model_dump()
            skill_profile_data = skill_dict.get("skill_profile", {})
            summary_data["skill_profile"] = {
                "total_skills": skill_profile_data.get("total_skills", 0),
                "top_skills": skill_profile_data.get("top_skills", [])[:5],  # 상위 5개만
                "level": skill_profile_data.get("level", {}),
            }
    except Exception:
        pass
    
    # UserAggregator 요약 (핵심 통계만)
    try:
        user_agg_response = store.load_result("user_aggregator", UserAggregatorResponse)
        if user_agg_response:
            user_agg = user_agg_response.model_dump()
            aggregate_stats = user_agg.get("aggregate_stats", {})
            summary_data["user_aggregator"] = {
                "quality_stats": aggregate_stats.get("quality_stats", {}),
                "tech_stats": aggregate_stats.get("tech_stats", {}),
            }
    except Exception:
        pass
    
    if summary_data:
        summary["summary"] = summary_data
    
    return summary


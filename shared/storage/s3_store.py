"""
S3StorageBackend - AWS S3 기반 스토리지

AWS 프로덕션 환경에서 S3에 결과를 저장/로드
"""

import json
import logging
from typing import Type, TypeVar, Optional, List, Any
from datetime import datetime
from pathlib import Path
try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    ClientError = Exception

from shared.storage.base import StorageBackend
from shared.schemas.common import BaseResponse
from shared.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseResponse)


class S3StorageBackend(StorageBackend):
    """
    AWS S3 기반 스토리지 백엔드

    구조:
        s3://bucket-name/analyze_multi/{main_task_uuid}/repos/{task_uuid}/
        ├── results/
        │   ├── repo_cloner.json
        │   ├── static_analyzer.json
        │   ├── commit_evaluator/
        │   │   ├── batch_0000.json
        │   │   └── batch_0001.json
        │   └── reporter.json
        └── metadata.json
    """

    def __init__(self, task_uuid: str, base_path: str):
        """
        S3StorageBackend 초기화

        Args:
            task_uuid: 작업 고유 UUID
            base_path: S3 기본 경로 (예: "analyze_multi/{main_task_uuid}/repos/{task_uuid}")

        Raises:
            ImportError: boto3가 설치되지 않은 경우
        """
        if boto3 is None:
            raise ImportError(
                "boto3가 설치되지 않았습니다. 'pip install boto3'를 실행하세요."
            )

        super().__init__(task_uuid, base_path)

        # S3 설정
        # ARN 형식인 경우 bucket name만 추출
        bucket_name_raw = settings.S3_BUCKET_NAME
        if bucket_name_raw.startswith("arn:aws:s3:::"):
            # arn:aws:s3:::bucket-name 형식에서 bucket name 추출
            self.bucket_name = bucket_name_raw.split(":::")[-1]
        else:
            self.bucket_name = bucket_name_raw
            
        self.region = settings.S3_REGION
        self.base_prefix = base_path.strip("/")
        self.results_prefix = f"{self.base_prefix}/results"

        # S3 클라이언트 생성
        self.s3_client = boto3.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

        logger.debug(f"📦 S3StorageBackend 초기화: s3://{self.bucket_name}/{self.base_prefix}")

    def _get_s3_key(self, *parts: str) -> str:
        """S3 키 생성 헬퍼"""
        return "/".join(str(p).strip("/") for p in parts if p)

    def _upload_json(self, key: str, data: dict | str) -> str:
        """JSON 데이터를 S3에 업로드"""
        try:
            if isinstance(data, str):
                json_content = data
            else:
                json_content = json.dumps(data, indent=2, ensure_ascii=False, default=str)

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json_content.encode("utf-8"),
                ContentType="application/json",
                Metadata={"uploaded_at": datetime.now().isoformat()},
            )

            s3_path = f"s3://{self.bucket_name}/{key}"
            logger.debug(f"💾 S3 업로드: {s3_path}")
            return s3_path

        except ClientError as e:
            logger.error(f"❌ S3 업로드 실패 ({key}): {e}")
            raise

    def _download_json(self, key: str) -> dict:
        """S3에서 JSON 데이터 다운로드"""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            json_content = response["Body"].read().decode("utf-8")
            return json.loads(json_content)

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"S3 객체를 찾을 수 없습니다: s3://{self.bucket_name}/{key}")
            logger.error(f"❌ S3 다운로드 실패 ({key}): {e}")
            raise

    def _list_objects(self, prefix: str, suffix: str = "") -> List[str]:
        """S3 객체 목록 조회"""
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)

            keys = []
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        key = obj["Key"]
                        if suffix and not key.endswith(suffix):
                            continue
                        keys.append(key)

            return sorted(keys)

        except ClientError as e:
            logger.error(f"❌ S3 목록 조회 실패 ({prefix}): {e}")
            return []

    def save_result(self, agent_name: str, result: BaseResponse) -> str:
        """에이전트 결과를 S3에 저장"""
        key = self._get_s3_key(self.results_prefix, f"{agent_name}.json")

        try:
            json_content = result.model_dump_json(indent=2, ensure_ascii=False)
            s3_path = self._upload_json(key, json_content)

            logger.info(f"💾 결과 저장 (S3): {agent_name} → {s3_path}")
            return s3_path

        except Exception as e:
            logger.error(f"❌ 결과 저장 실패 ({agent_name}): {e}")
            raise

    def load_result(self, agent_name: str, result_class: Type[T]) -> T:
        """S3에서 저장된 에이전트 결과를 로드"""
        key = self._get_s3_key(self.results_prefix, f"{agent_name}.json")

        try:
            data = self._download_json(key)
            result = result_class(**data)

            logger.debug(f"📂 결과 로드 (S3): {agent_name} ← s3://{self.bucket_name}/{key}")
            return result

        except FileNotFoundError:
            raise FileNotFoundError(f"결과를 찾을 수 없습니다: {agent_name}")
        except Exception as e:
            logger.error(f"❌ 결과 로드 실패 ({agent_name}): {e}")
            raise

    def save_batched_result(
        self,
        agent_name: str,
        batch_id: int,
        result: BaseResponse | List[BaseResponse] | dict[str, Any],
    ) -> str:
        """대용량 결과를 배치별로 S3에 저장"""
        key = self._get_s3_key(
            self.results_prefix, agent_name, f"batch_{batch_id:04d}.json"
        )

        try:
            # 결과 타입에 따라 직렬화
            if isinstance(result, BaseResponse):
                data = result.model_dump()
            elif isinstance(result, list) and result and isinstance(result[0], BaseResponse):
                data = [r.model_dump() for r in result]
            else:
                data = result

            s3_path = self._upload_json(key, data)

            logger.info(f"💾 배치 결과 저장 (S3): {agent_name}/batch_{batch_id:04d} → {s3_path}")
            return s3_path

        except Exception as e:
            logger.error(f"❌ 배치 결과 저장 실패 ({agent_name}/batch_{batch_id}): {e}")
            raise

    def load_batched_results(
        self,
        agent_name: str,
        result_class: Optional[Type[T]] = None,
    ) -> List[dict[str, Any]] | List[T]:
        """S3에서 배치 결과 전체를 로드"""
        prefix = self._get_s3_key(self.results_prefix, agent_name, "batch_")
        batch_keys = self._list_objects(prefix, suffix=".json")

        if not batch_keys:
            logger.warning(f"⚠️  배치 파일이 없습니다: {agent_name}")
            return []

        results = []

        for key in batch_keys:
            try:
                data = self._download_json(key)

                if result_class:
                    if isinstance(data, list):
                        results.extend([result_class(**item) for item in data])
                    else:
                        results.append(result_class(**data))
                else:
                    if isinstance(data, list):
                        results.extend(data)
                    else:
                        results.append(data)

            except Exception as e:
                logger.error(f"❌ 배치 파일 로드 실패 ({key}): {e}")
                continue

        logger.debug(f"📂 배치 결과 로드 (S3): {agent_name} - {len(results)}개 항목")
        return results

    def save_metadata(self, metadata: dict[str, Any]) -> str:
        """작업 메타데이터를 S3에 저장"""
        key = self._get_s3_key(self.base_prefix, "metadata.json")

        # 타임스탬프 추가
        metadata["updated_at"] = datetime.now().isoformat()

        try:
            s3_path = self._upload_json(key, metadata)
            logger.debug(f"💾 메타데이터 저장 (S3): {s3_path}")
            return s3_path

        except Exception as e:
            logger.error(f"❌ 메타데이터 저장 실패: {e}")
            raise

    def load_metadata(self) -> dict[str, Any]:
        """S3에서 작업 메타데이터를 로드"""
        key = self._get_s3_key(self.base_prefix, "metadata.json")

        try:
            return self._download_json(key)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error(f"❌ 메타데이터 로드 실패: {e}")
            return {}

    def list_available_results(self) -> List[str]:
        """S3에서 저장된 에이전트 결과 목록 조회"""
        prefix = self._get_s3_key(self.results_prefix, "")
        keys = self._list_objects(prefix, suffix=".json")

        # 파일명만 추출 (디렉토리 제외)
        result_files = []
        for key in keys:
            parts = key.split("/")
            if len(parts) > 0:
                filename = parts[-1]
                # batch_ 파일 제외, .json 파일만
                if not filename.startswith("batch_") and filename.endswith(".json"):
                    result_files.append(filename.replace(".json", ""))

        return sorted(set(result_files))

    def list_batched_agents(self) -> List[str]:
        """S3에서 배치 저장된 에이전트 목록 조회"""
        prefix = self._get_s3_key(self.results_prefix, "")
        keys = self._list_objects(prefix)

        # batch_ 파일이 있는 에이전트 추출
        batched_agents = set()
        for key in keys:
            parts = key.split("/")
            if len(parts) >= 2:
                filename = parts[-1]
                if filename.startswith("batch_"):
                    agent_name = parts[-2]
                    batched_agents.add(agent_name)

        return sorted(batched_agents)

    def get_result_path(self, agent_name: str) -> str:
        """에이전트 결과 S3 경로 반환"""
        key = self._get_s3_key(self.results_prefix, f"{agent_name}.json")
        return f"s3://{self.bucket_name}/{key}"

    def get_batch_dir(self, agent_name: str) -> str:
        """배치 결과 S3 디렉토리 경로 반환"""
        prefix = self._get_s3_key(self.results_prefix, agent_name, "")
        return f"s3://{self.bucket_name}/{prefix}"

    def save_report(self, report_name: str, content: str) -> str:
        """리포트 파일을 S3에 저장"""
        key = self._get_s3_key(self.base_prefix, "reports", report_name)
        
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=content.encode("utf-8"),
                ContentType="text/markdown",
                Metadata={"uploaded_at": datetime.now().isoformat()},
            )
            
            s3_path = f"s3://{self.bucket_name}/{key}"
            logger.info(f"💾 리포트 저장 (S3): {s3_path}")
            return s3_path
            
        except ClientError as e:
            logger.error(f"❌ 리포트 저장 실패 ({report_name}): {e}")
            raise

    def load_report(self, report_name: str) -> str:
        """S3에서 리포트 파일 로드"""
        key = self._get_s3_key(self.base_prefix, "reports", report_name)
        
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            content = response["Body"].read().decode("utf-8")
            logger.debug(f"📂 리포트 로드 (S3): {report_name}")
            return content
            
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"리포트 파일을 찾을 수 없습니다: {report_name}")
            logger.error(f"❌ 리포트 로드 실패 ({report_name}): {e}")
            raise

    def save_log(self, log_name: str, content: str) -> str:
        """로그 파일을 S3에 저장"""
        key = self._get_s3_key(self.base_prefix, "logs", log_name)
        
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=content.encode("utf-8"),
                ContentType="text/plain",
                Metadata={"uploaded_at": datetime.now().isoformat()},
            )
            
            s3_path = f"s3://{self.bucket_name}/{key}"
            logger.info(f"💾 로그 저장 (S3): {s3_path}")
            return s3_path
            
        except ClientError as e:
            logger.error(f"❌ 로그 저장 실패 ({log_name}): {e}")
            raise

    def upload_log_directory(self, local_log_dir: Path, remote_subdir: str = None) -> List[str]:
        """
        로그 디렉토리 전체를 S3에 업로드
        
        Args:
            local_log_dir: 로컬 로그 디렉토리 경로
            remote_subdir: S3에 저장할 하위 디렉토리 (예: "debug" → logs/debug/)
        """
        if not local_log_dir.exists():
            logger.warning(f"⚠️ 로그 디렉토리가 존재하지 않습니다: {local_log_dir}")
            return []
        
        uploaded_paths = []
        
        try:
            for log_file in local_log_dir.rglob("*"):
                if log_file.is_file():
                    # 상대 경로 계산
                    relative_path = log_file.relative_to(local_log_dir)
                    
                    # S3 키 생성
                    if remote_subdir:
                        key = self._get_s3_key(self.base_prefix, "logs", remote_subdir, str(relative_path))
                    else:
                        key = self._get_s3_key(self.base_prefix, "logs", str(relative_path))
                    
                    # 파일 업로드
                    self.s3_client.upload_file(
                        str(log_file),
                        self.bucket_name,
                        key,
                        ExtraArgs={
                            "ContentType": "text/plain",
                            "Metadata": {"uploaded_at": datetime.now().isoformat()},
                        }
                    )
                    
                    s3_path = f"s3://{self.bucket_name}/{key}"
                    uploaded_paths.append(s3_path)
                    logger.debug(f"💾 로그 파일 업로드: {log_file.name} → {s3_path}")
            
            logger.info(f"✅ 로그 디렉토리 업로드 완료: {len(uploaded_paths)}개 파일")
            return uploaded_paths
            
        except ClientError as e:
            logger.error(f"❌ 로그 디렉토리 업로드 실패: {e}")
            raise

    def save_debug_file(self, relative_path: str, content: str | bytes) -> str:
        """디버그 파일을 S3에 저장"""
        key = self._get_s3_key(self.base_prefix, relative_path)
        
        try:
            if isinstance(content, bytes):
                body = content
                content_type = "application/octet-stream"
            else:
                body = content.encode("utf-8")
                content_type = "application/json" if relative_path.endswith(".json") else "text/plain"
            
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata={"uploaded_at": datetime.now().isoformat()},
            )
            
            s3_path = f"s3://{self.bucket_name}/{key}"
            logger.debug(f"💾 디버그 파일 저장 (S3): {relative_path} → {s3_path}")
            return s3_path
            
        except ClientError as e:
            logger.error(f"❌ 디버그 파일 저장 실패 ({relative_path}): {e}")
            raise

    def load_debug_file(self, relative_path: str) -> str:
        """디버그 파일을 S3에서 로드"""
        key = self._get_s3_key(self.base_prefix, relative_path)
        
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            content = response["Body"].read().decode("utf-8")
            logger.debug(f"📂 디버그 파일 로드 (S3): {relative_path} → s3://{self.bucket_name}/{key}")
            return content
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                raise FileNotFoundError(f"디버그 파일을 찾을 수 없습니다: {relative_path} (s3://{self.bucket_name}/{key})")
            logger.error(f"❌ 디버그 파일 로드 실패 ({relative_path}): {e}")
            raise

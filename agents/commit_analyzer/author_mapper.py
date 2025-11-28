"""
Author Mapping Module

한 사람이 여러 Git username/email을 사용하는 경우를 처리하는 모듈.
매핑 규칙을 정의하여 여러 ID를 하나의 canonical ID로 통합.

Example:
    >>> mapping_rules = {
    ...     "John Doe": {
    ...         "canonical_email": "john.doe@company.com",
    ...         "aliases": [
    ...             {"name": "John Doe", "email": "john@work.com"},
    ...             {"name": "J. Doe", "email": "john@personal.com"},
    ...         ]
    ...     }
    ... }
    >>> mapper = AuthorMapper(mapping_rules)
    >>> mapper.normalize_author("J. Doe", "john@personal.com")
    ('John Doe', 'john.doe@company.com')
"""

import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)


class AuthorMapper:
    """Git 저자 ID를 정규화하는 매퍼"""

    def __init__(self, mapping_rules: Optional[Dict] = None):
        """
        Args:
            mapping_rules: {
                "canonical_name": {
                    "canonical_email": "master@email.com",
                    "aliases": [
                        {"name": "Alias Name", "email": "alias@email.com"},
                        {"email": "another@email.com"}  # name 생략 가능
                    ]
                }
            }
            None인 경우 매핑 없이 원본 그대로 반환
        """
        self.mapping_rules = mapping_rules or {}
        self._build_lookup_table()

    def _build_lookup_table(self):
        """빠른 검색을 위한 lookup 테이블 구축"""
        self.lookup = {}  # (name, email) -> (canonical_name, canonical_email)

        for canonical_name, rule in self.mapping_rules.items():
            canonical_email = rule["canonical_email"]

            # Canonical ID 자체도 등록
            self.lookup[
                (canonical_name.lower().strip(), canonical_email.lower().strip())
            ] = (canonical_name, canonical_email)

            # Aliases 등록
            for alias in rule.get("aliases", []):
                alias_name = alias.get("name", canonical_name).lower().strip()
                alias_email = alias["email"].lower().strip()
                self.lookup[(alias_name, alias_email)] = (canonical_name, canonical_email)

                # 이메일만으로도 매칭 가능하도록 (이름이 다양하게 변할 수 있으므로)
                self.lookup[(None, alias_email)] = (canonical_name, canonical_email)

        if self.mapping_rules:
            logger.info(
                f"AuthorMapper initialized: {len(self.mapping_rules)} developers, "
                f"{len(self.lookup)} total mappings"
            )

    def normalize_author(self, name: str, email: str) -> Tuple[str, str]:
        """
        저자 이름/이메일을 정규화

        Args:
            name: 원본 저자 이름
            email: 원본 이메일

        Returns:
            (정규화된 이름, 정규화된 이메일)
        """
        if not self.mapping_rules:
            # 매핑 규칙이 없으면 원본 그대로 반환
            return (name, email)

        name_normalized = name.lower().strip()
        email_normalized = email.lower().strip()

        # 1. 정확한 (name, email) 매칭 시도
        if (name_normalized, email_normalized) in self.lookup:
            return self.lookup[(name_normalized, email_normalized)]

        # 2. 이메일만으로 매칭 시도
        if (None, email_normalized) in self.lookup:
            return self.lookup[(None, email_normalized)]

        # 3. 매칭 실패 시 원본 반환
        return (name, email)

    def get_mapping_stats(self) -> Dict[str, int]:
        """
        매핑 통계 반환

        Returns:
            {
                "total_developers": int,
                "total_aliases": int,
                "enabled": bool
            }
        """
        total_aliases = sum(
            len(rule.get("aliases", [])) for rule in self.mapping_rules.values()
        )

        return {
            "total_developers": len(self.mapping_rules),
            "total_aliases": total_aliases,
            "enabled": len(self.mapping_rules) > 0,
        }

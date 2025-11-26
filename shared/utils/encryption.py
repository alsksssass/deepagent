"""
Token Encryption Utility

Fernet 대칭키 암호화를 사용하여 GitHub access token을 암호화/복호화합니다.
Backend와 동일한 암호화 방식 사용.
"""

import os
from cryptography.fernet import Fernet


class TokenEncryption:
    """
    Fernet 암호화를 사용한 토큰 암호화 유틸리티

    Usage:
        encrypted = TokenEncryption.encrypt("my_github_token")
        decrypted = TokenEncryption.decrypt(encrypted)
    """

    _cipher = None

    @classmethod
    def _get_cipher(cls):
        """Cipher 인스턴스를 Lazy 초기화"""
        if cls._cipher is None:
            encryption_key = os.getenv("ENCRYPTION_KEY")
            if not encryption_key:
                raise ValueError("ENCRYPTION_KEY environment variable not set")
            cls._cipher = Fernet(encryption_key.encode())
        return cls._cipher

    @classmethod
    def encrypt(cls, token: str) -> str:
        """
        토큰을 암호화합니다.

        Args:
            token: 암호화할 평문 토큰

        Returns:
            암호화된 토큰 문자열
        """
        if not token:
            return ""
        cipher = cls._get_cipher()
        return cipher.encrypt(token.encode()).decode()

    @classmethod
    def decrypt(cls, encrypted_token: str) -> str:
        """
        암호화된 토큰을 복호화합니다.

        Args:
            encrypted_token: 암호화된 토큰 문자열

        Returns:
            복호화된 평문 토큰
        """
        if not encrypted_token:
            return ""
        cipher = cls._get_cipher()
        return cipher.decrypt(encrypted_token.encode()).decode()

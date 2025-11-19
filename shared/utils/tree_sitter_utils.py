"""
Tree-sitter 기반 코드 파싱 유틸리티

실제 tree-sitter 라이브러리를 사용하여 AST 기반 코드 분석 제공
"""

import logging
from typing import Optional
from tree_sitter import Language, Parser, Node

logger = logging.getLogger(__name__)

# 언어별 파서 캐시 (싱글톤 패턴)
_PARSERS = {}
_LANGUAGES = {}


def _init_language(lang_name: str, module_name: str, func_name: str) -> Optional[Language]:
    """언어 모듈 초기화 (동적 import)"""
    try:
        module = __import__(module_name)
        language_func = getattr(module, func_name)
        return Language(language_func())
    except ImportError:
        logger.debug(f"⚠️  {lang_name} parser not available ({module_name})")
        return None
    except Exception as e:
        logger.debug(f"⚠️  Failed to initialize {lang_name}: {e}")
        return None


def _get_language(lang_name: str) -> Optional[Language]:
    """언어 객체 반환 (캐시 사용)"""
    if lang_name not in _LANGUAGES:
        # 언어별 모듈과 함수 매핑 (module_name, function_name)
        language_map = {
            'python': ('tree_sitter_python', 'language'),
            'javascript': ('tree_sitter_javascript', 'language'),
            'typescript': ('tree_sitter_typescript', 'language_typescript'),
            'tsx': ('tree_sitter_typescript', 'language_tsx'),
            'java': ('tree_sitter_java', 'language'),
            'go': ('tree_sitter_go', 'language'),
            'rust': ('tree_sitter_rust', 'language'),
            'cpp': ('tree_sitter_cpp', 'language'),
            'c': ('tree_sitter_c', 'language'),
            'csharp': ('tree_sitter_c_sharp', 'language'),
            'ruby': ('tree_sitter_ruby', 'language'),
            'php': ('tree_sitter_php', 'language_php'),
        }

        lang_info = language_map.get(lang_name)
        if lang_info:
            module_name, func_name = lang_info
            _LANGUAGES[lang_name] = _init_language(lang_name, module_name, func_name)
        else:
            _LANGUAGES[lang_name] = None

    return _LANGUAGES[lang_name]


def get_parser(lang_name: str) -> Optional[Parser]:
    """언어별 파서 반환 (싱글톤 패턴)

    Args:
        lang_name: 언어 이름 (예: 'python', 'javascript')

    Returns:
        Parser 객체 또는 None
    """
    if lang_name not in _PARSERS:
        language = _get_language(lang_name)
        if language:
            parser = Parser(language)
            _PARSERS[lang_name] = parser
        else:
            _PARSERS[lang_name] = None

    return _PARSERS[lang_name]


# 언어별 함수/클래스 노드 타입 매핑
NODE_TYPES = {
    'python': {
        'function': 'function_definition',
        'class': 'class_definition',
        'method': 'function_definition',  # 클래스 내부 함수
    },
    'javascript': {
        'function': 'function_declaration',
        'class': 'class_declaration',
        'method': 'method_definition',
        'arrow_function': 'arrow_function',
    },
    'typescript': {
        'function': 'function_declaration',
        'class': 'class_declaration',
        'method': 'method_definition',
        'interface': 'interface_declaration',
        'type_alias': 'type_alias_declaration',
    },
    'java': {
        'class': 'class_declaration',
        'method': 'method_declaration',
        'interface': 'interface_declaration',
    },
    'go': {
        'function': 'function_declaration',
        'method': 'method_declaration',
        'type': 'type_declaration',
    },
    'rust': {
        'function': 'function_item',
        'struct': 'struct_item',
        'impl': 'impl_item',
        'trait': 'trait_item',
    },
    'cpp': {
        'function': 'function_definition',
        'class': 'class_specifier',
        'struct': 'struct_specifier',
    },
    'c': {
        'function': 'function_definition',
        'struct': 'struct_specifier',
    },
    'csharp': {
        'class': 'class_declaration',
        'method': 'method_declaration',
        'interface': 'interface_declaration',
    },
    'ruby': {
        'function': 'method',
        'class': 'class',
        'module': 'module',
    },
    'php': {
        'function': 'function_definition',
        'class': 'class_declaration',
        'method': 'method_declaration',
    },
}


def _extract_node_name(node: Node) -> str:
    """노드에서 이름 추출 (함수명, 클래스명 등)"""
    # 'name' field 시도
    name_node = node.child_by_field_name('name')
    if name_node:
        return name_node.text.decode('utf8')

    # 자식 노드에서 identifier 찾기
    for child in node.children:
        if child.type == 'identifier':
            return child.text.decode('utf8')

    return 'anonymous'


def extract_functions_and_classes(
    code: str,
    language: str,
    max_chunk_lines: int = 200
) -> list[dict]:
    """함수/클래스 노드를 AST 기반으로 추출

    Args:
        code: 소스 코드
        language: 언어 이름
        max_chunk_lines: 최대 청크 줄 수 (초과 시 분할하지 않고 그대로 반환)

    Returns:
        청크 리스트 [{"code": str, "type": str, "name": str, "line_start": int, "line_end": int}, ...]
    """
    parser = get_parser(language)
    if not parser:
        logger.debug(f"Parser not available for {language}")
        return []

    try:
        tree = parser.parse(bytes(code, 'utf8'))
    except Exception as e:
        logger.error(f"Failed to parse code: {e}")
        return []

    chunks = []
    node_types = NODE_TYPES.get(language, {})
    target_types = set(node_types.values())

    def traverse(node: Node):
        """재귀적으로 노드 탐색"""
        # 목표 노드 타입이면 청크로 추출
        if node.type in target_types:
            name = _extract_node_name(node)
            chunk_code = code[node.start_byte:node.end_byte]
            line_start = node.start_point[0] + 1
            line_end = node.end_point[0] + 1

            chunks.append({
                'code': chunk_code,
                'type': node.type,
                'name': name,
                'line_start': line_start,
                'line_end': line_end,
            })

            # 클래스 내부 메서드도 탐색 (Python, Java 등)
            if node.type in ['class_definition', 'class_declaration', 'class_specifier']:
                for child in node.children:
                    traverse(child)
        else:
            # 자식 노드 계속 탐색
            for child in node.children:
                traverse(child)

    # 루트 노드부터 탐색 시작
    traverse(tree.root_node)

    logger.debug(f"Extracted {len(chunks)} chunks from {language} code")
    return chunks


def get_language_from_extension(file_extension: str) -> Optional[str]:
    """파일 확장자로부터 언어 이름 추론

    Args:
        file_extension: 파일 확장자 (예: '.py', '.js')

    Returns:
        언어 이름 또는 None
    """
    ext_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'tsx',
        '.java': 'java',
        '.go': 'go',
        '.rs': 'rust',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.c': 'c',
        '.h': 'c',
        '.hpp': 'cpp',
        '.cs': 'csharp',
        '.rb': 'ruby',
        '.php': 'php',
    }

    return ext_map.get(file_extension.lower())


def is_language_supported(file_extension: str) -> bool:
    """파일 확장자가 tree-sitter로 지원되는지 확인

    Args:
        file_extension: 파일 확장자 (예: '.py')

    Returns:
        지원 여부
    """
    language = get_language_from_extension(file_extension)
    if not language:
        return False

    return get_parser(language) is not None

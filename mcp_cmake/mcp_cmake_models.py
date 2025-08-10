from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class StructuredError:
    """構造化されたエラー情報を表現するデータクラス"""

    error_type: str  # "compile", "link", "test", "cmake"
    file_path: Optional[str]
    line_number: Optional[int]
    column_number: Optional[int]
    message: str
    context: List[str]  # 周辺のソースコード行
    suggestions: List[str]
    raw_output: str


@dataclass
class CommandResult:
    """コマンド実行結果を表現するデータクラス"""

    success: bool
    output: str
    error_output: str
    return_code: int
    execution_time: float
    structured_error: Optional[StructuredError] = None


@dataclass
class CompileError:
    """個別のコンパイルエラー情報"""

    file_path: str
    line_number: Optional[int]
    column_number: Optional[int]
    error_code: Optional[str]
    message: str
    severity: str  # "error", "warning", "note"


@dataclass
class TestFailure:
    """個別のテスト失敗情報"""

    test_name: str
    test_number: Optional[int]
    failure_type: str  # "failed", "timeout", "not_run"
    message: str
    execution_time: Optional[float]


@dataclass
class BuildErrorInfo:
    """ビルドエラーの構造化情報"""

    compiler: str
    error_count: int
    warning_count: int
    errors: List[CompileError]
    llm_summary: str
    raw_output: str
    command: str
    working_directory: str


@dataclass
class TestErrorInfo:
    """テストエラーの構造化情報"""

    total_tests: int
    failed_tests: int
    passed_tests: int
    failed_test_details: List[TestFailure]
    llm_summary: str
    raw_output: str
    command: str
    working_directory: str

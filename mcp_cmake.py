import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

import gradio as gr

# --- Constants ---
CMAKE_EXE = "cmake"


# --- Data Models ---
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


# --- Error Analysis Engine ---
class ErrorAnalyzer:
    """エラー解析エンジン - ビルドやテストエラーを構造化して解析する"""

    # エラーパターンの定義
    COMPILE_ERROR_PATTERNS = [
        # MSVC patterns
        (r"(.+?)\((\d+),(\d+)\):\s*error\s+C(\d+):\s*(.+)", "msvc_compile"),
        # GCC/Clang patterns
        (r"(.+?):(\d+):(\d+):\s*error:\s*(.+)", "gcc_compile"),
        # Generic compile error
        (r"(.+?):(\d+):\s*error:\s*(.+)", "generic_compile"),
    ]

    LINK_ERROR_PATTERNS = [
        # MSVC linker
        (r"(.+?)\s*:\s*error\s+LNK(\d+):\s*(.+)", "msvc_link"),
        # GCC/Clang linker
        (r"(.+?):\s*undefined reference to\s*(.+)", "gcc_link"),
        # Generic linker error
        (r"ld:\s*(.+)", "generic_link"),
    ]

    CMAKE_ERROR_PATTERNS = [
        # CMake configuration errors
        (r"CMake Error at (.+?):(\d+)\s*\((.+?)\):\s*(.+)", "cmake_config"),
        # CMake general errors
        (r"CMake Error:\s*(.+)", "cmake_general"),
    ]

    TEST_ERROR_PATTERNS = [
        # CTest test failures with ***Failed
        (r"(\d+)/\d+\s+Test\s+#(\d+):\s+(.+?)\s+\.+\*\*\*Failed", "test_failed"),
        # CTest timeout with ***Timeout
        (r"(\d+)/\d+\s+Test\s+#(\d+):\s+(.+?)\s+\.+\*\*\*Timeout", "test_timeout"),
        # CTest not run with ***Not Run
        (r"(\d+)/\d+\s+Test\s+#(\d+):\s+(.+?)\s+\.+\*\*\*Not Run", "test_not_run"),
        # Legacy patterns for backward compatibility
        (r"(\d+):\s*Test\s+(.+?)\s+.*Failed", "test_failed"),
        (r"(\d+):\s*Test\s+(.+?)\s+.*Timeout", "test_timeout"),
        (r"(\d+):\s*Test\s+(.+?)\s+.*Not Run", "test_not_run"),
        # Generic test error
        (r"Test\s+(.+?)\s+.*FAILED", "test_generic_failed"),
    ]

    def analyze_error(
        self, output: str, command_type: str = "build"
    ) -> Optional[StructuredError]:
        """エラー出力を解析して構造化されたエラー情報を生成する"""
        if not output or "[ERROR]" not in output:
            return None

        # エラータイプに応じてパターンを選択
        patterns = []
        if command_type == "build":
            patterns.extend(self.COMPILE_ERROR_PATTERNS)
            patterns.extend(self.LINK_ERROR_PATTERNS)
        elif command_type == "test":
            patterns.extend(self.TEST_ERROR_PATTERNS)
        patterns.extend(self.CMAKE_ERROR_PATTERNS)

        # パターンマッチングでエラーを解析
        for pattern, error_type in patterns:
            match = re.search(pattern, output, re.MULTILINE)
            if match:
                return self._create_structured_error(match, error_type, output)

        # パターンにマッチしない場合は汎用エラーとして処理
        return self._create_generic_error(output, command_type)

    def _create_structured_error(
        self, match, error_type: str, raw_output: str
    ) -> StructuredError:
        """マッチした正規表現から構造化エラーを作成する"""
        groups = match.groups()

        # エラータイプ別の処理
        if "compile" in error_type:
            file_path = groups[0] if len(groups) > 0 else None
            line_number = (
                int(groups[1]) if len(groups) > 1 and groups[1].isdigit() else None
            )
            column_number = (
                int(groups[2]) if len(groups) > 2 and groups[2].isdigit() else None
            )
            message = groups[-1] if groups else "Unknown compile error"
        elif "link" in error_type:
            file_path = groups[0] if len(groups) > 0 else None
            line_number = None
            column_number = None
            message = groups[-1] if groups else "Unknown link error"
        elif "cmake" in error_type:
            file_path = groups[0] if len(groups) > 0 else None
            line_number = (
                int(groups[1]) if len(groups) > 1 and groups[1].isdigit() else None
            )
            column_number = None
            message = groups[-1] if groups else "Unknown CMake error"
        else:
            file_path = None
            line_number = None
            column_number = None
            message = groups[0] if groups else "Unknown error"

        # コンテキストと提案を生成
        context = self._extract_context(raw_output, file_path, line_number)
        suggestions = self._generate_suggestions(error_type, message)

        return StructuredError(
            error_type=error_type,
            file_path=file_path,
            line_number=line_number,
            column_number=column_number,
            message=message,
            context=context,
            suggestions=suggestions,
            raw_output=raw_output,
        )

    def _create_generic_error(
        self, raw_output: str, command_type: str
    ) -> StructuredError:
        """汎用エラーを作成する"""
        # エラーメッセージを抽出
        error_lines = [line for line in raw_output.split("\n") if "[ERROR]" in line]
        message = error_lines[0] if error_lines else "Unknown error occurred"

        return StructuredError(
            error_type=f"{command_type}_generic",
            file_path=None,
            line_number=None,
            column_number=None,
            message=message,
            context=[],
            suggestions=self._generate_suggestions("generic", message),
            raw_output=raw_output,
        )

    def _extract_context(
        self, raw_output: str, file_path: Optional[str], line_number: Optional[int]
    ) -> List[str]:
        """エラー周辺のコンテキスト情報を抽出する"""
        context = []

        # ファイルパスと行番号がある場合、該当箇所の前後を取得
        if file_path and line_number:
            # 相対パスの場合は絶対パスに変換を試行
            full_path = file_path
            if not os.path.isabs(file_path):
                # 現在のディレクトリからの相対パス
                full_path = os.path.abspath(file_path)
                if not os.path.exists(full_path):
                    # sample ディレクトリからの相対パス
                    full_path = os.path.abspath(os.path.join("sample", file_path))

            if os.path.exists(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        start = max(0, line_number - 4)  # より多くのコンテキストを提供
                        end = min(len(lines), line_number + 3)

                        for i in range(start, end):
                            if i == line_number - 1:
                                prefix = ">>> "  # エラー行をハイライト
                            elif abs(i - (line_number - 1)) <= 1:
                                prefix = "  > "  # エラー行の近くをマーク
                            else:
                                prefix = "    "
                            context.append(f"{prefix}{i+1:4d}: {lines[i].rstrip()}")
                except Exception as e:
                    context.append(f"[Context extraction failed: {str(e)}]")
            else:
                context.append(f"[Source file not found: {file_path}]")

        # コンテキストが取得できない場合は、raw_outputから関連行を抽出
        if not context:
            output_lines = raw_output.split("\n")
            for i, line in enumerate(output_lines):
                if (
                    "error" in line.lower()
                    or "Error" in line
                    or "failed" in line.lower()
                ):
                    start = max(0, i - 3)
                    end = min(len(output_lines), i + 4)
                    context = [
                        f"    {j+1:4d}: {output_lines[j]}" for j in range(start, end)
                    ]
                    break

        return context[:15]  # 最大15行に拡張

    def extract_error_details(self, raw_output: str) -> Dict[str, Any]:
        """エラー出力から詳細な情報を抽出する（ファイル名、行番号、エラータイプ）"""
        details = {
            "files_with_errors": [],
            "error_types": [],
            "line_numbers": [],
            "error_count_by_type": {},
            "compiler_info": None,
            "build_target": None,
        }

        lines = raw_output.split("\n")

        # 全体のテキストでCMakeエラーを先に検索（マルチライン対応）
        cmake_multiline_pattern = r"CMake Error at (.+?):(\d+)\s*\((.+?)\):\s*\n\s*(.+?)(?=\n\n|\nCMake|\n[A-Z]|\Z)"
        cmake_multiline_matches = re.finditer(
            cmake_multiline_pattern, raw_output, re.MULTILINE | re.DOTALL
        )
        for match in cmake_multiline_matches:
            file_path, line_num, function, message = match.groups()
            details["files_with_errors"].append(
                {
                    "file": file_path.strip(),
                    "line": int(line_num),
                    "column": None,
                    "type": "cmake_error",
                    "code": function.strip(),
                    "message": message.strip().replace("\n", " "),
                }
            )
            details["error_types"].append("cmake_error")
            details["line_numbers"].append(int(line_num))

        for line in lines:
            # MSVC エラーパターン
            msvc_match = re.search(
                r"(.+?)\((\d+),(\d+)\):\s*(error|warning)\s+C(\d+):\s*(.+)", line
            )
            if msvc_match:
                file_path, line_num, col_num, severity, error_code, message = (
                    msvc_match.groups()
                )
                details["files_with_errors"].append(
                    {
                        "file": file_path.strip(),
                        "line": int(line_num),
                        "column": int(col_num),
                        "type": f"msvc_{severity}",
                        "code": f"C{error_code}",
                        "message": message.strip(),
                    }
                )
                details["error_types"].append(f"msvc_{severity}")
                details["line_numbers"].append(int(line_num))
                continue

            # GCC/Clang エラーパターン
            gcc_match = re.search(r"(.+?):(\d+):(\d+):\s*(error|warning):\s*(.+)", line)
            if gcc_match:
                file_path, line_num, col_num, severity, message = gcc_match.groups()
                details["files_with_errors"].append(
                    {
                        "file": file_path.strip(),
                        "line": int(line_num),
                        "column": int(col_num),
                        "type": f"gcc_{severity}",
                        "code": None,
                        "message": message.strip(),
                    }
                )
                details["error_types"].append(f"gcc_{severity}")
                details["line_numbers"].append(int(line_num))
                continue

            # CMake エラーパターン
            cmake_match = re.search(
                r"CMake Error at (.+?):(\d+)\s*\((.+?)\):\s*(.+)", line
            )
            if cmake_match:
                file_path, line_num, function, message = cmake_match.groups()
                details["files_with_errors"].append(
                    {
                        "file": file_path.strip(),
                        "line": int(line_num),
                        "column": None,
                        "type": "cmake_error",
                        "code": function,
                        "message": message.strip(),
                    }
                )
                details["error_types"].append("cmake_error")
                details["line_numbers"].append(int(line_num))
                continue

            # CMake 一般エラーパターン
            cmake_general_match = re.search(r"CMake Error:\s*(.+)", line)
            if cmake_general_match:
                message = cmake_general_match.group(1)
                details["files_with_errors"].append(
                    {
                        "file": "CMake",
                        "line": None,
                        "column": None,
                        "type": "cmake_general_error",
                        "code": None,
                        "message": message.strip(),
                    }
                )
                details["error_types"].append("cmake_general_error")
                continue

            # コンパイラ情報の抽出
            if "Microsoft (R) C/C++ Optimizing Compiler" in line:
                details["compiler_info"] = "MSVC"
            elif "gcc version" in line.lower() or "g++ " in line.lower():
                details["compiler_info"] = "GCC"
            elif "clang version" in line.lower():
                details["compiler_info"] = "Clang"

            # ビルドターゲット情報の抽出
            if "Building CXX object" in line:
                target_match = re.search(r"Building CXX object (.+?)\.dir", line)
                if target_match:
                    details["build_target"] = target_match.group(1)

        # エラータイプ別の集計
        for error_type in details["error_types"]:
            details["error_count_by_type"][error_type] = (
                details["error_count_by_type"].get(error_type, 0) + 1
            )

        # 重複を除去
        details["error_types"] = list(set(details["error_types"]))
        details["line_numbers"] = sorted(list(set(details["line_numbers"])))

        return details

    def get_source_context_enhanced(
        self, file_path: str, line_number: int, context_lines: int = 5
    ) -> Dict[str, Any]:
        """指定されたファイルの指定行周辺のソースコードコンテキストを取得する"""
        context_info = {
            "file_path": file_path,
            "line_number": line_number,
            "file_exists": False,
            "context_lines": [],
            "file_language": None,
            "total_lines": 0,
            "error_line_content": None,
        }

        # ファイル拡張子から言語を推定
        ext = os.path.splitext(file_path)[1].lower()
        language_map = {
            ".cpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
            ".c": "c",
            ".h": "c",
            ".hpp": "cpp",
            ".hxx": "cpp",
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".cmake": "cmake",
        }
        context_info["file_language"] = language_map.get(ext, "text")

        # ファイルパスの解決
        full_path = file_path
        if not os.path.isabs(file_path):
            full_path = os.path.abspath(file_path)
            if not os.path.exists(full_path):
                full_path = os.path.abspath(os.path.join("sample", file_path))

        if os.path.exists(full_path):
            context_info["file_exists"] = True
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    context_info["total_lines"] = len(lines)

                    start = max(0, line_number - context_lines - 1)
                    end = min(len(lines), line_number + context_lines)

                    for i in range(start, end):
                        line_content = lines[i].rstrip()
                        is_error_line = i == line_number - 1

                        if is_error_line:
                            context_info["error_line_content"] = line_content

                        context_info["context_lines"].append(
                            {
                                "line_number": i + 1,
                                "content": line_content,
                                "is_error_line": is_error_line,
                                "distance_from_error": abs(i - (line_number - 1)),
                            }
                        )
            except Exception as e:
                context_info["error"] = str(e)

        return context_info

    def _generate_suggestions(self, error_type: str, message: str) -> List[str]:
        """エラータイプとメッセージに基づいて解決提案を生成する"""
        suggestions = []

        if "compile" in error_type:
            if "undeclared" in message.lower() or "not declared" in message.lower():
                suggestions.extend(
                    [
                        "Check if the variable/function is declared in the current scope",
                        "Verify that necessary header files are included",
                        "Check for typos in variable/function names",
                    ]
                )
            elif "syntax" in message.lower():
                suggestions.extend(
                    [
                        "Check for missing semicolons or brackets",
                        "Verify proper syntax according to language standards",
                        "Check for unmatched parentheses or braces",
                    ]
                )
            else:
                suggestions.append(
                    "Review the compiler error message for specific guidance"
                )

        elif "link" in error_type:
            if "undefined reference" in message.lower():
                suggestions.extend(
                    [
                        "Check if the referenced function/variable is implemented",
                        "Verify that all necessary libraries are linked",
                        "Check for missing object files in the build",
                    ]
                )
            else:
                suggestions.append("Review linker settings and dependencies")

        elif "cmake" in error_type:
            suggestions.extend(
                [
                    "Check CMakeLists.txt syntax and configuration",
                    "Verify that all required dependencies are available",
                    "Check CMake version compatibility",
                ]
            )

        else:
            suggestions.append("Review the full error output for more details")

        return suggestions

    def format_comprehensive_error_for_llm(
        self,
        raw_output: str,
        command_type: str = "build",
        command: str = "",
        working_dir: str = "",
    ) -> str:
        """包括的なエラー解析とLLM向けフォーマット出力"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 詳細なエラー情報を抽出
        error_details = self.extract_error_details(raw_output)

        output = f"=== COMPREHENSIVE ERROR ANALYSIS FOR LLM ===\n"
        output += f"Analysis Timestamp: {timestamp}\n"
        output += f"Command Type: {command_type}\n"
        output += f"Command Executed: {command}\n"
        output += f"Working Directory: {working_dir}\n\n"

        # エラー統計
        output += f"ERROR STATISTICS:\n"
        output += (
            f"  Total Files with Errors: {len(error_details['files_with_errors'])}\n"
        )
        output += f"  Unique Error Types: {len(error_details['error_types'])}\n"
        output += f"  Lines with Errors: {len(error_details['line_numbers'])}\n"

        if error_details["error_count_by_type"]:
            output += f"  Error Count by Type:\n"
            for error_type, count in error_details["error_count_by_type"].items():
                output += f"    - {error_type}: {count}\n"

        if error_details["compiler_info"]:
            output += f"  Compiler: {error_details['compiler_info']}\n"

        if error_details["build_target"]:
            output += f"  Build Target: {error_details['build_target']}\n"

        output += "\n"

        # 個別エラーの詳細
        if error_details["files_with_errors"]:
            output += f"DETAILED ERROR BREAKDOWN:\n"
            for i, error in enumerate(
                error_details["files_with_errors"][:10], 1
            ):  # 最初の10個
                output += f"\n{i}. Error in {error['file']}\n"
                output += f"   Location: Line {error['line']}"
                if error["column"]:
                    output += f", Column {error['column']}"
                output += f"\n"
                output += f"   Type: {error['type']}\n"
                if error["code"]:
                    output += f"   Error Code: {error['code']}\n"
                output += f"   Message: {error['message']}\n"

                # ソースコードコンテキストを取得
                context_info = self.get_source_context_enhanced(
                    error["file"], error["line"]
                )
                if context_info["file_exists"] and context_info["context_lines"]:
                    output += f"   Source Context ({context_info['file_language']}):\n"
                    output += f"   ```{context_info['file_language']}\n"
                    for line_info in context_info["context_lines"]:
                        marker = ">>> " if line_info["is_error_line"] else "    "
                        output += f"   {marker}{line_info['line_number']:4d}: {line_info['content']}\n"
                    output += f"   ```\n"
                elif not context_info["file_exists"]:
                    output += (
                        f"   Source Context: File not accessible ({error['file']})\n"
                    )

            if len(error_details["files_with_errors"]) > 10:
                output += f"\n... and {len(error_details['files_with_errors']) - 10} more errors\n"

        # 解決提案
        output += f"\nRECOMMENDED ACTIONS:\n"
        suggestions = []

        # エラータイプ別の提案
        for error_type in error_details["error_types"]:
            if "compile" in error_type:
                suggestions.extend(
                    [
                        "Check for syntax errors and missing semicolons",
                        "Verify all required header files are included",
                        "Check for undeclared variables and functions",
                    ]
                )
            elif "link" in error_type:
                suggestions.extend(
                    [
                        "Verify all required libraries are linked",
                        "Check for missing function implementations",
                        "Review library paths and dependencies",
                    ]
                )
            elif "cmake" in error_type:
                suggestions.extend(
                    [
                        "Check CMakeLists.txt syntax and configuration",
                        "Verify CMake version compatibility",
                        "Check for missing dependencies and packages",
                    ]
                )

        # 重複を除去して表示
        unique_suggestions = list(dict.fromkeys(suggestions))
        for i, suggestion in enumerate(unique_suggestions[:8], 1):  # 最大8個
            output += f"  {i}. {suggestion}\n"

        # 生の出力（制限付き）
        output += f"\nRAW OUTPUT (last 2000 characters):\n"
        output += "```\n"
        raw_output_trimmed = (
            raw_output[-2000:] if len(raw_output) > 2000 else raw_output
        )
        output += raw_output_trimmed
        if not raw_output_trimmed.endswith("\n"):
            output += "\n"
        output += "```\n"

        output += "=== END COMPREHENSIVE ANALYSIS ===\n"

        return output

    def analyze_build_errors(
        self, output: str, command: str = "", working_dir: str = ""
    ) -> BuildErrorInfo:
        """ビルドエラーを構造化して解析する"""
        errors = []
        error_count = 0
        warning_count = 0
        compiler = "Unknown"

        # コンパイラの特定
        if "MSVC" in output or "Microsoft" in output:
            compiler = "MSVC"
        elif "gcc" in output.lower() or "g++" in output.lower():
            compiler = "GCC"
        elif "clang" in output.lower():
            compiler = "Clang"

        # エラーと警告をパース
        lines = output.split("\n")
        for line in lines:
            # MSVC エラーパターン
            msvc_match = re.search(
                r"(.+?)\((\d+),(\d+)\):\s*(error|warning)\s+C(\d+):\s*(.+)", line
            )
            if msvc_match:
                file_path, line_num, col_num, severity, error_code, message = (
                    msvc_match.groups()
                )
                errors.append(
                    CompileError(
                        file_path=file_path.strip(),
                        line_number=int(line_num),
                        column_number=int(col_num),
                        error_code=f"C{error_code}",
                        message=message.strip(),
                        severity=severity,
                    )
                )
                if severity == "error":
                    error_count += 1
                else:
                    warning_count += 1
                continue

            # GCC/Clang エラーパターン
            gcc_match = re.search(r"(.+?):(\d+):(\d+):\s*(error|warning):\s*(.+)", line)
            if gcc_match:
                file_path, line_num, col_num, severity, message = gcc_match.groups()
                errors.append(
                    CompileError(
                        file_path=file_path.strip(),
                        line_number=int(line_num),
                        column_number=int(col_num),
                        error_code=None,
                        message=message.strip(),
                        severity=severity,
                    )
                )
                if severity == "error":
                    error_count += 1
                else:
                    warning_count += 1
                continue

            # 汎用エラーカウント
            if "error" in line.lower() and ("C" in line or "error:" in line):
                error_count += 1
            elif "warning" in line.lower() and ("C" in line or "warning:" in line):
                warning_count += 1

        # LLMサマリーを生成
        llm_summary = self._generate_build_summary(
            errors, error_count, warning_count, compiler
        )

        return BuildErrorInfo(
            compiler=compiler,
            error_count=error_count,
            warning_count=warning_count,
            errors=errors,
            llm_summary=llm_summary,
            raw_output=output,
            command=command,
            working_directory=working_dir,
        )

    def analyze_test_errors(
        self, output: str, command: str = "", working_dir: str = ""
    ) -> TestErrorInfo:
        """テストエラーを構造化して解析する"""
        failed_tests = []
        total_tests = 0
        failed_count = 0
        passed_count = 0

        # CTest出力をパース
        lines = output.split("\n")
        for line in lines:
            # 新しいCTest形式のパターンマッチング (例: 2/3 Test #2: AdvancedTest ...***Failed)
            test_match = re.search(
                r"(\d+)/\d+\s+Test\s+#(\d+):\s+(.+?)\s+\.+(.+)", line
            )
            if test_match:
                test_seq, test_num, test_name, result = test_match.groups()
                total_tests = max(total_tests, int(test_seq))

                # 実行時間を抽出
                time_match = re.search(r"(\d+\.\d+)\s+sec", result)
                execution_time = float(time_match.group(1)) if time_match else None

                if "***Failed" in result:
                    failed_count += 1
                    failed_tests.append(
                        TestFailure(
                            test_name=test_name.strip(),
                            test_number=int(test_num),
                            failure_type="failed",
                            message=result.strip(),
                            execution_time=execution_time,
                        )
                    )
                elif "***Timeout" in result:
                    failed_count += 1
                    failed_tests.append(
                        TestFailure(
                            test_name=test_name.strip(),
                            test_number=int(test_num),
                            failure_type="timeout",
                            message=result.strip(),
                            execution_time=execution_time,
                        )
                    )
                elif "***Not Run" in result:
                    failed_tests.append(
                        TestFailure(
                            test_name=test_name.strip(),
                            test_number=int(test_num),
                            failure_type="not_run",
                            message=result.strip(),
                            execution_time=execution_time,
                        )
                    )
                elif "Passed" in result:
                    passed_count += 1
                continue

            # 従来形式のパターンマッチング (後方互換性のため)
            legacy_match = re.search(r"(\d+):\s*Test\s+(.+?)\s+\.\.\.\s*(.+)", line)
            if legacy_match:
                test_num, test_name, result = legacy_match.groups()
                total_tests += 1

                if "Failed" in result:
                    failed_count += 1
                    failed_tests.append(
                        TestFailure(
                            test_name=test_name.strip(),
                            test_number=int(test_num),
                            failure_type="failed",
                            message=result.strip(),
                            execution_time=None,
                        )
                    )
                elif "Timeout" in result:
                    failed_count += 1
                    failed_tests.append(
                        TestFailure(
                            test_name=test_name.strip(),
                            test_number=int(test_num),
                            failure_type="timeout",
                            message=result.strip(),
                            execution_time=None,
                        )
                    )
                elif "Not Run" in result:
                    failed_tests.append(
                        TestFailure(
                            test_name=test_name.strip(),
                            test_number=int(test_num),
                            failure_type="not_run",
                            message=result.strip(),
                            execution_time=None,
                        )
                    )
                else:
                    passed_count += 1

        # テスト統計の抽出
        stats_match = re.search(
            r"(\d+)% tests passed, (\d+) tests failed out of (\d+)", output
        )
        if stats_match:
            failed_count = int(stats_match.group(2))
            total_tests = int(stats_match.group(3))
            passed_count = total_tests - failed_count

        # LLMサマリーを生成
        llm_summary = self._generate_test_summary(
            failed_tests, total_tests, failed_count, passed_count
        )

        return TestErrorInfo(
            total_tests=total_tests,
            failed_tests=failed_count,
            passed_tests=passed_count,
            failed_test_details=failed_tests,
            llm_summary=llm_summary,
            raw_output=output,
            command=command,
            working_directory=working_dir,
        )

    def _generate_build_summary(
        self,
        errors: List[CompileError],
        error_count: int,
        warning_count: int,
        compiler: str,
    ) -> str:
        """ビルドエラーのLLMサマリーを生成"""
        summary = f"Build failed with {error_count} error(s) and {warning_count} warning(s) using {compiler} compiler.\n\n"

        if errors:
            summary += "Key Issues:\n"
            for i, error in enumerate(errors[:5], 1):  # 最初の5つのエラーのみ
                summary += f"{i}. {error.file_path}"
                if error.line_number:
                    summary += f":{error.line_number}"
                summary += f" - {error.message}\n"

            if len(errors) > 5:
                summary += f"... and {len(errors) - 5} more errors\n"

        return summary

    def _generate_test_summary(
        self, failed_tests: List[TestFailure], total: int, failed: int, passed: int
    ) -> str:
        """テストエラーのLLMサマリーを生成"""
        if failed == 0:
            return f"All {total} tests passed successfully."

        summary = f"Test execution completed: {passed}/{total} tests passed, {failed} failed.\n\n"

        if failed_tests:
            summary += "Failed Tests:\n"
            for i, test in enumerate(
                failed_tests[:10], 1
            ):  # 最初の10個の失敗テストのみ
                summary += (
                    f"{i}. {test.test_name} ({test.failure_type}): {test.message}\n"
                )

            if len(failed_tests) > 10:
                summary += f"... and {len(failed_tests) - 10} more failed tests\n"

        return summary

    def format_for_llm(self, error: StructuredError) -> str:
        """エラー情報をLLM向けの形式でフォーマットする"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # エラータイプの分類と説明
        error_type_descriptions = {
            "msvc_compile": "MSVC Compilation Error",
            "gcc_compile": "GCC/G++ Compilation Error",
            "clang_compile": "Clang Compilation Error",
            "msvc_link": "MSVC Linker Error",
            "gcc_link": "GCC/G++ Linker Error",
            "cmake_config": "CMake Configuration Error",
            "cmake_general": "CMake General Error",
            "test_failed": "Test Execution Failed",
            "test_timeout": "Test Execution Timeout",
            "test_not_run": "Test Not Executed",
        }

        error_description = error_type_descriptions.get(
            error.error_type, f"Unknown Error ({error.error_type})"
        )

        output = f"=== ERROR ANALYSIS FOR LLM ===\n"
        output += f"Timestamp: {timestamp}\n"
        output += f"Error Classification: {error_description}\n"
        output += f"Error Type Code: {error.error_type}\n"

        # ファイル情報の詳細表示
        if error.file_path:
            output += f"\nFile Information:\n"
            output += f"  File Path: {error.file_path}\n"
            if error.line_number:
                output += f"  Line Number: {error.line_number}\n"
                if error.column_number:
                    output += f"  Column Number: {error.column_number}\n"

            # ファイル存在確認
            file_exists = os.path.exists(error.file_path)
            if not file_exists and not os.path.isabs(error.file_path):
                # 相対パスの場合、sample ディレクトリも確認
                sample_path = os.path.join("sample", error.file_path)
                file_exists = os.path.exists(sample_path)
            output += f"  File Exists: {'Yes' if file_exists else 'No'}\n"

        output += f"\nError Message:\n{error.message}\n"

        # ソースコードコンテキストの表示
        if error.context:
            output += f"\nSource Code Context:\n"
            if any(">>>" in line for line in error.context):
                output += "```cpp\n"  # C++コードと仮定
            else:
                output += "```\n"
            for line in error.context:
                output += f"{line}\n"
            output += "```\n"
        else:
            output += f"\nSource Code Context: Not available\n"

        # 解決提案の表示
        if error.suggestions:
            output += f"\nRecommended Solutions:\n"
            for i, suggestion in enumerate(error.suggestions, 1):
                output += f"  {i}. {suggestion}\n"

        # 追加の診断情報
        output += f"\nDiagnostic Information:\n"
        output += f"  Error Pattern Matched: {error.error_type}\n"
        output += f"  Context Lines Available: {len(error.context)}\n"
        output += f"  Suggestions Provided: {len(error.suggestions)}\n"

        # 生の出力（制限付き）
        output += f"\nRaw Error Output (last 1200 chars):\n"
        output += "```\n"
        raw_output_trimmed = (
            error.raw_output[-1200:]
            if len(error.raw_output) > 1200
            else error.raw_output
        )
        output += raw_output_trimmed
        if not raw_output_trimmed.endswith("\n"):
            output += "\n"
        output += "```\n"

        output += "=== END ERROR ANALYSIS ===\n"

        return output

    def format_build_error_for_llm(self, build_error: BuildErrorInfo) -> str:
        """ビルドエラー情報をLLM向けの形式でフォーマットする"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        output = f"=== BUILD ERROR ANALYSIS ===\n"
        output += f"Timestamp: {timestamp}\n"
        output += f"Compiler: {build_error.compiler}\n"
        output += f"Error Count: {build_error.error_count}\n"
        output += f"Warning Count: {build_error.warning_count}\n"
        output += f"Command: {build_error.command}\n"
        output += f"Working Directory: {build_error.working_directory}\n\n"

        output += f"Summary:\n{build_error.llm_summary}\n"

        if build_error.errors:
            output += "Detailed Errors:\n"
            for i, error in enumerate(build_error.errors[:10], 1):
                output += f"{i}. File: {error.file_path}"
                if error.line_number:
                    output += f":{error.line_number}"
                    if error.column_number:
                        output += f":{error.column_number}"
                output += f"\n   Severity: {error.severity}\n"
                if error.error_code:
                    output += f"   Code: {error.error_code}\n"
                output += f"   Message: {error.message}\n\n"

        output += "Raw Output (last 1500 chars):\n"
        output += "```\n"
        output += build_error.raw_output[-1500:]
        output += "\n```\n"
        output += "=== END ANALYSIS ===\n"

        return output

    def format_test_error_for_llm(self, test_error: TestErrorInfo) -> str:
        """テストエラー情報をLLM向けの形式でフォーマットする"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        output = f"=== TEST ERROR ANALYSIS ===\n"
        output += f"Timestamp: {timestamp}\n"
        output += f"Total Tests: {test_error.total_tests}\n"
        output += f"Passed Tests: {test_error.passed_tests}\n"
        output += f"Failed Tests: {test_error.failed_tests}\n"
        output += f"Command: {test_error.command}\n"
        output += f"Working Directory: {test_error.working_directory}\n\n"

        output += f"Summary:\n{test_error.llm_summary}\n"

        if test_error.failed_test_details:
            output += "Failed Test Details:\n"
            for i, test in enumerate(test_error.failed_test_details[:15], 1):
                output += f"{i}. Test: {test.test_name}\n"
                output += f"   Type: {test.failure_type}\n"
                output += f"   Message: {test.message}\n"
                if test.execution_time:
                    output += f"   Execution Time: {test.execution_time}s\n"
                output += "\n"

        output += "Raw Output (last 1500 chars):\n"
        output += "```\n"
        output += test_error.raw_output[-1500:]
        output += "\n```\n"
        output += "=== END ANALYSIS ===\n"

        return output


# --- Command Execution ---
def execute_command(command_list, working_dir):
    """指定されたコマンドを実行し、出力をストリーミングするジェネレータ"""
    try:
        # Ensure the working directory exists
        if not os.path.isdir(working_dir):
            yield f"[ERROR] Working directory not found: {os.path.abspath(working_dir)}"
            return

        process = subprocess.Popen(
            command_list,
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = ""
        # Stream output
        for line in iter(process.stdout.readline, ""):
            output += line
            yield output

        process.stdout.close()
        rc = process.wait()
        if rc != 0:
            output += f"\n[ERROR] Process exited with return code: {rc}"
            yield output

    except FileNotFoundError:
        yield f"[ERROR] Command '{command_list[0]}' not found. Is it installed and in the system's PATH?"
    except Exception as e:
        yield f"[ERROR] An unexpected error occurred: {e}"


def execute_command_with_analysis(
    command_list, working_dir, command_type="build"
) -> Iterator[str]:
    """コマンドを実行し、エラー解析機能付きで出力をストリーミングする"""
    import time

    start_time = time.time()

    try:
        # Ensure the working directory exists
        if not os.path.isdir(working_dir):
            error_msg = (
                f"[ERROR] Working directory not found: {os.path.abspath(working_dir)}"
            )
            yield error_msg
            return

        process = subprocess.Popen(
            command_list,
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        output = ""
        error_output = ""

        # Stream output
        for line in iter(process.stdout.readline, ""):
            output += line
            yield output

        process.stdout.close()
        rc = process.wait()
        execution_time = time.time() - start_time

        # エラーが発生した場合の処理
        if rc != 0:
            error_msg = f"\n[ERROR] Process exited with return code: {rc}"
            output += error_msg
            error_output = output

            # エラー解析を実行
            analyzer = ErrorAnalyzer()
            structured_error = analyzer.analyze_error(output, command_type)

            if structured_error:
                # LLM向けフォーマット出力を追加
                llm_format = analyzer.format_for_llm(structured_error)
                output += f"\n\n=== LLM-READY ERROR ANALYSIS ===\n{llm_format}"

                # 包括的なエラー解析も追加
                comprehensive_format = analyzer.format_comprehensive_error_for_llm(
                    output, command_type, " ".join(command_list), working_dir
                )
                output += f"\n\n{comprehensive_format}"

            # 詳細なエラー解析（ビルドまたはテスト用）
            if command_type == "build":
                build_error = analyzer.analyze_build_errors(
                    output, " ".join(command_list), working_dir
                )
                if build_error.error_count > 0:
                    build_llm_format = analyzer.format_build_error_for_llm(build_error)
                    output += (
                        f"\n\n=== DETAILED BUILD ERROR ANALYSIS ===\n{build_llm_format}"
                    )
            elif command_type == "test":
                test_error = analyzer.analyze_test_errors(
                    output, " ".join(command_list), working_dir
                )
                if test_error.failed_tests > 0:
                    test_llm_format = analyzer.format_test_error_for_llm(test_error)
                    output += (
                        f"\n\n=== DETAILED TEST ERROR ANALYSIS ===\n{test_llm_format}"
                    )

            yield output

        # CommandResult オブジェクトを作成（将来の拡張用）
        analyzer = ErrorAnalyzer()
        result = CommandResult(
            success=(rc == 0),
            output=output,
            error_output=error_output,
            return_code=rc,
            execution_time=execution_time,
            structured_error=(
                analyzer.analyze_error(output, command_type) if rc != 0 else None
            ),
        )

    except FileNotFoundError:
        error_msg = f"[ERROR] Command '{command_list[0]}' not found. Is it installed and in the system's PATH?"
        yield error_msg
    except Exception as e:
        error_msg = f"[ERROR] An unexpected error occurred: {e}"
        yield error_msg


# --- Error Analysis API ---
def analyze_error_output(error_output: str, error_type: str = "build") -> str:
    """エラー出力を解析してLLM向けフォーマットで返す"""
    if not error_output.strip():
        return "No error output provided for analysis."

    analyzer = ErrorAnalyzer()

    # 基本的な構造化エラー解析
    structured_error = analyzer.analyze_error(error_output, error_type)
    result = ""

    if structured_error:
        result += analyzer.format_for_llm(structured_error)
        result += "\n\n"

    # 詳細な解析（エラータイプ別）
    if error_type == "build":
        build_error = analyzer.analyze_build_errors(error_output)
        if build_error.error_count > 0 or build_error.warning_count > 0:
            result += analyzer.format_build_error_for_llm(build_error)
        else:
            result += "No build errors detected in the output."
    elif error_type == "test":
        test_error = analyzer.analyze_test_errors(error_output)
        if test_error.failed_tests > 0:
            result += analyzer.format_test_error_for_llm(test_error)
        else:
            result += "No test failures detected in the output."
    elif error_type == "cmake":
        if structured_error:
            result += "CMake configuration error detected. See analysis above."
        else:
            result += "No CMake configuration errors detected in the output."

    if not result.strip():
        result = f"No structured error patterns found in the output.\n\nRaw output:\n{error_output}"

    return result


def analyze_build_error_detailed(
    error_output: str, command: str = "", working_dir: str = ""
) -> str:
    """ビルドエラーの詳細解析を実行してLLM向けフォーマットで返す"""
    if not error_output.strip():
        return "No build error output provided for analysis."

    analyzer = ErrorAnalyzer()
    build_error = analyzer.analyze_build_errors(error_output, command, working_dir)

    if build_error.error_count > 0 or build_error.warning_count > 0:
        return analyzer.format_build_error_for_llm(build_error)
    else:
        return "No build errors detected in the output."


def analyze_test_error_detailed(
    error_output: str, command: str = "", working_dir: str = ""
) -> str:
    """テストエラーの詳細解析を実行してLLM向けフォーマットで返す"""
    if not error_output.strip():
        return "No test error output provided for analysis."

    analyzer = ErrorAnalyzer()
    test_error = analyzer.analyze_test_errors(error_output, command, working_dir)

    if test_error.failed_tests > 0:
        return analyzer.format_test_error_for_llm(test_error)
    else:
        return "No test failures detected in the output."


def format_error_for_llm_analysis(
    error_output: str,
    error_type: str = "build",
    command: str = "",
    working_dir: str = "",
) -> str:
    """エラー出力をLLM解析用に包括的にフォーマットする"""
    if not error_output.strip():
        return "No error output provided for LLM analysis."

    analyzer = ErrorAnalyzer()
    return analyzer.format_comprehensive_error_for_llm(
        error_output, error_type, command, working_dir
    )


def extract_error_metadata(error_output: str) -> Dict[str, Any]:
    """エラー出力からメタデータを抽出する（ファイル名、行番号、エラータイプ等）"""
    if not error_output.strip():
        return {"error": "No error output provided"}

    analyzer = ErrorAnalyzer()
    return analyzer.extract_error_details(error_output)


def get_source_code_context(
    file_path: str, line_number: int, context_lines: int = 5
) -> Dict[str, Any]:
    """指定されたファイルの指定行周辺のソースコードコンテキストを取得する"""
    analyzer = ErrorAnalyzer()
    return analyzer.get_source_context_enhanced(file_path, line_number, context_lines)


def get_error_statistics(
    error_output: str, error_type: str = "build"
) -> Dict[str, Any]:
    """エラー統計情報を取得する"""
    if not error_output.strip():
        return {"error": "No error output provided"}

    analyzer = ErrorAnalyzer()

    if error_type == "build":
        build_error = analyzer.analyze_build_errors(error_output)
        return {
            "type": "build",
            "compiler": build_error.compiler,
            "error_count": build_error.error_count,
            "warning_count": build_error.warning_count,
            "total_issues": build_error.error_count + build_error.warning_count,
            "has_errors": build_error.error_count > 0,
            "summary": build_error.llm_summary,
        }
    elif error_type == "test":
        test_error = analyzer.analyze_test_errors(error_output)
        return {
            "type": "test",
            "total_tests": test_error.total_tests,
            "passed_tests": test_error.passed_tests,
            "failed_tests": test_error.failed_tests,
            "success_rate": (
                (test_error.passed_tests / test_error.total_tests * 100)
                if test_error.total_tests > 0
                else 0
            ),
            "has_failures": test_error.failed_tests > 0,
            "summary": test_error.llm_summary,
        }
    else:
        structured_error = analyzer.analyze_error(error_output, error_type)
        return {
            "type": error_type,
            "has_error": structured_error is not None,
            "error_type": structured_error.error_type if structured_error else None,
            "message": (
                structured_error.message if structured_error else "No errors detected"
            ),
        }


def get_error_statistics_ui(error_output: str, error_type: str = "build") -> tuple:
    """エラー統計情報をUI用に取得する"""
    if not error_output.strip():
        empty_stats = {"message": "No error output provided"}
        return empty_stats, empty_stats, "No error output provided for analysis."

    # 詳細統計を取得
    stats = get_error_statistics(error_output, error_type)

    # エラー詳細情報を取得
    analyzer = ErrorAnalyzer()
    error_details = analyzer.extract_error_details(error_output)

    # 統計情報を表示用に整理
    display_stats = {
        "error_type": error_type,
        "total_files_with_errors": len(error_details.get("files_with_errors", [])),
        "unique_error_types": len(error_details.get("error_types", [])),
        "error_count_by_type": error_details.get("error_count_by_type", {}),
        "compiler_info": error_details.get("compiler_info", "Unknown"),
        "build_target": error_details.get("build_target", "Unknown"),
    }

    # サマリーテキストを生成
    summary_text = f"Error Analysis Summary:\n"
    summary_text += f"- Error Type: {error_type}\n"
    summary_text += (
        f"- Files with Errors: {len(error_details.get('files_with_errors', []))}\n"
    )
    summary_text += (
        f"- Unique Error Types: {len(error_details.get('error_types', []))}\n"
    )

    if error_details.get("compiler_info"):
        summary_text += f"- Compiler: {error_details['compiler_info']}\n"

    if error_details.get("error_count_by_type"):
        summary_text += f"- Error Count by Type:\n"
        for err_type, count in error_details["error_count_by_type"].items():
            summary_text += f"  * {err_type}: {count}\n"

    # エラータイプ別の詳細
    if error_details.get("files_with_errors"):
        summary_text += f"\nFiles with Errors:\n"
        for i, error in enumerate(
            error_details["files_with_errors"][:5], 1
        ):  # 最初の5個
            summary_text += f"{i}. {error['file']}"
            if error.get("line"):
                summary_text += f" (Line {error['line']})"
            summary_text += f": {error['message'][:100]}...\n"

        if len(error_details["files_with_errors"]) > 5:
            summary_text += (
                f"... and {len(error_details['files_with_errors']) - 5} more errors\n"
            )

    return display_stats, display_stats, summary_text


def copy_analysis_to_clipboard(analysis_text: str) -> str:
    """分析結果をクリップボードにコピーする（UI用メッセージ）"""
    if not analysis_text.strip():
        return "No analysis text to copy."

    # Note: 実際のクリップボードへのコピーはブラウザ側で行う必要があります
    # ここではユーザーに手動コピーを促すメッセージを返します
    return f"Analysis ready for copying! ({len(analysis_text)} characters)"


def filter_errors_by_type(error_output: str, filter_type: str = "all") -> str:
    """エラータイプ別にフィルタリングされたエラー出力を返す"""
    if not error_output.strip():
        return "No error output provided for filtering."

    if filter_type == "all":
        return error_output

    analyzer = ErrorAnalyzer()
    error_details = analyzer.extract_error_details(error_output)

    filtered_lines = []
    lines = error_output.split("\n")

    for line in lines:
        include_line = False

        if filter_type == "compile_errors":
            if any(
                pattern in line.lower()
                for pattern in ["error c", "error:", "compilation terminated"]
            ):
                include_line = True
        elif filter_type == "link_errors":
            if any(
                pattern in line.lower()
                for pattern in ["error lnk", "undefined reference", "ld:"]
            ):
                include_line = True
        elif filter_type == "cmake_errors":
            if any(
                pattern in line.lower() for pattern in ["cmake error", "cmake warning"]
            ):
                include_line = True
        elif filter_type == "warnings":
            if any(pattern in line.lower() for pattern in ["warning c", "warning:"]):
                include_line = True

        if include_line:
            filtered_lines.append(line)

    if not filtered_lines:
        return f"No {filter_type} found in the error output."

    return "\n".join(filtered_lines)


def test_project(
    preset: str = "",
    working_dir: str = "sample",
    verbose: bool = False,
    test_filter: str = "",
    parallel_jobs: int = None,
):
    """CTest実行機能（エラー解析機能付き）- 拡張オプション対応"""
    if not working_dir:
        yield "Please specify a working directory."
        return

    # CTestコマンドを構築
    command = ["ctest"]

    # プリセットが指定されている場合
    if preset:
        command.extend(["--preset", preset])
    else:
        # プリセットが指定されていない場合は、ビルドディレクトリを推測
        build_dir = os.path.join(working_dir, "build")
        if os.path.exists(build_dir):
            command.extend(["--test-dir", build_dir])
        else:
            yield "[INFO] No test preset specified and no build directory found. Running ctest in working directory."

    # Verboseオプション
    if verbose:
        command.append("--verbose")

    # テストフィルター機能の追加
    if test_filter and test_filter.strip():
        # CTestでは-Rオプションで正規表現によるテストフィルタリングが可能
        command.extend(["-R", test_filter.strip()])
        yield f"[INFO] Applying test filter: {test_filter.strip()}"

    # 並列テスト実行オプションの追加
    if parallel_jobs and parallel_jobs > 0:
        # CTestでは-jオプションで並列実行ジョブ数を指定
        command.extend(["-j", str(parallel_jobs)])
        yield f"[INFO] Running tests with {parallel_jobs} parallel jobs"

    yield from execute_command_with_analysis(
        command, working_dir=working_dir, command_type="test"
    )


# --- Helper Functions ---
def get_common_cmake_variables() -> Dict[str, Dict[str, Any]]:
    """一般的なCMake変数の定義を返す"""
    return {
        "CMAKE_VERBOSE_MAKEFILE": {
            "description": "Enable verbose output from Makefile builds",
            "type": "bool",
            "default": "OFF",
            "values": ["ON", "OFF"],
        },
        "BUILD_SHARED_LIBS": {
            "description": "Build shared libraries instead of static",
            "type": "bool",
            "default": "OFF",
            "values": ["ON", "OFF"],
        },
        "CMAKE_BUILD_TYPE": {
            "description": "Build configuration type",
            "type": "choice",
            "default": "Release",
            "values": ["Debug", "Release", "RelWithDebInfo", "MinSizeRel"],
        },
        "CMAKE_INSTALL_PREFIX": {
            "description": "Install directory used by install()",
            "type": "path",
            "default": "/usr/local",
        },
        "CMAKE_FIND_ROOT_PATH": {
            "description": "Path used for searching by FIND_XXX(), with appropriate suffixes added",
            "type": "path",
            "default": "",
        },
        "CMAKE_TOOLCHAIN_FILE": {
            "description": "Path to toolchain file",
            "type": "file",
            "default": "",
        },
    }


def parse_cmake_defines_string(defines_string: str) -> Dict[str, str]:
    """文字列形式のCMake定義をパースしてDict形式に変換する"""
    defines = {}
    if not defines_string.strip():
        return defines

    # 複数の定義を分割（改行またはセミコロンで区切り）
    lines = defines_string.replace(";", "\n").split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # KEY=VALUE形式をパース
        if "=" in line:
            key, value = line.split("=", 1)
            defines[key.strip()] = value.strip()
        else:
            # 値なしの場合はONとして扱う
            defines[line.strip()] = "ON"

    return defines


# --- API Functions ---
def list_presets(working_dir: str = "sample"):
    """利用可能なCMakeプリセットを一覧表示する"""
    if not working_dir:
        yield "Please specify a working directory."
        return

    command = ["cmake", "--list-presets"]
    yield from execute_command(command, working_dir=working_dir)


def configure_project(
    preset: str, working_dir: str = "sample", cmake_defines: Dict[str, str] = None
):
    """CMake configureを実行する（エラー解析機能付き）"""
    if not preset:
        yield "Please select a preset."
        return

    if not working_dir:
        yield "Please specify a working directory."
        return

    # Command to run in the specified directory
    command = ["cmake", "--preset", preset]

    # Add CMake define variables if provided
    if cmake_defines:
        for key, value in cmake_defines.items():
            if key and value is not None:  # Skip empty keys or None values
                command.extend(["-D", f"{key}={value}"])

    yield from execute_command_with_analysis(
        command, working_dir=working_dir, command_type="cmake"
    )


def configure_project_with_defines(
    preset: str,
    working_dir: str = "sample",
    defines_string: str = "",
    verbose_makefile: bool = False,
    build_shared_libs: bool = False,
    build_type: str = "",
    install_prefix: str = "",
    find_root_path: str = "",
    toolchain_file: str = "",
):
    """CMake configureを実行する（Define変数対応版）"""
    if not preset:
        yield "Please select a preset."
        return

    if not working_dir:
        yield "Please specify a working directory."
        return

    # Parse custom defines from string
    cmake_defines = parse_cmake_defines_string(defines_string)

    # Add common variables if specified
    if verbose_makefile:
        cmake_defines["CMAKE_VERBOSE_MAKEFILE"] = "ON"

    if build_shared_libs:
        cmake_defines["BUILD_SHARED_LIBS"] = "ON"

    if build_type:
        cmake_defines["CMAKE_BUILD_TYPE"] = build_type

    if install_prefix:
        cmake_defines["CMAKE_INSTALL_PREFIX"] = install_prefix

    if find_root_path:
        cmake_defines["CMAKE_FIND_ROOT_PATH"] = find_root_path

    if toolchain_file:
        cmake_defines["CMAKE_TOOLCHAIN_FILE"] = toolchain_file

    # Show the defines that will be used
    if cmake_defines:
        defines_info = "CMake defines to be applied:\n"
        for key, value in cmake_defines.items():
            defines_info += f"  -D{key}={value}\n"
        yield defines_info + "\n"

    # Call the main configure function
    yield from configure_project(preset, working_dir, cmake_defines)


def build_project(
    preset: str,
    targets: List[str] = None,
    working_dir: str = "sample",
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
):
    """CMake buildを実行する（複数ターゲット対応、Verbose、並列ビルド対応、エラー解析機能付き）"""
    if not preset:
        yield "Please select a build preset."
        return

    if not working_dir:
        yield "Please specify a working directory."
        return

    command = [CMAKE_EXE, "--build", "--preset", preset]

    # 複数ターゲットの処理
    if targets:
        # 空文字列や None を除外してフィルタリング
        valid_targets = [
            target.strip() for target in targets if target and target.strip()
        ]
        for target in valid_targets:
            command.extend(["--target", target])

        if valid_targets:
            yield f"Building targets: {', '.join(valid_targets)}\n"

    # Verboseオプションの追加
    if verbose:
        command.append("--verbose")
        yield "Verbose build enabled.\n"

    # 並列ビルドジョブ数の指定
    if parallel_jobs and parallel_jobs > 0:
        command.extend(["--parallel", str(parallel_jobs)])
        yield f"Parallel build jobs: {parallel_jobs}\n"

    yield from execute_command_with_analysis(
        command, working_dir=working_dir, command_type="build"
    )


def build_project_single_target(
    preset: str,
    target: str = "",
    working_dir: str = "sample",
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
):
    """CMake buildを実行する（単一ターゲット用、後方互換性のため）"""
    targets = [target] if target else None
    yield from build_project(preset, targets, working_dir, verbose, parallel_jobs)


def build_project_multi_target_ui(
    preset: str,
    selected_targets: List[str],
    custom_targets: str,
    working_dir: str = "sample",
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
):
    """CMake buildを実行する（UI用複数ターゲット対応）"""
    if not preset:
        yield "Please select a build preset."
        return

    # Combine selected targets and custom targets
    all_targets = []

    # Add selected targets from checkbox group
    if selected_targets:
        all_targets.extend(selected_targets)

    # Add custom targets from text input
    if custom_targets and custom_targets.strip():
        custom_target_list = [
            target.strip() for target in custom_targets.split(",") if target.strip()
        ]
        all_targets.extend(custom_target_list)

    # Remove duplicates while preserving order
    unique_targets = []
    seen = set()
    for target in all_targets:
        if target not in seen:
            unique_targets.append(target)
            seen.add(target)

    # Show target configuration
    if unique_targets:
        yield f"Selected targets: {', '.join(unique_targets)}\n"
    else:
        yield "No specific targets selected, building default target.\n"

    # Call the main build function
    yield from build_project(
        preset,
        unique_targets if unique_targets else None,
        working_dir,
        verbose,
        parallel_jobs,
    )


def build_project_with_options(
    preset: str,
    targets: List[str] = None,
    working_dir: str = "sample",
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
):
    """CMake buildを実行する（全オプション対応版）"""
    if not preset:
        yield "Please select a build preset."
        return

    if not working_dir:
        yield "Please specify a working directory."
        return

    # Show build configuration
    config_info = f"Build Configuration:\n"
    config_info += f"  Preset: {preset}\n"
    config_info += f"  Working Directory: {working_dir}\n"

    if targets:
        valid_targets = [
            target.strip() for target in targets if target and target.strip()
        ]
        if valid_targets:
            config_info += f"  Targets: {', '.join(valid_targets)}\n"

    if verbose:
        config_info += f"  Verbose: Enabled\n"

    if parallel_jobs and parallel_jobs > 0:
        config_info += f"  Parallel Jobs: {parallel_jobs}\n"

    config_info += "\n"
    yield config_info

    # Call the main build function
    yield from build_project(preset, targets, working_dir, verbose, parallel_jobs)


def test_project_ui(
    preset: str,
    working_dir: str = "sample",
    verbose: bool = False,
    test_filter: str = "",
    parallel_jobs: Optional[int] = None,
):
    """CTest実行機能（UI用拡張オプション対応）"""
    if not working_dir:
        yield "Please specify a working directory."
        return

    # Show test configuration
    config_info = f"Test Configuration:\n"
    config_info += f"  Working Directory: {working_dir}\n"

    if preset and preset.strip():
        config_info += f"  Test Preset: {preset}\n"
    else:
        config_info += f"  Test Preset: None (using default test directory)\n"

    if verbose:
        config_info += f"  Verbose: Enabled\n"

    if test_filter and test_filter.strip():
        config_info += f"  Test Filter: {test_filter.strip()}\n"

    if parallel_jobs and parallel_jobs > 0:
        config_info += f"  Parallel Jobs: {parallel_jobs}\n"

    config_info += "\n"
    yield config_info

    # Call the main test function
    yield from test_project(preset, working_dir, verbose, test_filter, parallel_jobs)


# --- Health Check Functions ---
def health_check(working_dir: str = "sample") -> Dict[str, Any]:
    """システム環境の健全性チェックを実行する"""
    health_status = {
        "cmake_available": False,
        "ctest_available": False,
        "cmake_presets_exists": False,
        "working_directory_exists": False,
        "cmake_version": None,
        "ctest_version": None,
        "cmake_presets_path": None,
        "issues": [],
        "recommendations": [],
        "overall_status": "unknown",
    }

    # Working directory check
    abs_working_dir = os.path.abspath(working_dir)
    health_status["working_directory_exists"] = os.path.isdir(abs_working_dir)
    if not health_status["working_directory_exists"]:
        health_status["issues"].append(
            f"Working directory does not exist: {abs_working_dir}"
        )
        health_status["recommendations"].append(
            f"Create the working directory or specify a valid path"
        )

    # CMake availability check
    try:
        result = subprocess.run(
            [CMAKE_EXE, "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            health_status["cmake_available"] = True
            # Extract version from output
            version_match = re.search(r"cmake version (\d+\.\d+\.\d+)", result.stdout)
            if version_match:
                health_status["cmake_version"] = version_match.group(1)
        else:
            health_status["issues"].append("CMake command failed to execute")
            health_status["recommendations"].append(
                "Check CMake installation and PATH configuration"
            )
    except FileNotFoundError:
        health_status["issues"].append("CMake not found in system PATH")
        health_status["recommendations"].append(
            "Install CMake and ensure it's added to system PATH"
        )
    except subprocess.TimeoutExpired:
        health_status["issues"].append("CMake command timed out")
        health_status["recommendations"].append("Check CMake installation integrity")
    except Exception as e:
        health_status["issues"].append(f"Error checking CMake: {str(e)}")
        health_status["recommendations"].append("Verify CMake installation")

    # CTest availability check
    try:
        result = subprocess.run(
            ["ctest", "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            health_status["ctest_available"] = True
            # Extract version from output
            version_match = re.search(r"ctest version (\d+\.\d+\.\d+)", result.stdout)
            if version_match:
                health_status["ctest_version"] = version_match.group(1)
        else:
            health_status["issues"].append("CTest command failed to execute")
            health_status["recommendations"].append(
                "Check CTest installation (usually comes with CMake)"
            )
    except FileNotFoundError:
        health_status["issues"].append("CTest not found in system PATH")
        health_status["recommendations"].append(
            "Install CMake (CTest is included) and ensure it's added to system PATH"
        )
    except subprocess.TimeoutExpired:
        health_status["issues"].append("CTest command timed out")
        health_status["recommendations"].append("Check CTest installation integrity")
    except Exception as e:
        health_status["issues"].append(f"Error checking CTest: {str(e)}")
        health_status["recommendations"].append("Verify CTest installation")

    # CMakePresets.json check
    if health_status["working_directory_exists"]:
        presets_path = os.path.join(abs_working_dir, "CMakePresets.json")
        health_status["cmake_presets_path"] = presets_path
        health_status["cmake_presets_exists"] = os.path.isfile(presets_path)

        if not health_status["cmake_presets_exists"]:
            health_status["issues"].append(
                f"CMakePresets.json not found in {abs_working_dir}"
            )
            health_status["recommendations"].append(
                "Create CMakePresets.json file or navigate to a directory containing it"
            )

            # Check for CMakeLists.txt as alternative
            cmake_lists_path = os.path.join(abs_working_dir, "CMakeLists.txt")
            if os.path.isfile(cmake_lists_path):
                health_status["recommendations"].append(
                    "CMakeLists.txt found - you can create CMakePresets.json to use preset functionality"
                )
            else:
                health_status["recommendations"].append(
                    "No CMakeLists.txt found either - ensure you're in a CMake project directory"
                )

    # Overall status determination
    critical_issues = 0
    if not health_status["cmake_available"]:
        critical_issues += 1
    if not health_status["ctest_available"]:
        critical_issues += 1
    if not health_status["working_directory_exists"]:
        critical_issues += 1

    if critical_issues == 0:
        if health_status["cmake_presets_exists"]:
            health_status["overall_status"] = "healthy"
        else:
            health_status["overall_status"] = "warning"
            health_status["recommendations"].append(
                "System is functional but CMakePresets.json is missing for full functionality"
            )
    elif critical_issues <= 1:
        health_status["overall_status"] = "warning"
    else:
        health_status["overall_status"] = "critical"

    # Add Windows-specific recommendations if needed
    if not health_status["cmake_available"] and os.name == "nt":
        health_status["recommendations"].extend(
            [
                "On Windows, try using Visual Studio Developer Command Prompt",
                "Install Visual Studio Build Tools with C++ CMake tools",
                "Or install CMake from https://cmake.org/download/",
            ]
        )

    return health_status


def health_check_ui(working_dir: str = "sample") -> str:
    """健全性チェックのUI用ラッパー関数"""
    if not working_dir:
        return "Please specify a working directory."

    health_status = health_check(working_dir)

    # Format output for UI display
    output = "=== SYSTEM HEALTH CHECK ===\n\n"

    # Overall status
    status_emoji = {"healthy": "✅", "warning": "⚠️", "critical": "❌", "unknown": "❓"}

    output += f"Overall Status: {status_emoji.get(health_status['overall_status'], '❓')} {health_status['overall_status'].upper()}\n\n"

    # Component status
    output += "COMPONENT STATUS:\n"
    output += f"  CMake: {'✅ Available' if health_status['cmake_available'] else '❌ Not Available'}"
    if health_status["cmake_version"]:
        output += f" (v{health_status['cmake_version']})"
    output += "\n"

    output += f"  CTest: {'✅ Available' if health_status['ctest_available'] else '❌ Not Available'}"
    if health_status["ctest_version"]:
        output += f" (v{health_status['ctest_version']})"
    output += "\n"

    output += f"  Working Directory: {'✅ Exists' if health_status['working_directory_exists'] else '❌ Not Found'}\n"
    output += f"  CMakePresets.json: {'✅ Found' if health_status['cmake_presets_exists'] else '❌ Not Found'}"
    if health_status["cmake_presets_path"]:
        output += f"\n    Path: {health_status['cmake_presets_path']}"
    output += "\n\n"

    # Issues
    if health_status["issues"]:
        output += "ISSUES FOUND:\n"
        for i, issue in enumerate(health_status["issues"], 1):
            output += f"  {i}. {issue}\n"
        output += "\n"

    # Recommendations
    if health_status["recommendations"]:
        output += "RECOMMENDATIONS:\n"
        for i, rec in enumerate(health_status["recommendations"], 1):
            output += f"  {i}. {rec}\n"
        output += "\n"

    # Setup instructions based on status
    if health_status["overall_status"] == "critical":
        output += "SETUP INSTRUCTIONS:\n"
        output += "  Your system requires setup before using this MCP server.\n"
        output += (
            "  Please follow the recommendations above to resolve critical issues.\n\n"
        )
    elif health_status["overall_status"] == "warning":
        output += "SETUP NOTES:\n"
        output += "  Your system is mostly ready but may have limited functionality.\n"
        output += "  Consider addressing the recommendations above for full functionality.\n\n"
    else:
        output += "SYSTEM READY:\n"
        output += "  Your system is properly configured for CMake operations.\n"
        output += "  All core components are available and functional.\n\n"

    output += "=== END HEALTH CHECK ===\n"

    return output


def main():
    """uv run用のエントリーポイント"""
    with gr.Blocks() as app:
        gr.Markdown("# MCP-CMake Server")
        gr.Markdown(
            "This server exposes APIs for a Gradio client. You can also use this UI for direct testing."
        )

        with gr.Tab("List Presets"):
            list_working_dir = gr.Textbox(
                label="Working Directory",
                value="sample",
                info="Directory containing CMakeLists.txt",
            )
            list_btn = gr.Button("List Available Presets", variant="primary")
            list_output = gr.Textbox(
                label="Available Presets", lines=15, interactive=False, autoscroll=True
            )

        with gr.Tab("Configure API"):
            configure_working_dir = gr.Textbox(
                label="Working Directory",
                value="sample",
                info="Directory containing CMakeLists.txt",
            )
            configure_preset_input = gr.Textbox(
                label="Configure Preset Name",
                info="Enter the name of the configure preset.",
            )

            # CMake Define Variables Section
            gr.Markdown("### CMake Define Variables")

            # Common variables with checkboxes and dropdowns
            with gr.Row():
                with gr.Column():
                    verbose_makefile = gr.Checkbox(
                        label="CMAKE_VERBOSE_MAKEFILE",
                        info="Enable verbose output from Makefile builds",
                    )
                    build_shared_libs = gr.Checkbox(
                        label="BUILD_SHARED_LIBS",
                        info="Build shared libraries instead of static",
                    )
                with gr.Column():
                    build_type = gr.Dropdown(
                        choices=[
                            "",
                            "Debug",
                            "Release",
                            "RelWithDebInfo",
                            "MinSizeRel",
                        ],
                        value="",
                        label="CMAKE_BUILD_TYPE",
                        info="Build configuration type",
                    )

            # Path variables
            with gr.Row():
                with gr.Column():
                    install_prefix = gr.Textbox(
                        label="CMAKE_INSTALL_PREFIX",
                        placeholder="/usr/local",
                        info="Install directory used by install()",
                    )
                with gr.Column():
                    find_root_path = gr.Textbox(
                        label="CMAKE_FIND_ROOT_PATH",
                        placeholder="",
                        info="Path used for searching by FIND_XXX()",
                    )

            toolchain_file = gr.Textbox(
                label="CMAKE_TOOLCHAIN_FILE",
                placeholder="",
                info="Path to toolchain file",
            )

            # Custom defines input
            gr.Markdown("### Custom Define Variables")
            defines_string = gr.Textbox(
                label="Custom Defines",
                lines=4,
                placeholder="KEY1=VALUE1\nKEY2=VALUE2\nBOOL_FLAG",
                info="Enter custom CMake defines (one per line, KEY=VALUE format, or just KEY for boolean flags)",
            )

            configure_btn = gr.Button("Test Configure API", variant="primary")
            configure_output = gr.Textbox(
                label="Output", lines=15, interactive=False, autoscroll=True
            )

        with gr.Tab("Build API"):
            build_working_dir = gr.Textbox(
                label="Working Directory",
                value="sample",
                info="Directory containing CMakeLists.txt",
            )
            build_preset_input = gr.Textbox(label="Build Preset Name")

            # Multiple target selection
            gr.Markdown("### Target Selection")
            build_targets_input = gr.CheckboxGroup(
                choices=["all", "my_app", "clean", "install", "test", "package"],
                value=[],
                label="Build Targets",
                info="Select one or more targets to build (leave empty to build default target)",
            )

            # Alternative: Custom target input for targets not in the predefined list
            build_custom_targets = gr.Textbox(
                label="Custom Targets (optional)",
                placeholder="target1,target2,target3",
                info="Enter additional target names separated by commas",
            )

            # Build options
            gr.Markdown("### Build Options")
            with gr.Row():
                build_verbose = gr.Checkbox(
                    label="Verbose Build", info="Enable verbose output during build"
                )
                build_parallel_jobs = gr.Number(
                    label="Parallel Jobs",
                    value=1,
                    precision=0,
                    minimum=0,
                    maximum=32,
                    info="Number of parallel build jobs (0 = auto)",
                )

            build_btn = gr.Button("Test Build API")
            build_output = gr.Textbox(
                label="Output", lines=15, interactive=False, autoscroll=True
            )

        with gr.Tab("Test API"):
            test_working_dir = gr.Textbox(
                label="Working Directory",
                value="sample",
                info="Directory containing CMakeLists.txt",
            )
            test_preset_input = gr.Textbox(
                label="Test Preset Name (optional)",
                info="Enter the name of the test preset (leave empty to use default)",
            )

            # Test options
            gr.Markdown("### Test Options")
            with gr.Row():
                test_verbose = gr.Checkbox(
                    label="Verbose Test",
                    info="Enable verbose output during test execution",
                )
                test_parallel_jobs = gr.Number(
                    label="Parallel Jobs",
                    value=1,
                    precision=0,
                    minimum=0,
                    maximum=32,
                    info="Number of parallel test jobs (0 = auto)",
                )

            # Test filter
            test_filter_input = gr.Textbox(
                label="Test Filter (optional)",
                placeholder=".*MyTest.*",
                info="Regular expression to filter which tests to run (leave empty to run all tests)",
            )

            test_btn = gr.Button("Run Tests", variant="primary")
            test_output = gr.Textbox(
                label="Output", lines=15, interactive=False, autoscroll=True
            )

        with gr.Tab("Error Analysis"):
            gr.Markdown("### Error Analysis Engine")
            gr.Markdown(
                "Paste build or test error output to get structured analysis for LLM assistance."
            )

            with gr.Row():
                with gr.Column(scale=2):
                    error_input = gr.Textbox(
                        label="Error Output",
                        lines=12,
                        placeholder="Paste your build/test error output here...",
                        info="Copy and paste the error output from CMake, compiler, or test execution",
                    )
                with gr.Column(scale=1):
                    error_type_input = gr.Dropdown(
                        choices=["build", "test", "cmake"],
                        value="build",
                        label="Error Type",
                        info="Select the type of operation that generated the error",
                    )

                    # Error statistics display
                    gr.Markdown("#### Error Statistics")
                    error_stats = gr.JSON(label="Statistics", visible=False)

                    # Analysis options
                    gr.Markdown("#### Analysis Options")
                    show_context = gr.Checkbox(
                        label="Include Source Context",
                        value=True,
                        info="Include surrounding source code lines",
                    )
                    show_suggestions = gr.Checkbox(
                        label="Include Suggestions",
                        value=True,
                        info="Include resolution suggestions",
                    )
                    detailed_analysis = gr.Checkbox(
                        label="Detailed Analysis",
                        value=True,
                        info="Use enhanced analysis for build/test errors",
                    )

                    # Error filtering options
                    gr.Markdown("#### Error Filtering")
                    error_filter_type = gr.Dropdown(
                        choices=[
                            "all",
                            "compile_errors",
                            "link_errors",
                            "cmake_errors",
                            "warnings",
                        ],
                        value="all",
                        label="Filter by Error Type",
                        info="Filter errors by specific type",
                    )

            with gr.Row():
                analyze_btn = gr.Button("Analyze Error", variant="primary", scale=1)
                get_stats_btn = gr.Button(
                    "Get Statistics", variant="secondary", scale=1
                )
                filter_btn = gr.Button("Filter Errors", variant="secondary", scale=1)
                copy_btn = gr.Button("Copy Analysis", variant="secondary", scale=1)

            # Analysis results with tabs for different views
            with gr.Tabs():
                with gr.Tab("LLM-Ready Analysis"):
                    analysis_output = gr.Textbox(
                        label="Structured Analysis",
                        lines=25,
                        interactive=False,
                        autoscroll=True,
                        info="Structured error analysis ready to copy and paste to LLM",
                    )

                    # Copy instructions and status
                    gr.Markdown(
                        "**Copy Instructions:** Select all text above (Ctrl+A) and copy (Ctrl+C) to paste into your LLM chat."
                    )
                    copy_status = gr.Textbox(
                        label="Copy Status", lines=1, interactive=False, visible=False
                    )

                with gr.Tab("Error Summary"):
                    summary_output = gr.Textbox(
                        label="Quick Summary",
                        lines=10,
                        interactive=False,
                        info="Brief summary of errors and issues",
                    )

                with gr.Tab("Filtered Errors"):
                    filtered_output = gr.Textbox(
                        label="Filtered Error Output",
                        lines=15,
                        interactive=False,
                        autoscroll=True,
                        info="Error output filtered by selected type",
                    )

                with gr.Tab("Raw Statistics"):
                    gr.Markdown("Raw statistical data about the errors")
                    stats_output = gr.JSON(label="Detailed Statistics")

        with gr.Tab("Health Check"):
            gr.Markdown("### System Health Check")
            gr.Markdown(
                "Check if your system is properly configured for CMake operations."
            )

            health_working_dir = gr.Textbox(
                label="Working Directory",
                value="sample",
                info="Directory to check for CMake project files",
            )

            with gr.Row():
                health_check_btn = gr.Button(
                    "Run Health Check", variant="primary", scale=2
                )
                refresh_btn = gr.Button("Refresh", variant="secondary", scale=1)

            # Health check results
            health_output = gr.Textbox(
                label="Health Check Results",
                lines=20,
                interactive=False,
                autoscroll=True,
                info="System health status and recommendations",
            )

            # Quick status indicators
            with gr.Row():
                with gr.Column():
                    gr.Markdown("#### Quick Status")
                    cmake_status = gr.Textbox(
                        label="CMake Status", lines=1, interactive=False, visible=False
                    )
                    ctest_status = gr.Textbox(
                        label="CTest Status", lines=1, interactive=False, visible=False
                    )
                with gr.Column():
                    presets_status = gr.Textbox(
                        label="CMakePresets.json Status",
                        lines=1,
                        interactive=False,
                        visible=False,
                    )
                    overall_status = gr.Textbox(
                        label="Overall Status",
                        lines=1,
                        interactive=False,
                        visible=False,
                    )

            # Setup instructions section
            gr.Markdown("#### Setup Instructions")
            setup_instructions = gr.Markdown(
                """
                **Getting Started:**
                1. Click "Run Health Check" to diagnose your system
                2. Follow any recommendations provided
                3. Re-run the health check to verify fixes
                
                **Common Issues:**
                - **CMake not found**: Install CMake from https://cmake.org/download/
                - **Windows users**: Use Visual Studio Developer Command Prompt
                - **Missing CMakePresets.json**: Create one in your project directory
                """,
                visible=True,
            )

        # --- API Endpoint Definitions ---
        list_btn.click(
            fn=list_presets,
            inputs=[list_working_dir],
            outputs=[list_output],
            api_name="list_presets",
        )

        configure_btn.click(
            fn=configure_project_with_defines,
            inputs=[
                configure_preset_input,
                configure_working_dir,
                defines_string,
                verbose_makefile,
                build_shared_libs,
                build_type,
                install_prefix,
                find_root_path,
                toolchain_file,
            ],
            outputs=[configure_output],
            api_name="configure_with_defines",
        )

        build_btn.click(
            fn=build_project_multi_target_ui,
            inputs=[
                build_preset_input,
                build_targets_input,
                build_custom_targets,
                build_working_dir,
                build_verbose,
                build_parallel_jobs,
            ],
            outputs=[build_output],
            api_name="build",
        )

        test_btn.click(
            fn=test_project_ui,
            inputs=[
                test_preset_input,
                test_working_dir,
                test_verbose,
                test_filter_input,
                test_parallel_jobs,
            ],
            outputs=[test_output],
            api_name="test",
        )

        analyze_btn.click(
            fn=analyze_error_output,
            inputs=[error_input, error_type_input],
            outputs=[analysis_output],
            api_name="analyze_error",
        )

        get_stats_btn.click(
            fn=lambda error_input, error_type: get_error_statistics_ui(
                error_input, error_type
            )[0],
            inputs=[error_input, error_type_input],
            outputs=[stats_output],
            api_name="get_error_statistics",
        )

        copy_btn.click(
            fn=copy_analysis_to_clipboard,
            inputs=[analysis_output],
            outputs=[summary_output],
            api_name="copy_analysis",
        )

        filter_btn.click(
            fn=filter_errors_by_type,
            inputs=[error_input, error_filter_type],
            outputs=[filtered_output],
            api_name="filter_errors",
        )

        health_check_btn.click(
            fn=health_check_ui,
            inputs=[health_working_dir],
            outputs=[health_output],
            api_name="health_check",
        )

        refresh_btn.click(
            fn=health_check_ui,
            inputs=[health_working_dir],
            outputs=[health_output],
            api_name="health_check_refresh",
        )

        # Add hidden interfaces for additional API endpoints
        with gr.Row(visible=False):
            # Original configure API (for backward compatibility)
            hidden_configure_preset = gr.Textbox()
            hidden_configure_working_dir = gr.Textbox()
            hidden_configure_output = gr.Textbox()
            hidden_configure_btn = gr.Button()

            # Multiple targets build API
            hidden_build_preset = gr.Textbox()
            hidden_build_targets = gr.JSON()  # List of targets as JSON
            hidden_build_working_dir = gr.Textbox()
            hidden_build_verbose = gr.Checkbox()
            hidden_build_parallel_jobs = gr.Number()
            hidden_build_output = gr.Textbox()
            hidden_build_btn = gr.Button()

            # Build with options API
            hidden_build_options_preset = gr.Textbox()
            hidden_build_options_targets = gr.JSON()
            hidden_build_options_working_dir = gr.Textbox()
            hidden_build_options_verbose = gr.Checkbox()
            hidden_build_options_parallel_jobs = gr.Number()
            hidden_build_options_output = gr.Textbox()
            hidden_build_options_btn = gr.Button()

            # Test API (for direct API access)
            hidden_test_preset = gr.Textbox()
            hidden_test_working_dir = gr.Textbox()
            hidden_test_verbose = gr.Checkbox()
            hidden_test_filter = gr.Textbox()
            hidden_test_parallel_jobs = gr.Number()
            hidden_test_output = gr.Textbox()
            hidden_test_btn = gr.Button()

        hidden_configure_btn.click(
            fn=configure_project,
            inputs=[hidden_configure_preset, hidden_configure_working_dir],
            outputs=[hidden_configure_output],
            api_name="configure",
        )

        hidden_build_btn.click(
            fn=build_project,
            inputs=[
                hidden_build_preset,
                hidden_build_targets,
                hidden_build_working_dir,
                hidden_build_verbose,
                hidden_build_parallel_jobs,
            ],
            outputs=[hidden_build_output],
            api_name="build_multiple_targets",
        )

        hidden_build_options_btn.click(
            fn=build_project_with_options,
            inputs=[
                hidden_build_options_preset,
                hidden_build_options_targets,
                hidden_build_options_working_dir,
                hidden_build_options_verbose,
                hidden_build_options_parallel_jobs,
            ],
            outputs=[hidden_build_options_output],
            api_name="build_with_options",
        )

        hidden_test_btn.click(
            fn=test_project,
            inputs=[
                hidden_test_preset,
                hidden_test_working_dir,
                hidden_test_verbose,
                hidden_test_filter,
                hidden_test_parallel_jobs,
            ],
            outputs=[hidden_test_output],
            api_name="test_with_options",
        )

    app.launch(mcp_server=True, root_path="/api")


if __name__ == "__main__":
    main()

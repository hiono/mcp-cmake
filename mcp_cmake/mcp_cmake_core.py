import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from packaging.version import Version

from mcp_cmake.mcp_cmake_models import (
    BuildErrorInfo,
    CommandResult,
    CompileError,
    StructuredError,
    TestErrorInfo,
    TestFailure,
)

from mcp_cmake.mcp_cmake_helpers import get_minimum_cmake_version

# --- Constants ---
CMAKE_EXE = "cmake"


# --- Error Analysis Engine ---
class ErrorAnalyzer:
    """エラー解析エンジン - ビルドやテストエラーを構造化して解析する"""

    # エラーパターンの定義
    COMPILE_ERROR_PATTERNS = [
        # MSVC patterns
        (r"^([^()]+)\\((\\d+),(\\d+)\\):\\s*error\\s+C(\\d+):\\s*(.+)", "msvc_compile"),
        # GCC/Clang patterns
        (r"^([^:]+):(\\d+):(\\d+):\\s*error:\\s*(.+)", "gcc_compile"),
        # Generic compile error
        (r"^([^:]+):(\\d+):\\s*error:\\s*(.+)", "generic_compile"),
    ]

    LINK_ERROR_PATTERNS = [
        # MSVC linker
        (r"^\s*([^:]+)\s*:\s*error\s+LNK(\d+):\s+(.+)", "msvc_link"),
        # GCC/Clang linker
        (r"^\s*([^:]+):\(.+?\):\s*(undefined reference to `.+?`)", "gcc_link"),
        # Generic linker error
        (r"^ld:\s*(.+)", "generic_link"),
    ]

    CMAKE_ERROR_PATTERNS = [
        # CMake configuration errors
        (r"^CMake Error at ([^:]+):(\d+)\s*\((.+?)\):\s*(.+)", "cmake_config"),
        # CMake general errors
        (r"^CMake Error:\s*(.+)", "cmake_general"),
    ]

    TEST_ERROR_PATTERNS = [
        # CTest test failures with ***Failed
        (r"^(\\d+)/\\d+\\s+Test\\s+#(\\d+):\\s+(.+?)\\s+\\.+\\\\*{3}Failed", "test_failed"),
        # CTest timeout with ***Timeout
        (r"^(\\d+)/\\d+\\s+Test\\s+#(\\d+):\\s+(.+?)\\s+\\.+\\\\*{3}Timeout", "test_timeout"),
        # CTest not run with ***Not Run
        (r"^(\\d+)/\\d+\\s+Test\\s+#(\\d+):\\s+(.+?)\\s+\\.+\\\\*{3}Not Run", "test_not_run"),
        # Legacy patterns for backward compatibility
        (r"^(\\d+):\\s*Test\\s+(.+?)\\s+.*Failed", "test_failed"),
        (r"^(\\d+):\\s*Test\\s+(.+?)\\s+.*Timeout", "test_timeout"),
        (r"^(\\d+):\\s*Test\\s+(.+?)\\s+.*Not Run", "test_not_run"),
        # Generic test error
        (r"^Test\\s+(.+?)\\s+.*FAILED", "test_generic_failed"),
    ]

    def analyze_error(
        self,
        output: str,
        command_type: str = "build"
    ) -> Optional[StructuredError]:
        """エラー出力を解析して構造化されたエラー情報を生成する"""
        if not output:  # Keep this check for truly empty output
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
            match = re.search(pattern, output, re.MULTILINE | re.DOTALL)
            if match:
                return self._create_structured_error(match, error_type, output)

        # どのパターンにもマッチしない場合、汎用エラーとして処理を試みる
        # ただし、出力に一般的なエラーを示すキーワードが含まれている場合のみ
        if any(
            keyword in output.lower()
            for keyword in ["error", "failed", "fatal", "exception"]
        ):
            return self._create_generic_error(output, command_type)

        return None  # No error pattern found and no general error keywords

    def _create_structured_error(
        self,
        match,
        error_type: str,
        raw_output: str
    ) -> StructuredError:
        """マッチした正規表現から構造化エラーを作成する"""
        groups = match.groups()

        # エラータイプ別の処理
        if "compile" in error_type:
            file_path = groups[0].strip() if len(groups) > 0 and groups[0] else None
            line_number = (
                int(groups[1]) if len(groups) > 1 and groups[1].isdigit() else None
            )
            column_number = (
                int(groups[2]) if len(groups) > 2 and groups[2].isdigit() else None
            )
            message = groups[-1] if groups else "Unknown compile error"
        elif "link" in error_type:
            file_path = groups[0].strip() if len(groups) > 0 and groups[0] else None
            line_number = None
            column_number = None
            message = groups[-1] if groups else "Unknown link error"
        elif "cmake" in error_type:
            file_path = groups[0].strip() if len(groups) > 0 and groups[0] else None
            line_number = (
                int(groups[1]) if len(groups) > 1 and groups[1].isdigit() else None
            )
            column_number = None
            message = groups[-1] if groups else "Unknown CMake error"
        elif "test" in error_type:
            file_path = None
            line_number = None
            column_number = None
            # For test errors, the message should be the full matched string
            message = match.group(0) if match else "Unknown test error"
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
        self,
        raw_output: str,
        command_type: str
    ) -> StructuredError:
        """汎用エラーを作成する"""
        # エラーメッセージを抽出
        keywords_priority = [
            "error:",
            "fatal:",
            "exception:",
            "error",
            "fatal",
            "exception",
            "failed",
        ]
        relevant_lines = []
        for line in raw_output.split("\n"):
            stripped_line = line.strip()
            if any(keyword in stripped_line.lower() for keyword in keywords_priority):
                relevant_lines.append(stripped_line)
        message = relevant_lines[0] if relevant_lines else "Unknown error occurred"

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
        self,
        raw_output: str,
        file_path: Optional[str],
        line_number: Optional[int]
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
                                prefix = ">>>"  # エラー行をハイライト
                            elif abs(i - (line_number - 1)) <= 1:
                                prefix = ">"  # エラー行の近くをマーク
                            else:
                                prefix = ""
                            context.append(f"{prefix} {i+1:d}: {lines[i].rstrip()}")
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
        cmake_multiline_pattern = r"CMake Error at (.+?):(\\d+)\\s*\\((.+?)\\):\\s*\\n\\s*(.+?)(?=\\n\\n|\\nCMake|\\n[A-Z]|\\Z)"
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
                    "message": message.strip().replace("\\n", " "),
                }
            )
            details["error_types"].append("cmake_error")
            details["line_numbers"].append(int(line_num))

        for line in lines:
            # MSVC エラーパターン
            msvc_match = re.search(
                r"(.+?)\\((\\d+),(\\d+)\\):\\s*(error|warning)\\s+C(\\d+):\\s*(.+)", line
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
            gcc_match = re.search(r"(.+?):(\\d+):(\\d+):\\s*(error|warning):\\s*(.+)", line)
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
                if not details["compiler_info"]:
                    details["compiler_info"] = "GCC"
                continue

            # CMake エラーパターン
            cmake_match = re.search(
                r"CMake Error at (.+?):(\\d+)\\s*\\((.+?)\\):\\s*(.+)", line
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
            cmake_general_match = re.search(r"CMake Error:\\s*(.+)", line)
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
            elif "gcc version" in line.lower() or "g++" in line.lower():
                details["compiler_info"] = "GCC"
            elif "clang version" in line.lower():
                details["compiler_info"] = "Clang"

            # ビルドターゲット情報の抽出
            if "Building CXX object" in line:
                target_match = re.search(r"Building CXX object (.+?)\\.dir", line)
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
        self,
        file_path: str,
        line_number: int,
        context_lines: int = 5
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
            if (
                "undefined reference" in message.lower()
                or "unresolved external symbol" in message.lower()
            ):
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
        self,
        output: str,
        command: str = "",
        working_dir: str = "",
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
        elif "clang" in output.lower() or "clang++" in output.lower():
            compiler = "Clang"

        # エラーと警告をパース
        lines = output.split("\n")
        for line in lines:
            # MSVC エラーパターン
            msvc_match = re.search(
                r"(.+?)\\((\\d+),(\\d+)\\):\\s*(error|warning)\\s+C(\\d+):\\s*(.+)", line
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
            gcc_match = re.search(r"(.+?):(\\d+):(\\d+):\\s*(error|warning):\\s*(.+)", line)
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
        self,
        output: str,
        command: str = "",
        working_dir: str = "",
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
                r"(\\d+)/\\d+\\s+Test\\s+#(\\d+):\\s+(.+?)\\s+\\.+(.+)", line
            )
            if test_match:
                test_seq, test_num, test_name, result = test_match.groups()
                total_tests = max(total_tests, int(test_seq))

                # 実行時間を抽出
                time_match = re.search(r"(\\d+\\.\\d+)\\s+sec", result)
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
            legacy_match = re.search(r"(\\d+):\\s*Test\\s+(.+?)\\s+\\.+\\s*(.+)", line)
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
            r"(\\d+)% tests passed, (\\d+) tests failed out of (\\d+)", output
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
        self,
        failed_tests: List[TestFailure],
        total: int,
        failed: int,
        passed: int,
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
    error_output: str,
    command: str = "",
    working_dir: str = "",
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
    error_output: str,
    command: str = "",
    working_dir: str = "",
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
    preset: str,
    working_dir: str = "sample",
    cmake_defines: Dict[str, str] = None,
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

    critical_issues = 0  # Initialize critical_issues as an integer counter

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
        critical_issues += 1

    # CMake availability check
    try:
        result = subprocess.run(
            [CMAKE_EXE, "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            health_status["cmake_available"] = True
            # Extract version from output
            version_match = re.search(r"cmake version (\\d+\\.\\d+\\.\\d+)", result.stdout)
            if version_match:
                health_status["cmake_version"] = version_match.group(1)
        else:
            health_status["issues"].append("CMake command failed to execute")
            health_status["recommendations"].append(
                "Check CMake installation and PATH configuration"
            )
            critical_issues += 1
    except FileNotFoundError:
        health_status["issues"].append("CMake not found in system PATH")
        health_status["recommendations"].append(
            "Install CMake and ensure it's added to system PATH"
        )
        critical_issues += 1
    except subprocess.TimeoutExpired:
        health_status["issues"].append("CMake command timed out")
        health_status["recommendations"].append("Check CMake installation integrity")
        critical_issues += 1
    except Exception as e:
        health_status["issues"].append(f"Error checking CMake: {str(e)}")
        health_status["recommendations"].append("Verify CMake installation")
        critical_issues += 1

    # CTest availability check
    try:
        result = subprocess.run(
            ["ctest", "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            health_status["ctest_available"] = True
            # Extract version from output
            version_match = re.search(r"ctest version (\\d+\\.\\d+\\.\\d+)", result.stdout)
            if version_match:
                health_status["ctest_version"] = version_match.group(1)
        else:
            health_status["issues"].append("CTest command failed to execute")
            health_status["recommendations"].append(
                "Check CTest installation (usually comes with CMake)"
            )
            critical_issues += 1
    except FileNotFoundError:
        health_status["issues"].append("CTest not found in system PATH")
        health_status["recommendations"].append(
            "Install CMake (CTest is included) and ensure it's added to system PATH"
        )
        critical_issues += 1
    except subprocess.TimeoutExpired:
        health_status["issues"].append("CTest command timed out")
        health_status["recommendations"].append("Check CTest installation integrity")
        critical_issues += 1
    except Exception as e:
        health_status["issues"].append(f"Error checking CTest: {str(e)}")
        health_status["recommendations"].append("Verify CTest installation")
        critical_issues += 1

    # CMakePresets.json check
    if health_status["working_directory_exists"]:
        cmake_presets_path = os.path.join(abs_working_dir, "CMakePresets.json")
        health_status["cmake_presets_path"] = cmake_presets_path
        if os.path.exists(cmake_presets_path):
            health_status["cmake_presets_exists"] = True
        else:
            health_status["issues"].append(
                f"CMakePresets.json not found in {abs_working_dir}"
            )
            health_status["recommendations"].append(
                "Create a CMakePresets.json file or ensure it's in the correct working directory"
            )
            critical_issues += 1
    else:  # If working directory doesn't exist, presets can't exist either
        critical_issues += 1

    # Version compatibility check
    if health_status["cmake_available"] and health_status["cmake_presets_exists"]:
        try:
            # Get minimum CMake version from CMakePresets.json
            with open(health_status["cmake_presets_path"], "r") as f:
                presets = json.load(f)
        except json.JSONDecodeError:
            health_status["min_cmake_version"] = None
            health_status["cmake_version_check_message"] = "Error decoding CMakePresets.json"
        except Exception as e:
            health_status["min_cmake_version"] = None
            health_status["cmake_version_check_message"] = f"An unexpected error occurred: {e}"

    # Determine overall status
    if critical_issues == 0:
        health_status["overall_status"] = "healthy"
    elif critical_issues > 0 and len(health_status["issues"]) == critical_issues:
        health_status["overall_status"] = "warning"
    else:
        health_status["overall_status"] = "unhealthy"

    return health_status
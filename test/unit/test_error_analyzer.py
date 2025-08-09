import re
from unittest.mock import mock_open, patch

import pytest

from mcp_cmake import ErrorAnalyzer, StructuredError, parse_cmake_defines_string

# Existing tests for parse_cmake_defines_string...


def test_parse_cmake_defines_string_empty():
    assert parse_cmake_defines_string("") == {}
    assert parse_cmake_defines_string("   ") == {}


def test_parse_cmake_defines_string_single_define():
    assert parse_cmake_defines_string("KEY=VALUE") == {"KEY": "VALUE"}
    assert parse_cmake_defines_string("  ANOTHER_KEY = ANOTHER_VALUE  ") == {
        "ANOTHER_KEY": "ANOTHER_VALUE"
    }


def test_parse_cmake_defines_string_multiple_defines_newline():
    defines_string = "KEY1=VALUE1\nKEY2=VALUE2"
    expected = {"KEY1": "VALUE1", "KEY2": "VALUE2"}
    assert parse_cmake_defines_string(defines_string) == expected


def test_parse_cmake_defines_string_multiple_defines_semicolon():
    defines_string = "KEY1=VALUE1;KEY2=VALUE2"
    expected = {"KEY1": "VALUE1", "KEY2": "VALUE2"}
    assert parse_cmake_defines_string(defines_string) == expected


def test_parse_cmake_defines_string_mixed_separators_and_whitespace():
    defines_string = "  KEY_A=VALUE_A  \nKEY_B=VALUE_B;\n  KEY_C=VALUE_C  "
    expected = {"KEY_A": "VALUE_A", "KEY_B": "VALUE_B", "KEY_C": "VALUE_C"}
    assert parse_cmake_defines_string(defines_string) == expected


def test_parse_cmake_defines_string_no_value():
    assert parse_cmake_defines_string("FLAG_ON") == {"FLAG_ON": "ON"}
    assert parse_cmake_defines_string("  ANOTHER_FLAG  ") == {"ANOTHER_FLAG": "ON"}


def test_parse_cmake_defines_string_complex_values():
    defines_string = 'PATH_VAR=/usr/local/bin;MESSAGE="Hello World";VERSION=1.0.0'
    expected = {
        "PATH_VAR": "/usr/local/bin",
        "MESSAGE": '"Hello World"',
        "VERSION": "1.0.0",
    }
    assert parse_cmake_defines_string(defines_string) == expected


def test_parse_cmake_defines_string_empty_key_or_value_edge_cases():
    assert parse_cmake_defines_string("=VALUE") == {"": "VALUE"}
    assert parse_cmake_defines_string("KEY=") == {"KEY": ""}
    assert parse_cmake_defines_string("KEY1=VALUE1;=VALUE2") == {
        "KEY1": "VALUE1",
        "": "VALUE2",
    }


# New tests for ErrorAnalyzer


@pytest.fixture
def error_analyzer():
    return ErrorAnalyzer()


def test_analyze_error_msvc_compile_error(error_analyzer, mocker):
    error_output = """
    Microsoft (R) C/C++ Optimizing Compiler Version 19.29.30146 for x64
    Copyright (C) Microsoft Corporation. All rights reserved.

    main.cpp(10,5): error C2065: 'undeclared_variable': undeclared identifier
    """

    # Mock os.path.exists and open for context extraction
    mocker.patch("os.path.exists", return_value=True)
    mock_file_content = "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7\nline 8\nline 9\nundeclared_variable = 10;\nline 11\nline 12\nline 13\nline 14\nline 15\n"
    mocker.patch("builtins.open", mock_open(read_data=mock_file_content))

    error = error_analyzer.analyze_error(error_output, command_type="build")

    assert error is not None
    assert isinstance(error, StructuredError)
    assert error.error_type == "msvc_compile"
    assert error.file_path == "main.cpp"
    assert error.line_number == 10
    assert error.column_number == 5
    assert "undeclared_variable" in error.message
    assert "undeclared identifier" in error.message
    assert "Check if the variable/function is declared" in error.suggestions[0]

    assert re.search(r">>>\s+10:\s+undeclared_variable = 10;", error.context[3])


def test_analyze_error_gcc_compile_error(error_analyzer, mocker):
    error_output = """
    /home/user/project/src/main.cpp:5:10: error: 'undefined_function' was not declared in this scope
    /home/user/project/src/main.cpp:5:10: note: suggested alternative: 'defined_function'
    """

    # Mock os.path.exists and open for context extraction
    mocker.patch("os.path.exists", return_value=True)
    mock_file_content = """line 1\nline 2\nline 3\nline 4\nundefined_function(); // This is line 5\nline 6\nline 7\nline 8\nline 9\nline 10\nline 11\nline 12\nline 13\nline 14\nline 15\n"""
    mocker.patch("builtins.open", mock_open(read_data=mock_file_content))

    error = error_analyzer.analyze_error(error_output, command_type="build")

    assert error is not None
    assert isinstance(error, StructuredError)
    assert error.error_type == "gcc_compile"
    assert error.file_path == "/home/user/project/src/main.cpp"
    assert error.line_number == 5
    assert error.column_number == 10
    assert "'undefined_function' was not declared in this scope" in error.message
    assert "Check if the variable/function is declared" in error.suggestions[0]
    assert re.search(
        r">>>\s+5:\s+undefined_function\(\);\s*// This is line 5", error.context[3]
    )


def test_analyze_error_msvc_link_error(error_analyzer):
    error_output = """
    Microsoft (R) Incremental Linker Version 14.29.30146.0
    Copyright (C) Microsoft Corporation. All rights reserved.

    main.obj : error LNK2019: unresolved external symbol "void __cdecl undefined_function(void)" (?undefined_function@@YAXXZ) referenced in function main
    main.exe : fatal error LNK1120: 1 unresolved externals
    """

    error = error_analyzer.analyze_error(error_output, command_type="build")

    assert error is not None
    assert isinstance(error, StructuredError)
    assert error.error_type == "msvc_link"
    assert error.file_path == "main.obj"  # Or main.exe, depending on regex capture
    assert error.line_number is None
    assert error.column_number is None
    assert "unresolved external symbol" in error.message
    assert "Verify that all necessary libraries are linked" in error.suggestions


def test_analyze_error_gcc_link_error(error_analyzer):
    error_output = """
    /usr/bin/ld: /tmp/ccXg1234.o: in function `main`:
    main.c:(.text+0x1a): undefined reference to `undefined_function`
    collect2: error: ld returned 1 exit status
    """

    error = error_analyzer.analyze_error(error_output, command_type="build")

    assert error is not None
    assert isinstance(error, StructuredError)
    assert error.error_type == "gcc_link"
    assert error.file_path == "main.c"  # Or /tmp/ccXg1234.o, depending on regex capture
    assert error.line_number is None
    assert error.column_number is None
    assert "undefined reference to `undefined_function`" in error.message
    assert (
        "Check if the referenced function/variable is implemented"
        in error.suggestions[0]
    )


def test_analyze_error_cmake_config_error(error_analyzer):
    error_output = """
    CMake Error at CMakeLists.txt:10 (find_package):
      Could not find a package configuration file provided by "SomeLibrary" with
      any of the following names:

        SomeLibraryConfig.cmake
        somelibrary-config.cmake

      Add the installation prefix of "SomeLibrary" to CMAKE_PREFIX_PATH or set
      "SomeLibrary_DIR" to a directory containing one of the above files.  If
      "SomeLibrary" provides a separate development package or SDK, be sure it has
      been installed.
    """

    error = error_analyzer.analyze_error(error_output, command_type="cmake")

    assert error is not None
    assert isinstance(error, StructuredError)
    assert error.error_type == "cmake_config"
    assert error.file_path == "CMakeLists.txt"
    assert error.line_number == 10
    assert error.column_number is None
    assert (
        'Could not find a package configuration file provided by "SomeLibrary"'
        in error.message
    )
    assert "Check CMakeLists.txt syntax and configuration" in error.suggestions[0]


def test_analyze_error_ctest_failure(error_analyzer):
    error_output = """
    1/2 Test #1: MyTestName .....................***Failed
    2/2 Test #2: AnotherTestName ................ Passed
    """

    error = error_analyzer.analyze_error(error_output, command_type="test")

    assert error is not None
    assert isinstance(error, StructuredError)
    assert error.error_type == "test_failed"
    assert error.file_path is None
    assert error.line_number is None
    assert error.column_number is None
    assert "MyTestName .....................***Failed" in error.message
    assert "Review the full error output for more details" in error.suggestions[0]


def test_analyze_error_no_error_found(error_analyzer):
    error_output = """
    Building CXX object CMakeFiles/MyProject.dir/src/main.cpp.o
    [100%] Linking CXX executable MyProject
    [100%] Built target MyProject
    """

    error = error_analyzer.analyze_error(error_output, command_type="build")

    assert error is None


def test_analyze_error_generic_error(error_analyzer):
    error_output = """
    An unexpected error occurred during compilation.
    Error: Something went wrong.
    Fatal: Disk full.
    """

    error = error_analyzer.analyze_error(error_output, command_type="build")

    assert error is not None
    assert isinstance(error, StructuredError)
    assert error.error_type == "build_generic"
    assert error.file_path is None
    assert error.line_number is None
    assert error.column_number is None
    assert (
        "An unexpected error occurred during compilation." in error.message
    )  # Should capture the first error line
    assert "Review the full error output for more details" in error.suggestions[0]


def test_extract_error_details_msvc_compile_error(error_analyzer):
    error_output = """
    Microsoft (R) C/C++ Optimizing Compiler Version 19.29.30146 for x64
    Copyright (C) Microsoft Corporation. All rights reserved.

    main.cpp(10,5): error C2065: 'undeclared_variable': undeclared identifier
    """

    details = error_analyzer.extract_error_details(error_output)

    assert details is not None
    assert details["compiler_info"] == "MSVC"
    assert details["error_count_by_type"]["msvc_error"] == 1
    assert len(details["files_with_errors"]) == 1

    error_file = details["files_with_errors"][0]
    assert error_file["file"] == "main.cpp"
    assert error_file["line"] == 10
    assert error_file["column"] == 5
    assert error_file["type"] == "msvc_error"
    assert error_file["code"] == "C2065"
    assert "undeclared identifier" in error_file["message"]


def test_extract_error_details_gcc_compile_error(error_analyzer):
    error_output = """
    /home/user/project/src/main.cpp:5:10: error: 'undefined_function' was not declared in this scope
    /home/user/project/src/main.cpp:5:10: note: suggested alternative: 'defined_function'
    """

    details = error_analyzer.extract_error_details(error_output)

    assert details is not None
    assert details["compiler_info"] == "GCC"  # Or Clang, depending on the output
    assert details["error_count_by_type"]["gcc_error"] == 1
    assert len(details["files_with_errors"]) == 1

    error_file = details["files_with_errors"][0]
    assert error_file["file"] == "/home/user/project/src/main.cpp"
    assert error_file["line"] == 5
    assert error_file["column"] == 10
    assert error_file["type"] == "gcc_error"
    assert error_file["code"] is None
    assert (
        "'undefined_function' was not declared in this scope" in error_file["message"]
    )


def test_get_source_context_enhanced(error_analyzer, mocker):
    file_path = "src/main.cpp"
    line_number = 5
    context_lines = 2

    mock_file_content = """#include <iostream>\n
int main() {\n    std::cout << "Hello, World!" << std::endl;\n    return 0;\n}\n"""

    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("builtins.open", mock_open(read_data=mock_file_content))

    context_info = error_analyzer.get_source_context_enhanced(
        file_path, line_number, context_lines
    )

    assert context_info["file_path"] == file_path
    assert context_info["line_number"] == line_number
    assert context_info["file_exists"] is True
    assert context_info["file_language"] == "cpp"
    assert context_info["total_lines"] == 6
    assert context_info["error_line_content"] == "    return 0;"

    assert len(context_info["context_lines"]) == 4  # 2 before, 1 error line, 1 after

    error_line_info = context_info["context_lines"][2]
    assert error_line_info["line_number"] == 5
    assert error_line_info["content"] == "    return 0;"
    assert error_line_info["is_error_line"] is True
    assert error_line_info["distance_from_error"] == 0


def test_generate_suggestions(error_analyzer):
    # Test for compile error with "undeclared"
    suggestions = error_analyzer._generate_suggestions(
        "msvc_compile", "undeclared identifier"
    )
    assert (
        "Check if the variable/function is declared in the current scope" in suggestions
    )
    assert "Verify that necessary header files are included" in suggestions
    assert "Check for typos in variable/function names" in suggestions

    # Test for compile error with "syntax"
    suggestions = error_analyzer._generate_suggestions("gcc_compile", "syntax error")
    assert "Check for missing semicolons or brackets" in suggestions
    assert "Verify proper syntax according to language standards" in suggestions
    assert "Check for unmatched parentheses or braces" in suggestions

    # Test for linker error with "undefined reference"
    suggestions = error_analyzer._generate_suggestions(
        "gcc_link", "undefined reference to `my_func`"
    )
    assert "Check if the referenced function/variable is implemented" in suggestions
    assert "Verify that all necessary libraries are linked" in suggestions
    assert "Check for missing object files in the build" in suggestions

    # Test for CMake error
    suggestions = error_analyzer._generate_suggestions(
        "cmake_config", "Could not find a package"
    )
    assert "Check CMakeLists.txt syntax and configuration" in suggestions
    assert "Verify that all required dependencies are available" in suggestions
    assert "Check CMake version compatibility" in suggestions

    # Test for generic error
    suggestions = error_analyzer._generate_suggestions(
        "generic", "Something went wrong"
    )
    assert "Review the full error output for more details" in suggestions

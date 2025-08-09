import re
from unittest.mock import mock_open, patch

import pytest

from mcp_cmake import ErrorAnalyzer, StructuredError, parse_cmake_defines_string


@pytest.mark.parametrize(
    "defines_string, expected_dict",
    [
        ("", {}),
        ("   ", {}),
        ("KEY=VALUE", {"KEY": "VALUE"}),
        ("  ANOTHER_KEY = ANOTHER_VALUE  ", {"ANOTHER_KEY": "ANOTHER_VALUE"}),
        ("KEY1=VALUE1\nKEY2=VALUE2", {"KEY1": "VALUE1", "KEY2": "VALUE2"}),
        ("KEY1=VALUE1;KEY2=VALUE2", {"KEY1": "VALUE1", "KEY2": "VALUE2"}),
        (
            "  KEY_A=VALUE_A  \nKEY_B=VALUE_B;\n  KEY_C=VALUE_C  ",
            {"KEY_A": "VALUE_A", "KEY_B": "VALUE_B", "KEY_C": "VALUE_C"},
        ),
        ("FLAG_ON", {"FLAG_ON": "ON"}),
        ("  ANOTHER_FLAG  ", {"ANOTHER_FLAG": "ON"}),
        (
            'PATH_VAR=/usr/local/bin;MESSAGE="Hello World";VERSION=1.0.0',
            {
                "PATH_VAR": "/usr/local/bin",
                "MESSAGE": '"Hello World"',
                "VERSION": "1.0.0",
            },
        ),
        ("=VALUE", {"": "VALUE"}),
        ("KEY=", {"KEY": ""}),
        ("KEY1=VALUE1;=VALUE2", {"KEY1": "VALUE1", "": "VALUE2"}),
    ],
)
def test_parse_cmake_defines_string_parameterized(defines_string, expected_dict):
    assert parse_cmake_defines_string(defines_string) == expected_dict


@pytest.fixture
def error_analyzer():
    return ErrorAnalyzer()


@pytest.mark.parametrize(
    "error_output, command_type, expected_error_type, expected_file_path, expected_line_number, expected_column_number, expected_message_substring, expected_suggestions_substring, mock_file_content, expected_context_regex",
    [
        # MSVC Compile Error
        (
            """
Microsoft (R) C/C++ Optimizing Compiler Version 19.29.30146 for x64
Copyright (C) Microsoft Corporation. All rights reserved.

main.cpp(10,5): error C2065: 'undeclared_variable': undeclared identifier
""",
            "build",
            "msvc_compile",
            "main.cpp",
            10,
            5,
            "undeclared_variable",
            "Check if the variable/function is declared in the current scope",
            "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7\nline 8\nline 9\nundeclared_variable = 10;\nline 11\nline 12\nline 13\nline 14\nline 15\n",
            r">>>\s+10:\s+undeclared_variable = 10;",
        ),
        # GCC Compile Error
        (
            """
/home/user/project/src/main.cpp:5:10: error: 'undefined_function' was not declared in this scope
/home/user/project/src/main.cpp:5:10: note: suggested alternative: 'defined_function' 
""",
            "build",
            "gcc_compile",
            "/home/user/project/src/main.cpp",
            5,
            10,
            "'undefined_function' was not declared in this scope",
            "Check if the variable/function is declared in the current scope",
            "line 1\nline 2\nline 3\nline 4\nundefined_function(); // This is line 5\nline 6\nline 7\nline 8\nline 9\nline 10\nline 11\nline 12\nline 13\nline 14\nline 15\n",
            r">>>\s+5:\s+undefined_function\(\);\s*// This is line 5",
        ),
        # MSVC Link Error
        (
            """
Microsoft (R) Incremental Linker Version 14.29.30146.0
Copyright (C) Microsoft Corporation. All rights reserved.

main.obj : error LNK2019: unresolved external symbol \"void __cdecl undefined_function(void)\" (?undefined_function@@YAXXZ) referenced in function main
main.exe : fatal error LNK1120: 1 unresolved externals
""",
            "build",
            "msvc_link",
            "main.obj",
            None,
            None,
            "unresolved external symbol",
            "Verify that all necessary libraries are linked",
            None,  # No file content needed for link errors
            None,
        ),
        # GCC Link Error
        (
            """
/usr/bin/ld: /tmp/ccXg1234.o: in function `main`:
main.c:(.text+0x1a): undefined reference to `undefined_function`
collect2: error: ld returned 1 exit status
""",
            "build",
            "gcc_link",
            "main.c",
            None,
            None,
            "undefined reference to `undefined_function`",
            "Check if the referenced function/variable is implemented",
            None,  # No file content needed for link errors
            None,
        ),
        # CMake Config Error
        (
            """
CMake Error at CMakeLists.txt:10 (find_package):
  Could not find a package configuration file provided by \"SomeLibrary\" with
  any of the following names:

    SomeLibraryConfig.cmake
    somelibrary-config.cmake

  Add the installation prefix of \"SomeLibrary\" to CMAKE_PREFIX_PATH or set
  \"SomeLibrary_DIR\" to a directory containing one of the above files.  If
  \"SomeLibrary\" provides a separate development package or SDK, be sure it has
  been installed.
""",
            "cmake",
            "cmake_config",
            "CMakeLists.txt",
            10,
            None,
            'Could not find a package configuration file provided by "SomeLibrary"',
            "Check CMakeLists.txt syntax and configuration",
            None,  # No file content needed for cmake errors
            None,
        ),
        # CTest Failure
        (
            """
1/2 Test #1: MyTestName .....................***Failed
2/2 Test #2: AnotherTestName ................ Passed
""",
            "test",
            "test_failed",
            None,
            None,
            None,
            "MyTestName .....................***Failed",
            "Review the full error output for more details",
            None,  # No file content needed for test errors
            None,
        ),
        # No Error Found
        (
            """
Building CXX object CMakeFiles/MyProject.dir/src/main.cpp.o
[100%] Linking CXX executable MyProject
[100%] Built target MyProject
""",
            "build",
            None,
            None,
            None,
            None,
            None,
            None,
            None,  # mock_file_content
            None,  # expected_context_regex
        ),
        # Generic Error
        (
            """
An unexpected error occurred during compilation.
Error: Something went wrong.
Fatal: Disk full.
""",
            "build",
            "build_generic",
            None,
            None,
            None,
            "An unexpected error occurred during compilation.",
            "Review the full error output for more details",
            None,  # No file content needed for generic error
            None,
        ),
    ],
)
def test_analyze_error_parameterized(
    error_analyzer,
    mocker,
    error_output,
    command_type,
    expected_error_type,
    expected_file_path,
    expected_line_number,
    expected_column_number,
    expected_message_substring,
    expected_suggestions_substring,
    mock_file_content,
    expected_context_regex,
):
    # Mock os.path.exists and open for context extraction if mock_file_content is provided
    if mock_file_content is not None:
        mocker.patch("os.path.exists", return_value=True)
        mocker.patch("builtins.open", mock_open(read_data=mock_file_content))
    else:
        mocker.patch(
            "os.path.exists", return_value=False
        )  # Ensure no file is read if not needed

    error = error_analyzer.analyze_error(error_output, command_type=command_type)

    if expected_error_type is None:
        assert error is None
    else:
        assert error is not None
        assert isinstance(error, StructuredError)
        assert error.error_type == expected_error_type
        assert error.file_path == expected_file_path
        assert error.line_number == expected_line_number
        assert error.column_number == expected_column_number
        assert expected_message_substring in error.message
        assert expected_suggestions_substring in error.suggestions

        if expected_context_regex:
            assert re.search(expected_context_regex, error.context[3])


@pytest.mark.parametrize(
    "error_output, expected_compiler_info, expected_error_count, expected_file_path, expected_line, expected_column, expected_type, expected_code, expected_message_substring",
    [
        # MSVC Compile Error Details
        (
            """
Microsoft (R) C/C++ Optimizing Compiler Version 19.29.30146 for x64
Copyright (C) Microsoft Corporation. All rights reserved.

main.cpp(10,5): error C2065: 'undeclared_variable': undeclared identifier
""",
            "MSVC",
            {"msvc_error": 1},
            "main.cpp",
            10,
            5,
            "msvc_error",
            "C2065",
            "undeclared identifier",
        ),
        # GCC Compile Error Details
        (
            """
/home/user/project/src/main.cpp:5:10: error: 'undefined_function' was not declared in this scope
/home/user/project/src/main.cpp:5:10: note: suggested alternative: 'defined_function'
""",
            "GCC",
            {"gcc_error": 1},
            "/home/user/project/src/main.cpp",
            5,
            10,
            "gcc_error",
            None,
            "'undefined_function' was not declared in this scope",
        ),
    ],
)
def test_extract_error_details_parameterized(
    error_analyzer,
    error_output,
    expected_compiler_info,
    expected_error_count,
    expected_file_path,
    expected_line,
    expected_column,
    expected_type,
    expected_code,
    expected_message_substring,
):
    details = error_analyzer.extract_error_details(error_output)

    assert details is not None
    assert details["compiler_info"] == expected_compiler_info
    assert details["error_count_by_type"] == expected_error_count
    assert len(details["files_with_errors"]) == 1

    error_file = details["files_with_errors"][0]
    assert error_file["file"] == expected_file_path
    assert error_file["line"] == expected_line
    assert error_file["column"] == expected_column
    assert error_file["type"] == expected_type
    assert error_file["code"] == expected_code
    assert expected_message_substring in error_file["message"]


@pytest.mark.parametrize(
    "error_type, message, expected_suggestions",
    [
        (
            "msvc_compile",
            "undeclared identifier",
            [
                "Check if the variable/function is declared in the current scope",
                "Verify that necessary header files are included",
                "Check for typos in variable/function names",
            ],
        ),
        (
            "gcc_compile",
            "syntax error",
            [
                "Check for missing semicolons or brackets",
                "Verify proper syntax according to language standards",
                "Check for unmatched parentheses or braces",
            ],
        ),
        (
            "gcc_link",
            "undefined reference to `my_func`",
            [
                "Check if the referenced function/variable is implemented",
                "Verify that all necessary libraries are linked",
                "Check for missing object files in the build",
            ],
        ),
        (
            "cmake_config",
            "Could not find a package",
            [
                "Check CMakeLists.txt syntax and configuration",
                "Verify that all required dependencies are available",
                "Check CMake version compatibility",
            ],
        ),
        (
            "generic",
            "Something went wrong",
            [
                "Review the full error output for more details",
            ],
        ),
    ],
)
def test_generate_suggestions_parameterized(
    error_analyzer, error_type, message, expected_suggestions
):
    suggestions = error_analyzer._generate_suggestions(error_type, message)
    assert suggestions == expected_suggestions


def test_get_source_context_enhanced(error_analyzer, mocker):
    file_path = "src/main.cpp"
    line_number = 5
    context_lines = 2

    mock_file_content = "".join(
        [
            "#include <iostream>\n",
            "\n",  # Empty line
            "int main() {\n",
            '    std::cout << "Hello, World!" << std::endl;\n',
            "    return 0;\n",
            "}\n",
        ]
    )

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

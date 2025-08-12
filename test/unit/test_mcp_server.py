from unittest.mock import MagicMock, patch

import pytest

import mcp_cmake.mcp_cmake_core as mcp_core

# This import will fail initially, which is expected in TDD
import mcp_cmake.mcp_cmake_server as mcp_server


@patch("mcp_cmake.mcp_cmake_core.health_check")
def test_health_check_calls_core_function(mock_core_health_check):
    """
    Tests if the server's health_check tool correctly calls the core health_check function.
    """
    # Arrange
    expected_result = {"status": "ok"}
    mock_core_health_check.return_value = expected_result

    # Act
    result = mcp_server.health_check(working_dir="/fake/dir")

    # Assert
    mock_core_health_check.assert_called_once_with(working_dir="/fake/dir")
    assert result == expected_result


@patch("mcp_cmake.mcp_cmake_core.list_presets")
def test_list_presets_calls_core_function(mock_core_list_presets):
    """
    Tests if the server's list_presets tool correctly calls the core list_presets function.
    """
    # Arrange
    # The core function is a generator, so we mock its return value as a list of strings.
    mock_core_list_presets.return_value = iter(["preset1", "preset2"])
    expected_result = (
        "preset1preset2"  # The server function should concatenate the output
    )

    # Act
    result = mcp_server.list_presets(working_dir="/fake/dir")

    # Assert
    mock_core_list_presets.assert_called_once_with(working_dir="/fake/dir")
    assert result == expected_result


@patch("mcp_cmake.mcp_cmake_core.configure_project")
def test_configure_project_calls_core_function(mock_core_configure):
    """
    Tests if the server's configure_project tool correctly calls the core configure_project function.
    """
    # Arrange
    mock_core_configure.return_value = iter(["Configuring...", "Done."])
    expected_result = "Configuring...Done."
    cmake_defines = {"MY_VAR": "ON"}

    # Act
    result = mcp_server.configure_project(
        preset="my-preset", working_dir="/fake/dir", cmake_defines=cmake_defines
    )

    # Assert
    mock_core_configure.assert_called_once_with(
        preset="my-preset", working_dir="/fake/dir", cmake_defines=cmake_defines
    )
    assert result == expected_result


@patch("mcp_cmake.mcp_cmake_core.build_project")
def test_build_project_calls_core_function(mock_core_build):
    """
    Tests if the server's build_project tool correctly calls the core build_project function.
    """
    # Arrange
    mock_core_build.return_value = iter(["Building...", "Success."])
    expected_result = "Building...Success."
    targets = ["all", "clean"]

    # Act
    result = mcp_server.build_project(
        preset="my-build-preset",
        targets=targets,
        working_dir="/fake/dir",
        verbose=True,
        parallel_jobs=8,
    )

    # Assert
    mock_core_build.assert_called_once_with(
        preset="my-build-preset",
        targets=targets,
        working_dir="/fake/dir",
        verbose=True,
        parallel_jobs=8,
    )
    assert result == expected_result


@patch("mcp_cmake.mcp_cmake_core.test_project")
def test_test_project_calls_core_function(mock_core_test):
    """
    Tests if the server's test_project tool correctly calls the core test_project function.
    """
    # Arrange
    mock_core_test.return_value = iter(["Testing...", "All tests passed."])
    expected_result = "Testing...All tests passed."

    # Act
    result = mcp_server.test_project(
        preset="my-test-preset",
        working_dir="/fake/dir",
        verbose=True,
        test_filter="MyTest*",
        parallel_jobs=4,
    )

    # Assert
    mock_core_test.assert_called_once_with(
        preset="my-test-preset",
        working_dir="/fake/dir",
        verbose=True,
        test_filter="MyTest*",
        parallel_jobs=4,
    )
    assert result == expected_result


@patch("mcp_cmake.mcp_cmake_core.format_error_for_llm_analysis")
def test_format_error_for_llm_analysis_calls_core_function(mock_core_format_error):
    """
    Tests if the server's format_error_for_llm_analysis tool correctly calls the core function.
    """
    # Arrange
    mock_core_format_error.return_value = "Formatted Error String"
    error_output = "raw error text"
    error_type = "build"
    command = "cmake --build ."
    working_dir = "/fake/dir"

    # Act
    result = mcp_server.format_error_for_llm_analysis(
        error_output=error_output,
        error_type=error_type,
        command=command,
        working_dir=working_dir,
    )

    # Assert
    mock_core_format_error.assert_called_once_with(
        error_output=error_output,
        error_type=error_type,
        command=command,
        working_dir=working_dir,
    )
    assert result == "Formatted Error String"

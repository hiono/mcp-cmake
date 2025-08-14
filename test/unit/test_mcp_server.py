from unittest.mock import patch
import pytest
from mcp_cmake.mcp_cmake_server import mcp

pytestmark = pytest.mark.asyncio

async def get_tool_func(tool_name):
    tool = await mcp.get_tool(tool_name)
    return tool.fn

@patch("mcp_cmake.mcp_cmake_core.health_check")
async def test_health_check_calls_core_function(mock_core_health_check):
    """
    Tests if the server's health_check tool correctly calls the core health_check function.
    """
    # Arrange
    expected_result = {"status": "ok"}
    mock_core_health_check.return_value = expected_result
    health_check_tool = await get_tool_func('health_check')

    # Act
    result = health_check_tool(working_dir="/fake/dir")

    # Assert
    mock_core_health_check.assert_called_once_with(working_dir="/fake/dir")
    assert result == expected_result


@patch("mcp_cmake.mcp_cmake_core.list_presets")
async def test_list_presets_calls_core_function(mock_core_list_presets):
    """
    Tests if the server's list_presets tool correctly calls the core list_presets function.
    """
    # Arrange
    # The core function is a generator, so we mock its return value as a list of strings.
    mock_core_list_presets.return_value = iter(["preset1", "preset2"])
    list_presets_tool = await get_tool_func('list_presets')

    # Act
    result = list_presets_tool(working_dir="/fake/dir")

    # Assert
    mock_core_list_presets.assert_called_once_with(working_dir="/fake/dir")
    # The server function returns a list.
    assert result == ["preset1", "preset2"]


@patch("mcp_cmake.mcp_cmake_core.configure_project")
async def test_configure_project_calls_core_function(mock_core_configure):
    """
    Tests if the server's configure_project tool correctly calls the core configure_project function.
    """
    # Arrange
    mock_core_configure.return_value = iter(["Configuring...", "Done."])
    expected_result = "Configuring...Done."
    cmake_defines = {"MY_VAR": "ON"}
    configure_project_tool = await get_tool_func('configure_project')

    # Act
    result = configure_project_tool(
        preset="my-preset", working_dir="/fake/dir", cmake_defines=cmake_defines
    )

    # Assert
    mock_core_configure.assert_called_once_with(
        preset="my-preset", working_dir="/fake/dir", cmake_defines=cmake_defines
    )
    assert result == expected_result


@patch("mcp_cmake.mcp_cmake_core.build_project")
async def test_build_project_calls_core_function(mock_core_build):
    """
    Tests if the server's build_project tool correctly calls the core build_project function.
    """
    # Arrange
    mock_core_build.return_value = iter(["Building...", "Success."])
    expected_result = "Building...Success."
    targets = ["all", "clean"]
    build_project_tool = await get_tool_func('build_project')

    # Act
    result = build_project_tool(
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
async def test_test_project_calls_core_function(mock_core_test):
    """
    Tests if the server's test_project tool correctly calls the core test_project function.
    """
    # Arrange
    mock_core_test.return_value = iter(["Testing...", "All tests passed."])
    expected_result = "Testing...All tests passed."
    test_project_tool = await get_tool_func('test_project')

    # Act
    result = test_project_tool(
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
async def test_format_error_for_llm_analysis_calls_core_function(mock_core_format_error):
    """
    Tests if the server's format_error_for_llm_analysis tool correctly calls the core function.
    """
    # Arrange
    mock_core_format_error.return_value = "Formatted Error String"
    error_output = "raw error text"
    error_type = "build"
    command = "cmake --build ."
    working_dir = "/fake/dir"
    format_error_tool = await get_tool_func('format_error_for_llm_analysis')

    # Act
    result = format_error_tool(
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

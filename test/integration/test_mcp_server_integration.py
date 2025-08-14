import pytest
from fastmcp.client import Client
from mcp_cmake.mcp_cmake_server import mcp
import json
import os
import shutil
import sys
import tempfile
import subprocess

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio

@pytest.fixture(scope="function")
def client(mocker):
    """Provides a client for the MCP server with a mocked environment."""
    # Create a temporary directory for dummy cmake/ctest executables
    temp_bin_dir = tempfile.mkdtemp()
    if sys.platform == "win32":
        cmake_exe = os.path.join(temp_bin_dir, "cmake.bat")
        ctest_exe = os.path.join(temp_bin_dir, "ctest.bat")
        with open(cmake_exe, "w") as f:
            f.write("@echo off\necho cmake version 3.20.0\nexit /b 0")
        with open(ctest_exe, "w") as f:
            f.write("@echo off\necho ctest version 3.20.0\nexit /b 0")
    else:
        cmake_exe = os.path.join(temp_bin_dir, "cmake")
        ctest_exe = os.path.join(temp_bin_dir, "ctest")
        with open(cmake_exe, "w") as f:
            f.write("#!/bin/bash\necho cmake version 3.20.0\nexit 0")
        with open(ctest_exe, "w") as f:
            f.write("#!/bin/bash\necho ctest version 3.20.0\nexit 0")
        os.chmod(cmake_exe, 0o755)
        os.chmod(ctest_exe, 0o755)

    # Prepare environment for subprocess (still needed for the server's subprocess calls)
    env = os.environ.copy()
    env["PATH"] = temp_bin_dir + os.pathsep + env["PATH"]

    # Patch subprocess.Popen to inject the modified environment
    original_popen = subprocess.Popen
    def mock_popen(cmd, *args, **kwargs):
        if ("cmake" in cmd or "ctest" in cmd) and "--version" in cmd:
            kwargs['env'] = env # Inject the modified environment
            return original_popen(cmd, *args, **kwargs)
        return original_popen(cmd, *args, **kwargs)
    mocker.patch('subprocess.Popen', side_effect=mock_popen)

    # Create dummy CMake files
    sample_dir = os.path.join(os.getcwd(), "sample")
    os.makedirs(sample_dir, exist_ok=True)
    with open(os.path.join(sample_dir, "CMakeLists.txt"), "w") as f:
        f.write("cmake_minimum_required(VERSION 3.20)")
    with open(os.path.join(sample_dir, "CMakePresets.json"), "w") as f:
        f.write("{\"version\": 3, \"configurePresets\": [{\"name\": \"default\", \"displayName\": \"Default Config\", \"description\": \"Default build settings\", \"generator\": \"Ninja\", \"binaryDir\": \"${sourceDir}/build/default\"}], \"buildPresets\": [{\"name\": \"default\", \"configurePreset\": \"default\"}], \"testPresets\": [{\"name\": \"default\", \"configurePreset\": \"default\"}]}")

    yield Client(mcp)

    # Clean up the temporary bin directory
    if os.path.exists(temp_bin_dir):
        shutil.rmtree(temp_bin_dir)

@pytest.fixture(autouse=True)
def clean_build_dir():
    """Cleans up the build directory before and after tests."""
    _project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    build_dir = os.path.join(_project_root, "sample", "build")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    yield
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)


async def test_tools_list_schema(client: Client):
    """tools/listメソッドを呼び出し、スキーマを検証する"""
    async with client:
        tools_list = await client.list_tools()
    tools = {tool.name: tool for tool in tools_list}

    print("\n--- TOOLS/LIST SCHEMA ---")
    import pprint
    pprint.pprint(tools)
    print("------------------------")

    expected_tools = [
        "health_check",
        "list_presets",
        "configure_project",
        "build_project",
        "test_project",
        "format_error_for_llm_analysis",
    ]
    assert set(tools.keys()) == set(expected_tools)
    assert (
        tools["health_check"].inputSchema['properties']['working_dir']['default']
        == "sample"
    )

@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_substring"),
    [
        ("health_check", {"working_dir": "sample"}, '"overall_status": "healthy"'),
        ("list_presets", {"working_dir": "sample"}, 'default'),
        (
            "configure_project",
            {"preset": "default", "working_dir": "sample"},
            "Build files have been written to",
        ),
        (
            "build_project",
            {"preset": "default", "working_dir": "sample"},
            "Building",
        ),
        (
            "test_project",
            {"preset": "default", "working_dir": "sample"},
            "No tests were found",
        ),
        (
            "format_error_for_llm_analysis",
            {"error_output": "error: an error occurred"},
            "COMPREHENSIVE ERROR ANALYSIS",
        ),
    ],
)
async def test_tools_call_for_all_tools(
    client: Client, tool_name, arguments, expected_substring
):
    """tools/callメソッドを呼び出し、各ツールの動作を検証する"""
    async with client:
        result = await client.call_tool(tool_name, arguments)

    # The result can be a string or a dict/list that gets jsonified.
    if isinstance(result.data, (dict, list)):
        result_str = json.dumps(result.data)
    else:
        result_str = str(result.data)

    assert expected_substring in result_str
    if tool_name == "build_project":
        assert "[ERROR]" not in result_str

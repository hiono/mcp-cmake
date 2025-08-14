import json
import os
import subprocess

import pytest
from packaging.version import Version

from mcp_cmake.mcp_cmake_core import health_check

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PRESET_FILE = os.path.join(_project_root, "sample", "CMakePresets.json")

def get_minimum_cmake_version(preset_file_path):
    with open(preset_file_path, "r") as f:
        presets = json.load(f)
    min_req = presets.get("cmakeMinimumRequired", {})
    major = min_req.get("major", 0)
    minor = min_req.get("minor", 0)
    patch = min_req.get("patch", 0)
    return Version(f"{major}.{minor}.{patch}")

def test_cmake_ctest_version_meets_minimum_required():
    min_cmake_version = get_minimum_cmake_version(PRESET_FILE)

    current_cmake_version = Version(subprocess.run(["cmake", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0].split(" ")[2])
    current_ctest_version = Version(subprocess.run(["ctest", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0].split(" ")[2])

    assert (
        current_cmake_version >= min_cmake_version
    ), f"CMake version {current_cmake_version} is less than required {min_cmake_version}"
    assert (
        current_ctest_version >= min_cmake_version
    ), f"CTest version {current_ctest_version} is less than required {min_cmake_version}"

def test_health_check_cmake_not_found(mocker):
    original_subprocess_run = subprocess.run

    def mock_subprocess_run(cmd, *args, **kwargs):
        if "cmake" in cmd:
            raise FileNotFoundError("cmake not found")
        elif "ctest" in cmd:
            mock_result = mocker.Mock()
            mock_result.returncode = 0
            mock_result.stdout = "ctest version 3.20.0\n"
            return mock_result
        else:
            return original_subprocess_run(cmd, *args, **kwargs)

    mocker.patch("subprocess.run", side_effect=mock_subprocess_run)
    mocker.patch(
        "os.path.exists", return_value=True
    )

    health_status = health_check()

    assert health_status["overall_status"] == "critical"
    assert health_status["cmake_available"] is False
    assert "CMake not found in system PATH" in health_status["issues"]
    assert (
        "Install CMake and ensure it's added to system PATH"
        in health_status["recommendations"]
    )

    assert health_status["ctest_available"] is True
    assert health_status["cmake_presets_exists"] is True
    assert health_status["working_directory_exists"] is True

@pytest.mark.parametrize(
    "cmake_mock_version, ctest_mock_version, expected_overall_status, expected_issues_substrings",
    [
        ("3.19.0", "3.19.0", "critical", ["CMake version 3.19.0 is older than required", "CTest version 3.19.0 is older than required"]),
        ("3.21.0", "3.21.0", "healthy", []),
        ("3.19.0", "3.21.0", "critical", ["CMake version 3.19.0 is older than required"]),
        ("3.21.0", "3.19.0", "critical", ["CTest version 3.19.0 is older than required"]),
        ("3.20.0", "3.20.0", "healthy", []),
    ]
)
def test_cmake_ctest_version_compatibility(
    mocker,
    cmake_mock_version,
    ctest_mock_version,
    expected_overall_status,
    expected_issues_substrings,
):
    mocker.patch("os.path.isdir", return_value=True)
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("json.load", return_value={"version": 3, "cmakeMinimumRequired": {"major": 3, "minor": 20, "patch": 0}})

    def mock_subprocess_run(cmd, *args, **kwargs):
        mock_result = mocker.Mock()
        mock_result.returncode = 0
        if "cmake" in cmd:
            mock_result.stdout = f"cmake version {cmake_mock_version}\n"
        elif "ctest" in cmd:
            mock_result.stdout = f"ctest version {ctest_mock_version}\n"
        return mock_result

    mocker.patch("subprocess.run", side_effect=mock_subprocess_run)

    health_status = health_check()

    assert health_status["overall_status"] == expected_overall_status

    for substring in expected_issues_substrings:
        assert any(substring in issue for issue in health_status["issues"])

    if not expected_issues_substrings:
        assert not health_status["issues"]
    else:
        assert len(health_status["issues"]) == len(expected_issues_substrings)

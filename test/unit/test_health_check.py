import json
import os  # Import os for mocking os.path.exists
import subprocess

import pytest
from packaging.version import Version

from mcp_cmake.mcp_cmake_core import health_check  # Import health_check


def get_cmake_version():
    result = subprocess.run(
        ["cmake", "--version"], capture_output=True, text=True, check=True
    )
    version_line = result.stdout.splitlines()[0]
    return Version(version_line.split(" ")[2])


def get_ctest_version():
    result = subprocess.run(
        ["ctest", "--version"], capture_output=True, text=True, check=True
    )
    version_line = result.stdout.splitlines()[0]
    return Version(version_line.split(" ")[2])


def get_minimum_cmake_version(preset_file_path):
    with open(preset_file_path, "r") as f:
        presets = json.load(f)
    min_req = presets.get("cmakeMinimumRequired", {})
    major = min_req.get("major", 0)
    minor = min_req.get("minor", 0)
    patch = min_req.get("patch", 0)
    return Version(f"{major}.{minor}.{patch}")


def test_cmake_ctest_version_meets_minimum_required():
    preset_file = "/workspace/sample/CMakePresets.json"
    min_cmake_version = get_minimum_cmake_version(preset_file)

    current_cmake_version = get_cmake_version()
    current_ctest_version = get_ctest_version()

    assert (
        current_cmake_version >= min_cmake_version
    ), f"CMake version {current_cmake_version} is less than required {min_cmake_version}"
    assert (
        current_ctest_version >= min_cmake_version
    ), f"CTest version {current_ctest_version} is less than required {min_cmake_version}"


def test_health_check_cmake_not_found(mocker):
    # Mock subprocess.run to simulate CMake not found
    original_subprocess_run = subprocess.run

    def mock_subprocess_run(cmd, *args, **kwargs):
        if "cmake" in cmd:
            raise FileNotFoundError("cmake not found")
        elif "ctest" in cmd:
            # Simulate ctest being available
            mock_result = mocker.Mock()
            mock_result.returncode = 0
            mock_result.stdout = "ctest version 3.20.0\n"  # Provide a dummy version
            return mock_result
        else:
            return original_subprocess_run(cmd, *args, **kwargs)

    mocker.patch("subprocess.run", side_effect=mock_subprocess_run)
    mocker.patch(
        "os.path.exists", return_value=True
    )  # Mock for cmake_presets_exists and working_directory_exists

    # Call the health_check function
    health_status = health_check()

    # Assertions
    assert health_status["overall_status"] == "critical"
    assert health_status["cmake_available"] is False
    assert "CMake not found in system PATH" in health_status["issues"]
    assert (
        "Install CMake and ensure it's added to system PATH"
        in health_status["recommendations"]
    )

    # Other checks should still be true if they are mocked to pass
    assert health_status["ctest_available"] is True
    assert health_status["cmake_presets_exists"] is True
    assert health_status["working_directory_exists"] is True


def get_test_version_scenarios():
    preset_file = "/workspace/sample/CMakePresets.json"
    min_cmake_version = get_minimum_cmake_version(preset_file)

    # Calculate versions relative to min_cmake_version
    # Ensure minor version doesn't go below 0 for older_version
    older_version_minor = max(0, min_cmake_version.minor - 1)
    older_version = Version(f"{min_cmake_version.major}.{older_version_minor}.0")
    newer_version = Version(
        f"{min_cmake_version.major}.{min_cmake_version.minor + 1}.0"
    )

    return [
        # Scenario 1: Both older than minimum
        (
            str(older_version),
            str(older_version),
            "critical",
            [
                f"CMake version {older_version} is older than required {min_cmake_version}",
                f"CTest version {older_version} is older than required {min_cmake_version}",
            ],
        ),
        # Scenario 2: Both newer than minimum
        (str(newer_version), str(newer_version), "healthy", []),
        # Scenario 3: CMake older, CTest newer
        (
            str(older_version),
            str(newer_version),
            "critical",
            [
                f"CMake version {older_version} is older than required {min_cmake_version}"
            ],
        ),
        # Scenario 4: CMake newer, CTest older
        (
            str(newer_version),
            str(older_version),
            "critical",
            [
                f"CTest version {older_version} is older than required {min_cmake_version}"
            ],
        ),
        # Scenario 5: Both equal to minimum
        (str(min_cmake_version), str(min_cmake_version), "healthy", []),
    ]


@pytest.mark.parametrize(
    "cmake_mock_version, ctest_mock_version, expected_overall_status, expected_issues_substrings",
    get_test_version_scenarios(),  # Use the dynamically generated scenarios
)
def test_cmake_ctest_version_compatibility(
    mocker,
    cmake_mock_version,
    ctest_mock_version,
    expected_overall_status,
    expected_issues_substrings,
):
    preset_file = "/workspace/sample/CMakePresets.json"
    min_cmake_version = get_minimum_cmake_version(preset_file)

    # Mock os.path.isfile for CMakePresets.json
    mocker.patch("os.path.isfile", side_effect=lambda p: p == preset_file)
    mocker.patch("os.path.isdir", return_value=True)  # Mock working directory exists

    # Mock subprocess.run to return specified versions
    def mock_subprocess_run(cmd, *args, **kwargs):
        mock_result = mocker.Mock()
        mock_result.returncode = 0
        if "cmake" in cmd:
            mock_result.stdout = f"cmake version {cmake_mock_version}\n"
        elif "ctest" in cmd:
            mock_result.stdout = f"ctest version {ctest_mock_version}\n"
        return mock_result

    mocker.patch("subprocess.run", side_effect=mock_subprocess_run)

    # Call the health_check function
    health_status = health_check()

    # Assertions
    assert health_status["overall_status"] == expected_overall_status

    for substring in expected_issues_substrings:
        assert substring in health_status["issues"]

    # Ensure no unexpected issues are present
    if not expected_issues_substrings:
        assert not health_status["issues"]
    else:
        # Check that there are no other issues beyond the expected ones
        assert len(health_status["issues"]) == len(expected_issues_substrings)

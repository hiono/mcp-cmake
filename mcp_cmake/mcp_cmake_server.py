import argparse
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

import mcp_cmake.mcp_cmake_core as core

mcp = FastMCP(
    name="mcp-cmake",
    title="CMake Project Helper",
    description="A tool to help with CMake project configuration, building, testing, and error analysis.",
    host="127.0.0.1",  # デフォルトホスト
    port=8000,  # デフォルトポート
)
mcp.settings.log_level = "DEBUG"  # Set log level at top level


@mcp.tool()
def health_check(working_dir: str = "sample") -> dict:
    """Runs a health check on the system environment."""
    return core.health_check(working_dir=working_dir)


@mcp.tool()
def list_presets(working_dir: Optional[str] = None) -> str:
    """Lists available CMake presets."""
    # The core function is a generator, so we join the output.
    return "".join(list(core.list_presets(working_dir=working_dir)))


@mcp.tool()
def configure_project(
    preset: str,
    working_dir: str = "sample",
    cmake_defines: Optional[dict] = None,
) -> str:
    """Runs CMake configure."""
    return "".join(
        list(
            core.configure_project(
                preset=preset, working_dir=working_dir, cmake_defines=cmake_defines
            )
        )
    )


@mcp.tool()
def build_project(
    preset: str,
    targets: Optional[list] = None,
    working_dir: str = "sample",
    verbose: bool = False,
    parallel_jobs: Optional[int] = None,
) -> str:
    """Runs CMake build."""
    return "".join(
        list(
            core.build_project(
                preset=preset,
                targets=targets,
                working_dir=working_dir,
                verbose=verbose,
                parallel_jobs=parallel_jobs,
            )
        )
    )


@mcp.tool()
def test_project(
    preset: str = "",
    working_dir: str = "sample",
    verbose: bool = False,
    test_filter: str = "",
    parallel_jobs: Optional[int] = None,
) -> str:
    """Runs CTest."""
    return "".join(
        list(
            core.test_project(
                preset=preset,
                working_dir=working_dir,
                verbose=verbose,
                test_filter=test_filter,
                parallel_jobs=parallel_jobs,
            )
        )
    )


@mcp.tool()
def format_error_for_llm_analysis(
    error_output: str,
    error_type: str = "build",
    command: str = "",
    working_dir: str = "",
) -> str:
    """Formats an error output for LLM analysis."""
    return core.format_error_for_llm_analysis(
        error_output=error_output,
        error_type=error_type,
        command=command,
        working_dir=working_dir,
    )


def main():
    parser = argparse.ArgumentParser(description="MCP-CMake Server")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio mode.")
    parser.add_argument(
        "--host", type=str, default=mcp.settings.host, help="Host for HTTP server."
    )
    parser.add_argument(
        "--port", type=int, default=mcp.settings.port, help="Port for HTTP server."
    )
    parser.add_argument(
        "-w",
        "--working-dir",
        type=str,
        default=".",
        help="CMake project working directory.",
    )
    args = parser.parse_args()

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

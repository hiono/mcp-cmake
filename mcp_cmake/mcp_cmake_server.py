import argparse
import sys
from typing import Optional

from fastmcp import FastMCP

import mcp_cmake.mcp_cmake_core as core

# ## FastMCP Constructor Parameters
# * name: (str) default:"FastMCP" - A human-readable name for your server
# * instructions: (str|None) - Description of how to interact with this server. These instructions help clients understand the server’s purpose and available functionality
# * auth: (OAuthProvider|TokenVerifier|None) - Authentication provider for securing HTTP-based transports. See [Authentication](https://gofastmcp.com/servers/auth/authentication) for configuration options
# * lifespan: (AsyncContextManager|None) - An async context manager function for server startup and shutdown logic
# * tools: (list[Tool|Callable]|None) - A list of tools (or functions to convert to tools) to add to the server. In some cases, providing tools programmatically may be more convenient than using the decorator`@mcp.tool`
# * dependencies: (list[str]|None) - Optional server dependencies list with package specifications
# * include_tags: (set[str]|None) - Only expose components with at least one matching tag
# * exclude_tags: (set[str]|None) - Hide components with any matching tag
# * on_duplicate_tools: (Literal["error","warn","replace"]) default:"error" - How to handle duplicate tool registrations
# * on_duplicate_resources: (Literal["error","warn","replace"]) default:"warn" - How to handle duplicate resource registrations
# * on_duplicate_prompts: (Literal["error","warn","replace"]) default:"replace" - How to handle duplicate prompt registrations
# * include_fastmcp_meta: (bool) default:"True"
mcp = FastMCP(
    name="mcp-cmake",
    debug=True,
)


@mcp.tool()
def health_check(working_dir: str = "sample") -> dict:
    """Runs a health check on the system environment."""
    return core.health_check(working_dir=working_dir)


@mcp.tool()
def list_presets(working_dir: Optional[str] = None) -> list[str]:
    """Lists available CMake presets."""
    # The core function is a generator, so we join the output.
    return list(core.list_presets(working_dir=working_dir))


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
    parser.add_argument("--stdio", action="store_true", default=True, help="Run in stdio mode.")
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

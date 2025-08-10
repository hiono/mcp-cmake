
import argparse
from mcp.server.fastmcp import FastMCP
import mcp_cmake.mcp_cmake_core as core

mcp = FastMCP(
    name="mcp-cmake",
    title="CMake Project Helper",
    description="A tool to help with CMake project configuration, building, testing, and error analysis."
)

@mcp.tool()
def health_check(working_dir: str = "sample") -> dict:
    """Runs a health check on the system environment."""
    return core.health_check(working_dir)

@mcp.tool()
def list_presets(working_dir: str = "sample") -> str:
    """Lists available CMake presets."""
    output = ""
    for line in core.list_presets(working_dir=working_dir):
        output += line
    return output

@mcp.tool()
def configure_project(
    preset: str,
    working_dir: str = "sample",
    cmake_defines: dict = None,
) -> str:
    """Runs CMake configure."""
    output = ""
    for line in core.configure_project(
        preset=preset, working_dir=working_dir, cmake_defines=cmake_defines
    ):
        output += line
    return output

@mcp.tool()
def build_project(
    preset: str,
    targets: list = None,
    working_dir: str = "sample",
    verbose: bool = False,
    parallel_jobs: int = None,
) -> str:
    """Runs CMake build."""
    output = ""
    for line in core.build_project(
        preset=preset,
        targets=targets,
        working_dir=working_dir,
        verbose=verbose,
        parallel_jobs=parallel_jobs,
    ):
        output += line
    return output

@mcp.tool()
def test_project(
    preset: str = "",
    working_dir: str = "sample",
    verbose: bool = False,
    test_filter: str = "",
    parallel_jobs: int = None,
) -> str:
    """Runs CTest."""
    output = ""
    for line in core.test_project(
        preset=preset,
        working_dir=working_dir,
        verbose=verbose,
        test_filter=test_filter,
        parallel_jobs=parallel_jobs,
    ):
        output += line
    return output

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
    parser.add_argument('--stdio', action='store_true', help='Run in stdio mode.')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host for HTTP server.')
    parser.add_argument('--port', type=int, default=8000, help='Port for HTTP server.')
    parser.add_argument('-w', '--working-dir', type=str, default='.', help='CMake project working directory.')
    args = parser.parse_args()

    # NOTE: The working_dir argument is not yet used by the tools.
    # This will be implemented in subsequent steps.

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        # HTTPモードの場合、hostとportはmcp.run()に直接渡さない
        # mcp.run()が内部的にuvicornを起動する際にデフォルト値を使用する
        mcp = FastMCP(
    name="mcp-cmake",
    title="CMake Project Helper",
    description="A tool to help with CMake project configuration, building, testing, and error analysis.",
    host="127.0.0.1", # デフォルトホスト
    port=8000,       # デフォルトポート
)

# ... (ツール定義)

def main():
    parser = argparse.ArgumentParser(description="MCP-CMake Server")
    parser.add_argument('--stdio', action='store_true', help='Run in stdio mode.')
    parser.add_argument('--host', type=str, default=mcp.settings.host, help='Host for HTTP server.') # デフォルト値をmcp.settingsから取得
    parser.add_argument('--port', type=int, default=mcp.settings.port, help='Port for HTTP server.') # デフォルト値をmcp.settingsから取得
    parser.add_argument('-w', '--working-dir', type=str, default='.', help='CMake project working directory.')
    args = parser.parse_args()

    # コマンドライン引数で指定されたhostとportをmcp.settingsに反映
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    if args.stdio:
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http") # 正しいtransport名

if __name__ == "__main__":
    main()

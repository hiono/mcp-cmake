"""mcp_cmake - A CMake project management tool for MCP."""

__version__ = "0.1.0"

from .mcp_cmake_core import (
    ErrorAnalyzer,
    analyze_build_error_detailed,
    analyze_error_output,
    analyze_test_error_detailed,
    build_project,
    build_project_single_target,
    configure_project,
    copy_analysis_to_clipboard,
    execute_command,
    execute_command_with_analysis,
    extract_error_metadata,
    filter_errors_by_type,
    format_error_for_llm_analysis,
    get_common_cmake_variables,
    get_error_statistics,
    get_source_code_context,
    health_check,
    list_presets,
    parse_cmake_defines_string,
    test_project,
)
from .mcp_cmake_models import (
    BuildErrorInfo,
    CommandResult,
    CompileError,
    StructuredError,
    TestErrorInfo,
    TestFailure,
)

# The new server entry point is not exposed here by default
# to avoid circular dependencies if it were to import from here.
# It should be imported directly, e.g., `from mcp_cmake.mcp_cmake_server import main`

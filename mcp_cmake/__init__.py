
"""mcp_cmake - A CMake project management tool for MCP."""

__version__ = "0.1.0"

from .mcp_cmake_core import (
    ErrorAnalyzer,
    execute_command,
    execute_command_with_analysis,
    analyze_error_output,
    analyze_build_error_detailed,
    analyze_test_error_detailed,
    format_error_for_llm_analysis,
    extract_error_metadata,
    get_source_code_context,
    get_error_statistics,
    copy_analysis_to_clipboard,
    filter_errors_by_type,
    test_project,
    get_common_cmake_variables,
    parse_cmake_defines_string,
    list_presets,
    configure_project,
    build_project,
    build_project_single_target,
    health_check,
)

from .mcp_cmake_models import (
    StructuredError,
    CommandResult,
    CompileError,
    TestFailure,
    BuildErrorInfo,
    TestErrorInfo,
)

# The new server entry point is not exposed here by default
# to avoid circular dependencies if it were to import from here.
# It should be imported directly, e.g., `from mcp_cmake.mcp_cmake_server import main`

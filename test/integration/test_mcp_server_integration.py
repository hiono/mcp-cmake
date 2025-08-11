import json
import os
import subprocess
import sys
import time

import pytest

# MCPサーバーのパスと引数
MCP_SERVER_COMMAND = [
    "uv",
    "run",
    "python",
    "-m",
    "mcp_cmake.mcp_cmake_server",
    "--stdio",
    "-w",
    "/workspace/sample",
]


@pytest.fixture(scope="module")
def mcp_server_session():
    """MCPサーバープロセスを起動し、セッションを初期化するフィクスチャ"""
    stderr_log_path = "/tmp/mcp_server_stderr.log"
    with open(stderr_log_path, "w") as stderr_file:
        process = subprocess.Popen(
            MCP_SERVER_COMMAND,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            bufsize=1,
        )

        # サーバーが起動するのを待つ
        time.sleep(3)  # 起動直後の安定化のために短い待機を残す

        # --- ハンドシェイク ---
        # 1. initialize リクエスト
        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "Pytest Client", "version": "1.0"},
            },
        }
        process.stdin.write(json.dumps(initialize_request) + "\n")
        process.stdin.flush()
        response_line = process.stdout.readline()
        initialize_response = json.loads(response_line)
        assert initialize_response.get("id") == 1 and "result" in initialize_response

        # 2. notifications/initialized 通知
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        process.stdin.write(json.dumps(initialized_notification) + "\n")
        process.stdin.flush()
        # この通知に対する応答はないので、少し待つ
        time.sleep(0.5)

        yield process

    # --- クリーンアップ ---
    if process.poll() is None:
        process.stdin.close()
        process.terminate()
        process.wait(timeout=5)
        if process.poll() is None:
            process.kill()
    if os.path.exists(stderr_log_path):
        os.remove(stderr_log_path)


def send_request_and_get_response(process: subprocess.Popen, request: dict) -> dict:
    """プロセスにリクエストを送信し、応答を読み取って返すヘルパー関数"""
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    response_line = process.stdout.readline()
    # 空の応答やデバッグメッセージをスキップ
    while not response_line.strip():
        response_line = process.stdout.readline()
    return json.loads(response_line)


def test_tools_list_schema(mcp_server_session):
    """tools/listメソッドを呼び出し、スキーマを検証する"""
    process = mcp_server_session

    # `params`は完全に省略するのが正しい仕様
    tools_list_request = {"jsonrpc": "2.0", "id": 100, "method": "tools/list"}

    response = send_request_and_get_response(process, tools_list_request)

    assert response.get("id") == 100
    assert "result" in response
    assert "tools" in response["result"]

    tools = {tool["name"]: tool for tool in response["result"]["tools"]}
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
        tools["health_check"]["inputSchema"]["properties"]["working_dir"]["default"]
        == "sample"
    )


@pytest.mark.parametrize(
    "tool_name, arguments, expected_substring",
    [
        ("health_check", {}, "PoC_OK"),
        ("list_presets", {}, "PoC: preset1"),
        (
            "configure_project",
            {"preset": "test-preset"},
            "Configuring project test-preset",
        ),
        ("build_project", {"preset": "test-preset"}, "Building project test-preset"),
        (
            "test_project",
            {"preset": "test-preset", "test_filter": "some_test"},
            "with filter some_test",
        ),
        (
            "format_error_for_llm_analysis",
            {"error_output": "an error occurred"},
            "Analyzed error",
        ),
    ],
)
def test_tools_call_for_all_tools(
    mcp_server_session, tool_name, arguments, expected_substring
):
    """tools/callメソッドを呼び出し、各ツールの動作を検証する"""
    process = mcp_server_session
    request_id = hash(tool_name + str(arguments)) % 100000

    tools_call_request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }

    response = send_request_and_get_response(process, tools_call_request)

    assert response.get("id") == request_id
    result = response.get("result")
    assert result is not None

    # 戻り値の型によって結果の格納場所が異なるため、両方をチェックする
    result_str = ""
    if result.get("structuredContent") and isinstance(
        result["structuredContent"].get("result"), str
    ):
        result_str = result["structuredContent"]["result"]
    elif result.get("content") and result["content"][0].get("text"):
        # health_checkのように辞書を返すツールは、content[0].textにJSON文字列として格納される
        # ここでは単純な文字列チェックなので、JSONパースはせずに文字列として扱う
        result_str = result["content"][0]["text"]

    assert expected_substring in result_str

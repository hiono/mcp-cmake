# MCP-CMake

MCP-CMakeは、CMakeプロジェクトの管理を自動化・支援するためのModel Context Protocol (MCP) サーバーです。
AI Coder（大規模言語モデルベースの開発エージェント）がCMakeプロジェクトの状況確認、設定、ビルド、テスト、エラー分析を簡単かつ対話的に行えるように設計されています。

## 主な機能

- **デュアルモード動作**: stdio（標準入出力）とHTTPの両方の通信モードをサポートし、ローカルでの対話とネットワーク経由での利用の両方に対応します。
- **CMakeワークフローのフルサポート**: プリセットのリスト表示、設定(configure)、ビルド(build)、テスト(test)の一連のワークフローをツールとして提供します。
- **高度な実行オプション**: 複数ターゲットの指定、並列ビルド・テスト、詳細（verbose）出力など、柔軟なオプションに対応します。
- **インテリジェントなエラー分析**: ビルドやテストで発生したエラーを単なるテキストではなく、ファイルパス、行番号、エラーメッセージを含む構造化データとして解析し、LLMが理解しやすいサマリーを生成します。
- **環境チェック**: `cmake`や`ctest`の利用可能性など、実行環境の健全性をチェックする機能を提供します。

## インストール

`uv`などのPythonパッケージ管理ツールを使用してインストールします。

```bash
# このリポジトリをクローンした後
git clone https://github.com/your-username/mcp-cmake.git
cd mcp-cmake

# 編集可能モードでインストール
uv pip install -e .
```

## 使用方法

`mcp-cmake`は、インストール後に単一のコマンドとして実行できます。

### サーバーの起動

```bash
# stdioモードで起動（デフォルト）
mcp-cmake

# HTTPモードで起動
mcp-cmake --host 127.0.0.1 --port 8000

# ヘルプの表示
mcp-cmake --help
```

#### コマンドライン引数

- `--stdio`: stdioモードでサーバーを起動します。
- `--host <address>`: HTTPモードでリッスンするホストアドレスを指定します。（デフォルト: `127.0.0.1`）
- `--port <number>`: HTTPモードでリッスンするポートを指定します。（デフォルト: `8000`）
- `-w`, `--working-dir <path>`: CMakeプロジェクトのルートディレクトリを指定します。（デフォルト: `.`）

### 開発者向けダッシュボード

HTTPモードでサーバーを起動した場合、Webブラウザで `http://<host>:<port>/docs` にアクセスすると、APIドキュメント（Swagger UI）が表示されます。
このダッシュボードで、公開されているツールの一覧を確認したり、パラメータを入力してツールの動作をテストしたりできます。

## 公開ツール（API）一覧

以下は、MCPクライアントから利用可能な主要なツールです。

- `health_check(working_dir: str) -> dict`
- `list_presets(working_dir: str) -> str`
- `configure_project(preset: str, working_dir: str, cmake_defines: dict) -> str`
- `build_project(preset: str, targets: list, working_dir: str, verbose: bool, parallel_jobs: int) -> str`
- `test_project(preset: str, working_dir: str, verbose: bool, test_filter: str, parallel_jobs: int) -> str`
- `format_error_for_llm_analysis(error_output: str, error_type: str, command: str, working_dir: str) -> str`

## 開発

### 開発環境

```bash
# 依存関係の同期
uv sync
```

### テストの実行

```bash
# すべてのユニットテストを実行
uv run python -m pytest test/unit
```
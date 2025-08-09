# MCP-CMake

MCP-CMakeは、CMakeプロジェクトの管理を行うためのGradioベースのMCPサーバーです。このサーバーは、CMakeプロジェクトの設定、ビルド、テスト実行を統一されたインターフェースで簡単に実行できる包括的なツールを提供します。

## 機能

### 基本機能
- **CMakeプリセット一覧**: 利用可能なconfigure、build、testプリセットを表示
- **CMakeプロジェクトの設定**: CMakeプリセットを使用してプロジェクトを設定
- **ビルド実行**: 指定されたプリセットとターゲットでプロジェクトをビルド
- **テスト実行**: CTestを使用したテスト実行とレポート生成
- **リアルタイム出力**: コマンド実行結果をリアルタイムで表示
- **Web UI**: ブラウザベースのインターフェースで操作
- **MCP対応**: GradioのMCPサーバー機能を使用
- **柔軟なディレクトリ指定**: working_dirパラメータで任意のディレクトリを指定可能

### 高度な機能
- **CMake Define変数の動的追加**: ビルド時にCMake変数を動的に設定
- **複数ターゲット対応**: 一度に複数のビルドターゲットを指定可能
- **Verboseオプション**: 詳細なビルド・テスト出力の表示
- **並列実行**: 並列ビルド・テストジョブ数の指定
- **エラー解析エンジン**: ビルド・テストエラーの構造化解析
- **LLM支援機能**: エラー情報をLLMが解析しやすい形式で出力
- **健全性チェック**: システム環境とプロジェクト設定の検証

## インストール

```bash
# 依存関係のインストール
pip install -r requirements.txt

# または
pip install gradio[mcp]
```

## 使用方法

### サーバーの起動

```bash
python mcp_cmake.py
```

サーバー起動後、ブラウザで `http://localhost:7860` にアクセスしてWeb UIを使用できます。

### uvでの使用方法

```bash
# 依存関係のインストール
uv pip install -r requirements.txt

# サーバーの起動
uv run mcp_cmake.py
```

または

```bash
# プロジェクトとしてインストール
uv pip install -e .

# スクリプトとして実行
uv run mcp-cmake
```

### MCPクライアントからの使用

このサーバーはMCPプロトコルに対応しており、MCPクライアントから以下のツールを使用できます：

## API仕様

### list_presets

利用可能なCMakeプリセットを一覧表示します。

**パラメータ:**
- `working_dir` (オプション): CMakeLists.txtがあるディレクトリ（デフォルト: "sample"）

**戻り値:** configure、build、testプリセットの一覧

### configure_project

CMakeプロジェクトを設定します。

**パラメータ:**
- `preset` (必須): 使用するCMakeプリセット名
- `working_dir` (オプション): CMakeLists.txtがあるディレクトリ（デフォルト: "sample"）
- `cmake_defines` (オプション): CMake変数の辞書形式 `{"VAR": "VALUE"}`

**戻り値:** 設定処理の出力とエラー解析結果

### configure_project_with_defines

CMakeプロジェクトを設定します（UI用拡張版）。

**パラメータ:**
- `preset` (必須): 使用するCMakeプリセット名
- `working_dir` (オプション): CMakeLists.txtがあるディレクトリ（デフォルト: "sample"）
- `defines_string` (オプション): "KEY1=VALUE1;KEY2=VALUE2" 形式のDefine変数
- `verbose_makefile` (オプション): CMAKE_VERBOSE_MAKEFILEを有効にする
- `build_shared_libs` (オプション): BUILD_SHARED_LIBSを有効にする
- `find_root_path` (オプション): CMAKE_FIND_ROOT_PATHの設定

### build_project

CMakeプロジェクトをビルドします。

**パラメータ:**
- `preset` (必須): 使用するビルドプリセット名
- `targets` (オプション): ビルド対象のターゲット名のリスト
- `working_dir` (オプション): CMakeプロジェクトのルートディレクトリ（デフォルト: "sample"）
- `verbose` (オプション): Verboseビルドを有効にする
- `parallel_jobs` (オプション): 並列ビルドジョブ数

**戻り値:** ビルド処理の出力とエラー解析結果

### test_project

CTestを使用してテストを実行します。

**パラメータ:**
- `preset` (オプション): 使用するテストプリセット名（空の場合はデフォルト実行）
- `working_dir` (オプション): CMakeプロジェクトのルートディレクトリ（デフォルト: "sample"）
- `verbose` (オプション): Verboseテストを有効にする
- `test_filter` (オプション): テストフィルター（正規表現）
- `parallel_jobs` (オプション): 並列テストジョブ数

**戻り値:** テスト実行結果とエラー解析結果

### health_check

システム環境とプロジェクト設定の健全性をチェックします。

**パラメータ:**
- `working_dir` (オプション): チェック対象のディレクトリ（デフォルト: "sample"）

**戻り値:** システム状態の詳細レポート

## エラー解析API

### analyze_error_output

エラー出力を解析してLLM向けフォーマットで返します。

**パラメータ:**
- `error_output` (必須): 解析対象のエラー出力
- `error_type` (オプション): エラータイプ（"build", "test", "cmake"）

### format_error_for_llm_analysis

エラー出力をLLM解析用に包括的にフォーマットします。

**パラメータ:**
- `error_output` (必須): 解析対象のエラー出力
- `error_type` (オプション): エラータイプ
- `command` (オプション): 実行されたコマンド
- `working_dir` (オプション): 作業ディレクトリ

### extract_error_metadata

エラー出力からメタデータを抽出します。

**パラメータ:**
- `error_output` (必須): 解析対象のエラー出力

**戻り値:** ファイル名、行番号、エラータイプ等のメタデータ

### 使用例

#### 基本的な使用例

```python
# MCPクライアントからの呼び出し例
# 利用可能なプリセットを確認
presets = client.call_tool("list_presets", {
    "working_dir": "./my_project"
})

# プリセットを使用してプロジェクトを設定
client.call_tool("configure_project", {
    "preset": "msvc",
    "working_dir": "./my_project"
})

# ビルドを実行
client.call_tool("build_project", {
    "preset": "msvc",
    "targets": ["my_app", "tests"],
    "working_dir": "./my_project",
    "verbose": True
})

# テストを実行
client.call_tool("test_project", {
    "preset": "msvc",
    "working_dir": "./my_project",
    "verbose": True
})
```

#### 高度な使用例

```python
# CMake変数を指定してconfigure
client.call_tool("configure_project_with_defines", {
    "preset": "msvc",
    "working_dir": "./my_project",
    "defines_string": "CMAKE_BUILD_TYPE=Debug;ENABLE_TESTING=ON",
    "verbose_makefile": True,
    "build_shared_libs": False
})

# 複数ターゲットで並列ビルド
client.call_tool("build_project", {
    "preset": "msvc",
    "targets": ["app", "lib1", "lib2"],
    "working_dir": "./my_project",
    "verbose": True,
    "parallel_jobs": 4
})

# フィルター付きテスト実行
client.call_tool("test_project", {
    "preset": "msvc",
    "working_dir": "./my_project",
    "test_filter": "unit_test_*",
    "parallel_jobs": 2
})

# エラー解析
error_analysis = client.call_tool("analyze_error_output", {
    "error_output": build_error_log,
    "error_type": "build"
})
```

## Web UI機能

サーバー起動後、ブラウザで `http://localhost:7860` にアクセスすると以下のタブが利用できます：

### List Presets タブ
- 利用可能なCMakeプリセットの一覧表示
- configure、build、testプリセットを表示

### Configure API タブ
- CMakeプロジェクトの設定実行
- CMake Define変数の動的追加
- 一般的な変数（CMAKE_VERBOSE_MAKEFILE等）のチェックボックス
- カスタムDefine変数の文字列入力

### Build API タブ
- CMakeプロジェクトのビルド実行
- 複数ターゲットの選択（チェックボックス）
- カスタムターゲットの追加
- Verboseオプションと並列ジョブ数の指定

### Test API タブ
- CTestを使用したテスト実行
- テストプリセットの選択
- テストフィルター（正規表現）の指定
- Verboseオプションと並列実行の設定

### Error Analysis タブ
- ビルド・テストエラーの構造化解析
- LLM向けフォーマット出力
- エラー統計情報の表示
- エラータイプ別フィルタリング
- 分析結果のコピー機能

### Health Check タブ
- システム環境の健全性チェック
- CMake/CTestの存在確認
- CMakePresets.jsonの検証
- 問題発生時の解決方法提案

## SSEエラーについて

MCPクライアントから接続する際に「SSE error: Invalid content type, expected "text/event-stream"」が発生する場合は、以下の点を確認してください：

1. **サーバー起動方法**: `python mcp_cmake.py` で直接起動してください
2. **MCP設定**: MCPクライアントの設定で正しいエンドポイントを指定しているか確認
3. **Gradioバージョン**: `gradio[mcp]>=4.0` を使用していることを確認

## 新機能の詳細

### エラー解析エンジン

MCP-CMakeは高度なエラー解析エンジンを搭載しており、以下の機能を提供します：

- **構造化エラー解析**: コンパイルエラー、リンクエラー、テストエラーを構造化して解析
- **LLM向けフォーマット**: エラー情報をLLMが解析しやすい形式で出力
- **ソースコード文脈**: エラー発生箇所の周辺コードを自動取得
- **解決提案**: エラータイプに基づく解決方法の提案
- **統計情報**: エラー・警告の統計とサマリー

### CMake Define変数の動的設定

ビルド時にCMake変数を柔軟に設定できます：

- **Key-Valueペア入力**: `KEY=VALUE` 形式での変数設定
- **一般的な変数**: `CMAKE_VERBOSE_MAKEFILE`、`BUILD_SHARED_LIBS`等のチェックボックス
- **文字列形式**: `"VAR1=VALUE1;VAR2=VALUE2"` 形式での一括設定

### 複数ターゲット対応

ビルド時に複数のターゲットを同時に指定できます：

- **チェックボックス選択**: 事前定義されたターゲットから選択
- **カスタムターゲット**: 任意のターゲット名を追加入力
- **並列ビルド**: ジョブ数を指定した並列ビルド

### テスト機能

CTestを使用した包括的なテスト機能：

- **プリセット対応**: testプリセットを使用した実行
- **フィルタリング**: 正規表現によるテストフィルター
- **並列実行**: 複数テストの並列実行
- **詳細レポート**: テスト結果の構造化レポート

## プロジェクト構造

```
mcp-cmake/
├── mcp_cmake.py              # Gradio MCPサーバー（メイン）
├── mcp_client.py             # MCPクライアント（テスト用）
├── sample/                   # サンプルCMakeプロジェクト
│   ├── CMakeLists.txt
│   ├── CMakePresets.json
│   ├── main.cpp
│   └── build/               # ビルドディレクトリ
├── test_*.py                # 各種テストファイル
├── pyproject.toml           # プロジェクト設定
├── requirements.txt         # 依存関係
├── uv.lock                  # uvロックファイル
├── CONFIGURE_*.md           # 設定ドキュメント
├── TASK_*.md               # 実装タスクドキュメント
└── README.md               # このファイル
```

## MCP設定

### Kiro IDEでの設定

Kiro IDEでMCP-CMakeサーバーを使用する場合の設定例：

```json
{
  "mcpServers": {
    "cmake-server": {
      "command": "uv",
      "args": ["run", "python", "mcp_cmake.py"],
      "cwd": "/path/to/mcp-cmake",
      "env": {
        "PYTHONPATH": "/path/to/mcp-cmake"
      },
      "disabled": false,
      "autoApprove": [
        "list_presets",
        "health_check",
        "analyze_error_output"
      ]
    }
  }
}
```

### 他のMCPクライアントでの設定

一般的なMCPクライアントでの接続設定：

- **エンドポイント**: `http://127.0.0.1:7860/gradio_api/mcp/`
- **プロトコル**: HTTP/SSE
- **認証**: 不要（ローカル開発用）

## サンプルプロジェクト

`sample/`ディレクトリには、簡単なC++プロジェクトが含まれています：

- `main.cpp`: Hello Worldプログラム
- `CMakeLists.txt`: CMake設定ファイル
- `CMakePresets.json`: configure、build、testプリセット定義

### サンプルプロジェクトの拡張

より複雑なプロジェクトでテストする場合：

1. **テストの追加**: `CMakeLists.txt`にCTestの設定を追加
2. **複数ターゲット**: ライブラリとアプリケーションの分離
3. **依存関係**: 外部ライブラリの使用例

```cmake
# CMakeLists.txt の例
cmake_minimum_required(VERSION 3.20)
project(SampleProject)

# ライブラリターゲット
add_library(mylib src/lib.cpp)

# アプリケーションターゲット
add_executable(myapp src/main.cpp)
target_link_libraries(myapp mylib)

# テストの有効化
enable_testing()
add_executable(tests src/test.cpp)
target_link_libraries(tests mylib)
add_test(NAME unit_tests COMMAND tests)
```

## トラブルシューティング

### システム環境の問題

#### CMakeコマンドが見つからない場合

システムのPATHにCMakeが含まれていることを確認してください：

```bash
# Windows
where cmake

# macOS/Linux
which cmake
```

**Windows環境での注意事項:**
- 通常のPowerShellではCMakeが見つからない場合があります
- Visual Studio Build Toolsがインストールされている場合は、Developer Command Promptを使用してください：

```cmd
cmd.exe /k "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -startdir=none -arch=x64 -host_arch=x64
```

または、Visual Studio Developer PowerShellを使用：
```powershell
# Visual Studio Developer PowerShellを起動後
uv run python mcp_cmake.py
```

#### ワンライナーでの起動（推奨）
Visual Studio Build Toolsの環境設定とサーバー起動を一度に実行：
```cmd
cmd /c '"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -startdir=none -arch=x64 -host_arch=x64 && uv run python mcp_cmake.py'
```

### プロジェクト設定の問題

#### CMakePresets.jsonが見つからない場合

プロジェクトルートに`CMakePresets.json`ファイルが存在することを確認してください。基本的な例：

```json
{
  "version": 3,
  "configurePresets": [
    {
      "name": "default",
      "displayName": "Default Config",
      "description": "Default build using Ninja generator",
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/build/${presetName}",
      "cacheVariables": {
        "CMAKE_BUILD_TYPE": "Debug"
      }
    }
  ],
  "buildPresets": [
    {
      "name": "default",
      "configurePreset": "default"
    }
  ],
  "testPresets": [
    {
      "name": "default",
      "configurePreset": "default"
    }
  ]
}
```

### ビルドエラーの解決

#### Visual Studio C++例外処理エラー

Visual Studioを使用している場合、警告C4530が表示されることがあります。この場合、`CMakePresets.json`に`/EHsc`フラグを追加してください：

```json
{
  "configurePresets": [
    {
      "name": "msvc",
      "cacheVariables": {
        "CMAKE_CXX_FLAGS": "/EHsc"
      }
    }
  ]
}
```

#### リンクエラー

ライブラリが見つからない場合：
1. `CMAKE_PREFIX_PATH`を設定して依存関係の場所を指定
2. `find_package`の設定を確認
3. ライブラリのインストール状況を確認

### テスト実行の問題

#### CTestが見つからない場合

CTestはCMakeと一緒にインストールされます。CMakeが正しくインストールされていることを確認してください。

#### テストプリセットが見つからない場合

`CMakePresets.json`にtestプリセットが定義されていない場合、システムは自動的にデフォルトのctest実行にフォールバックします。

### エラー解析機能の問題

#### LLM向け出力が生成されない場合

1. エラー出力に`[ERROR]`マーカーが含まれていることを確認
2. エラー出力が空でないことを確認
3. エラータイプ（build/test/cmake）が正しく指定されていることを確認

### MCPクライアント接続の問題

#### SSEエラーについて

MCPクライアントから接続する際に「SSE error: Invalid content type, expected "text/event-stream"」が発生する場合：

1. **サーバー起動方法**: `python mcp_cmake.py` で直接起動してください
2. **MCP設定**: MCPクライアントの設定で正しいエンドポイントを指定しているか確認
3. **Gradioバージョン**: `gradio[mcp]>=4.0` を使用していることを確認

#### ポート競合エラー

ポート7860が既に使用されている場合：

```powershell
# ポート7860を使用しているプロセスを確認
netstat -ano | findstr :7860

# プロセスIDを確認してプロセスを終了
taskkill /PID <プロセスID> /F
```

### パフォーマンスの問題

#### 大きなプロジェクトでの遅延

1. 並列ビルド・テストジョブ数を調整
2. Verboseオプションを無効にして出力量を削減
3. 不要なターゲットを除外

#### メモリ使用量が多い場合

1. 大きなビルドログの出力制限を確認
2. エラー解析の対象を絞り込み
3. 複数の操作を同時実行しない

### 健全性チェックの活用

問題が発生した場合は、まず健全性チェック機能を使用してシステム状態を確認してください：

```python
# MCPクライアントから
health_status = client.call_tool("health_check", {
    "working_dir": "./my_project"
})
```

または、Web UIの「Health Check」タブを使用してください。

## ベストプラクティス

### プロジェクト構成

1. **CMakePresets.json の活用**
   - configure、build、testプリセットを適切に定義
   - 環境別（Debug/Release、コンパイラ別）のプリセット作成
   - 継承機能を使用した設定の共通化

2. **エラー解析の活用**
   - ビルドエラー発生時は即座にError Analysisタブを使用
   - LLM向け出力をコピーしてAIアシスタントに相談
   - エラー統計を確認して問題の傾向を把握

3. **テスト駆動開発**
   - テストプリセットを設定してCI/CDパイプラインと連携
   - 並列テスト実行でテスト時間を短縮
   - テストフィルターを使用して特定のテストグループを実行

### パフォーマンス最適化

1. **並列実行の活用**
   - ビルド・テストで適切な並列ジョブ数を設定
   - CPUコア数に応じた最適化

2. **出力制御**
   - 通常時はVerboseオプションを無効にして高速化
   - 問題発生時のみVerboseを有効にして詳細確認

3. **ターゲット選択**
   - 必要なターゲットのみをビルドして時間短縮
   - 開発中は変更のあるターゲットのみを対象に

### セキュリティ考慮事項

1. **作業ディレクトリの制限**
   - 信頼できるプロジェクトディレクトリのみを指定
   - システムディレクトリでの実行を避ける

2. **CMake変数の検証**
   - Define変数に機密情報を含めない
   - パス指定時は相対パスを使用

## 開発・貢献

### 開発環境のセットアップ

```bash
# リポジトリのクローン
git clone <repository-url>
cd mcp-cmake

# 依存関係のインストール
uv sync

# 開発モードでの実行
uv run python mcp_cmake.py
```

### テストの実行

```bash
# 全テストの実行
uv run python -m pytest

# 特定のテストファイル
uv run python test_mcp_client.py
```

### 機能追加・バグ修正

1. Issueを作成して問題・要望を報告
2. フィーチャーブランチを作成
3. テストを追加・更新
4. プルリクエストを作成

## ライセンス

このプロジェクトはオープンソースです。詳細はLICENSEファイルを参照してください。

## サポート・コミュニティ

- **Issues**: バグレポートや機能要望
- **Discussions**: 使用方法や質問
- **Wiki**: 詳細なドキュメントと使用例

## 更新履歴

### v2.0.0 (最新)
- テスト実行機能の追加
- エラー解析エンジンの実装
- CMake Define変数の動的設定
- 複数ターゲット対応
- LLM支援機能
- 健全性チェック機能
- UI の大幅な拡張

### v1.0.0
- 基本的なCMake操作（configure、build）
- プリセット一覧表示
- Gradio Web UI
- MCP対応

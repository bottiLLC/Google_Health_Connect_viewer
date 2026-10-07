# Google Health Connect Viewer

[![CI Status](https://img.shields.io/badge/CI-Passing-brightgreen?style=flat-square&logo=githubactions)](.github/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/Python-3.14%20%7C%203.13-blue?style=flat-square&logo=python)](pyproject.toml)
[![Code Style](https://img.shields.io/badge/Code%20Style-Ruff-black?style=flat-square&logo=ruff)](https://github.com/astral-sh/ruff)
[![Type Checker](https://img.shields.io/badge/Type%20Checker-Mypy%20Strict-blue?style=flat-square)](https://mypy-lang.org/)
[![Test Coverage](https://img.shields.io/badge/Coverage-100%25%20C1-brightgreen?style=flat-square&logo=pytest)](tests/)
[![Data Protection](https://img.shields.io/badge/Backup-Integrity%20Verified-success?style=flat-square)](backup_manager.py)

Android の **Google ヘルスコネクト (Google Health Connect)** からエクスポートされた SQLite データベース（`./data/health_connect_export.db`）を参照し、保存可能な全 77 テーブルおよび 8 大ドメイン情報をインタラクティブに可視化・分析・探索するための本番グレード Streamlit ダッシュボードです。

---

## 🌟 主な機能と特徴

1. **Google Health Connect 8大ドメイン・全77テーブルの完全網羅**:
   - **🏃 アクティビティ (Activity - 26テーブル)**: 歩数・歩行ケイデンス、移動距離、移動速度、アクティブ消費カロリー、ワークアウトセッション詳細、GPS 運動ルートマップ（PyDeck 3D描画）。
   - **⚖️ 身体測定 (Body Measurements - 7テーブル)**: 体重、体脂肪率、BMI、基礎代謝量 (BMR) の長期推移、オムロン体重体組成計 (KRD-703T) 等の測定機器別分析。
   - **😴 睡眠 (Sleep - 2テーブル)**: 日毎の合計睡眠時間推移折れ線グラフ（推奨睡眠7〜8h基準バンド付き）を最上部に配置し、下部に睡眠セッション一覧と睡眠ステージ（覚醒 / 浅い睡眠 / 深い睡眠 / レム睡眠）のタイムライン帯グラフ可視化。
   - **❤️ バイタル (Vitals - 13テーブル)**: 6 万件超の心拍数時系列データ（平均・最小・最大バンド）、血中酸素濃度 (SpO2) 測定分布および低下イベント（< 95%）の自動検知。
   - **🍎 栄養・水分・ライフスタイル (6テーブル)**: 栄養素、水分摂取、マインドフルネス、嗜好品等の全スキーマカタログ。
   - **🩺 医療データ & 月経周期 (9テーブル)**: FHIR 医療リソースおよび月経周期・排卵管理の完全スキーマ定義。
   - **📱 アプリ・デバイス & 監査ログ (14テーブル)**: 連携アプリ (Google Fit, Mi Fitness, OMRON connect, chocoZAP 等)、登録デバイス、読取アクセス監査ログ (344件)。
   - **🔍 全 77 テーブル探索カタログ**: 全テーブルのスキーマ定義、動的ページネーションプレビュー、CSV / JSON ワンクリックエクスポート。

2. **⚙️ 表示カスタマイズ設定画面とサイドバー切替**:
   - サイドバーからメインダッシュボードと「⚙️ 設定画面」をスムーズに切替可能。
   - サイドバー上のクイックマルチセレクトおよび設定画面より、全 9 タブの表示・非表示を任意に制御。
   - エグゼクティブ・サマリーに表示するメトリクス（歩数、カロリー、体重、睡眠）やグラフ項目の選択・絞り込み。
   - ユーザー設定は `./data/dashboard_settings.json` に安全に隔離・永続化され、アプリ再起動後も状態を完全復元。

3. **原本データベース保護と高密度パフォーマンス**:
   - SQLite 接続を常に **URI 読み取り専用モード (`file:...mode=ro`)** でオープンし、元 DB の破壊・破損・ロックを物理的に遮断。
   - 42 万件超の生データをメモリへ一括ロードせず、SQLite 側でダウンサンプリングする **SQL プッシュダウン集計** を徹底。
   - `@st.cache_data`（ファイル mtime 連動）による高速クエリキャッシュ。

4. **厳格なデータ保護と整合性検証付きバックアップ**:
   - `@[user_global]` および `Python-backup-script` スキルに 100% 準拠。
   - `./data` ディレクトリの自動 ZIP アーカイブ生成と `testzip()` による破損検知をサイドバーからワンクリック実行可能。

---

## 🚀 クイックスタート

### 動作環境
- **OS**: Windows, macOS, Linux
- **Python**: Python 3.14 (推奨) または 3.13

### 1. ワンクリック起動（推奨）
Python のみがインストールされた環境でも、起動スクリプトが自動的に `uv` パッケージマネージャーをセットアップし、仮想環境の構築から依存同期、アプリ起動までを完全自動で実行します。

- **Windows**: `run.bat` をダブルクリック
- **macOS / Linux**: ターミナルで `./run.command` を実行

### 2. 手動起動 (uv CLI)
```bash
# 依存関係の同期
uv sync

# Streamlit アプリケーションの起動
uv run streamlit run app.py
```

ブラウザで `http://localhost:8501` に自動アクセスされます。

---

## 🏗️ システムアーキテクチャ

単一責任の原則（SRP）に従い、関心事を明確に分離した高凝集・疎結合設計を採用しています：

```text
Google_Health_Connect_viewer/
├── app.py                  # Streamlit エントリーポイント・タブ編成
├── ui_components.py        # 共通チャート・テーブル・バックアップUIウィジェット
├── analytics_service.py    # SQLプッシュダウン集計・時系列処理・統計エンジン
├── db_engine.py            # SQLite 読み取り専用(mode=ro)接続＆全77テーブル走査
├── domain_models.py        # Pydantic v2 型安全スキーマ・値オブジェクト
├── backup_manager.py       # ./data 隔離保護・整合性検証付きZIPバックアップ
├── data/
│   ├── health_connect_export.db  # Googleヘルスコネクト SQLite DB
│   └── backup_config.json        # バックアップ保存先設定
├── tests/                  # 包括的テストスイート (100% C1カバレッジ)
├── pyproject.toml          # プロジェクト・依存関係・ツール設定
├── run.bat                 # Windows用ランチャー (CRLF)
└── run.command             # Mac/Linux用ランチャー (LF)
```

---

## 🧪 品質検証・CI テスト実行

本プロジェクトは `mypy --strict` による完全型安全、`ruff` による厳格なリント、`pytest` による C1 ブランチカバレッジ検証を標準装備しています。

```bash
# コードフォーマット検証
uv run ruff format --check .

# 静的解析・リンター検証
uv run ruff check .

# 厳格静的型チェック
uv run mypy .

# ブランチカバレッジ付き単体テスト実行
uv run pytest -v --cov=. --cov-branch --cov-report=term-missing
```

---

## 📄 ライセンス
MIT License

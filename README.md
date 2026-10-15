# Google Health Connect Viewer

![CI](https://img.shields.io/badge/CI-passed-green) ![Python](https://img.shields.io/badge/Python-3.14-blue.svg) ![Streamlit](https://img.shields.io/badge/Streamlit-1.42.0-FF4B4B.svg) ![License](https://img.shields.io/badge/License-Private-red.svg)

## Overview
Android の Google ヘルスコネクト (Google Health Connect) からエクスポートされた SQLite データベース（`./data/health_connect_export.db`）を参照し、全 77 テーブルおよび 8 大ドメイン情報の可視化・分析・探索と Google Drive クラウド差分マージを提供する本番運用ダッシュボードです。

## Quick Start (TL;DR)
```bash
# 1. 依存関係の同期
uv sync

# 2. (任意) Google Cloud OAuth 認証情報の配置
# Google Cloud Console より取得したクライアント秘密鍵 JSON を ./data/credentials.json として配置

# 3. ダッシュボードの起動 (ブラウザで http://localhost:8501 が自動オープン)
uv run streamlit run app.py
```

## Architecture & Features
- **全 77 テーブル完全走査 & 8 大ドメイン分析**: 42 万件超のヘルスコネクト生データを URI 読取専用モード (`mode=ro`) かつ SQL プッシュダウン集計で高速処理し、アクティビティ、睡眠ステージ、バイタル時系列、身体測定、GPS 3D ルートマップなどをインタラクティブ可視化。
- **Google Drive クラウド同期 & 堅牢差分マージ**: Google Drive 上の最新 SQLite バックアップを自動検知して安全にダウンロードし、`PRAGMA table_xinfo` による計算生成列（Generated Columns）の除外および `EXCEPT` 集合差分クエリにより、主キー欠如テーブルを含む全スキーマの重複増殖を完全排除したアトミックマージを実行。
- **データ分離 & プレマージ自動バックアップ**: すべての動的永続データ・設定・DB を `./data/` 配下に厳格隔離し、マージ実行直前に `backup_manager.run_backup()` による完全性検証付き ZIP 退避を強制先行実行するフェイルセーフ設計。
- **表示カスタマイズ & 状態永続化**: メイン画面と設定画面をシームレスに切替可能。タブの表示制御プリセットやサマリー項目の絞り込み状態を `./data/dashboard_settings.json` へ自動永続化。
- **高カバレッジ品質保証**: `mypy --strict` 完全型検査、`ruff` リント/フォーマット、および全 72 件のユニット/UI/差分マージテストによる高水準 C1 ブランチ網羅率（91.4%）を標準維持。

## Environment Variables & Configuration
| 設定項目 / 環境変数 | 規定値 / 保存先 | 概要 |
| :--- | :--- | :--- |
| `drive_folder_id` | `""` (`./data/dashboard_settings.json`) | Google ヘルスコネクトの SQLite バックアップが格納されている Google Drive フォルダ ID |
| `BACKUP_DIR` | `./backups` (`./data/backup_config.json`) | ローカル ZIP バックアップの出力先ディレクトリパス |
| `credentials.json` | `./data/credentials.json` | Google Cloud Console (Desktop App) より取得した OAuth 2.0 クライアント認証情報 |
| `token.json` | `./data/token.json` | 初回ブラウザ認証完了時に自動生成・更新される Google Drive API アクセストークン |
| `dashboard_settings.json` | `./data/dashboard_settings.json` | タブ表示制御、エグゼクティブサマリー項目、Drive フォルダ ID 等のユーザー永続設定 |

## Limits & Known Trade-offs
- **初回 OAuth 認証時のブラウザ待機**: 初回同期時はローカルサーバー経由でブラウザが起動し承認操作を待機（タイムアウト: 120 秒）するため、SSH ポートフォワード等のヘッドレス環境ではあらかじめローカルでトークンを生成しておく必要があります。
- **SQLite ロック競合**: 差分マージ中は排他書込ロック（`BEGIN IMMEDIATE`）を取得するため、ダッシュボード側の並行クエリは短時間待機となります（完了時に `st.cache_data.clear()` で自動リフレッシュ）。
- **今後の拡張課題**: 定期タイマーによる完全バックグラウンド自動同期、および差分マージ履歴の詳細監査ログビューワーの実装。

---

Copyright (c) LLC Bocchi. All rights reserved.

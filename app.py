"""Google Health Connect Full Viewer - Streamlit Dashboard Entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure deterministic root path resolution regardless of launcher execution context
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from analytics_service import HealthConnectAnalyticsService
from db_engine import DatabaseConnectionError, HealthConnectDbEngine
from domain_models import (
    DEFAULT_VISIBLE_TABS,
    SUMMARY_ITEMS_LABEL_MAP,
    DashboardFilterParams,
    DashboardSettings,
    HealthDomainCategory,
    SummaryItemKey,
    TableCatalogMeta,
)
from settings_manager import (
    load_dashboard_settings,
    reset_dashboard_settings,
    save_dashboard_settings,
)
from ui_components import (
    build_activity_composite_chart,
    build_body_measurement_chart,
    build_calories_chart,
    build_daily_sleep_trend_chart,
    build_heart_rate_chart,
    build_oxygen_saturation_chart,
    build_sleep_stages_chart,
    render_backup_sidebar,
    render_paginated_table,
    render_route_map,
    render_schema_table,
)

# Page configuration
st.set_page_config(
    page_title="Google Health Connect Viewer",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner=False)
def _get_database_engine(db_path_str: str, file_mtime: float) -> HealthConnectDbEngine:
    """Instantiate and cache database engine bound to file path and mtime."""
    _ = file_mtime
    return HealthConnectDbEngine(db_path_str)


@st.cache_data(show_spinner=False)
def _get_catalog_cached(db_path_str: str, file_mtime: float) -> list[TableCatalogMeta]:
    """Cache all 77 table catalog metadata."""
    _ = file_mtime
    engine = HealthConnectDbEngine(db_path_str)
    return engine.get_all_tables_catalog()


def main() -> None:
    """Application layout and orchestration entrypoint."""
    st.title("🩺 Google Health Connect 全情報統合ダッシュボード")
    st.caption("Google ヘルスコネクトの SQLite エクスポートデータを全テーブル完全走査・可視化")

    # 1. Resolve database path
    db_file = _ROOT / "data" / "health_connect_export.db"
    if not db_file.exists():
        st.error(
            f"❌ データベースファイルが見つかりません: {db_file}\n./data/ に配置されているか確認してください。"
        )
        render_backup_sidebar()
        return

    mtime = db_file.stat().st_mtime
    try:
        engine = _get_database_engine(str(db_file), mtime)
        analytics = HealthConnectAnalyticsService(engine)
    except DatabaseConnectionError as e:
        st.error(f"❌ データベース接続エラー: {e}")
        render_backup_sidebar()
        return

    # Load settings from persistent storage / session state
    if "dashboard_settings" not in st.session_state:
        st.session_state["dashboard_settings"] = load_dashboard_settings()
    settings: DashboardSettings = st.session_state["dashboard_settings"]

    # 2. Sidebar configuration, mode selection, and filters
    with st.sidebar:
        st.header("🧭 画面切替 & 表示設定")
        view_mode = st.radio(
            "表示画面を選択",
            options=["📊 ダッシュボード", "⚙️ 設定画面"],
            index=0,
            key="app_view_mode",
        )

        with st.expander("📑 表示タブ クイック切替", expanded=False):
            sidebar_selected_tabs = st.multiselect(
                "表示するタブ",
                options=list(DEFAULT_VISIBLE_TABS),
                default=[t for t in settings.visible_tabs if t in DEFAULT_VISIBLE_TABS],
                key="sidebar_tabs_multiselect",
            )
            if sidebar_selected_tabs != settings.visible_tabs:
                new_settings = DashboardSettings(
                    visible_tabs=sidebar_selected_tabs,
                    visible_summary_items=settings.visible_summary_items,
                )
                save_dashboard_settings(new_settings)
                st.session_state["dashboard_settings"] = new_settings
                st.rerun()

        st.divider()
        st.header("⚙️ データベース概要 & フィルタ")
        db_size_mb = db_file.stat().st_size / (1024 * 1024)
        st.info(f"📂 **DBファイル**: `{db_file.name}` ({db_size_mb:.1f} MB)")

        earliest_d, latest_d = analytics.get_database_date_range()
        selected_start_d, selected_end_d = None, None

        if earliest_d and latest_d:
            st.subheader("📅 集計対象期間")
            date_range = st.date_input(
                "日付範囲を選択",
                value=(earliest_d, latest_d),
                min_value=earliest_d,
                max_value=latest_d,
            )
            if isinstance(date_range, (tuple, list)):
                if len(date_range) == 2:
                    selected_start_d, selected_end_d = date_range[0], date_range[1]
                elif len(date_range) == 1:
                    selected_start_d = date_range[0]

        # Applications & Devices filter
        apps = analytics.get_apps_list()
        devices = analytics.get_devices_list()

        st.subheader("📱 連携アプリ & 記録元")
        app_names = {a.row_id: a.app_name or a.package_name for a in apps}
        selected_apps = st.multiselect(
            "アプリ絞り込み",
            options=list(app_names.keys()),
            format_func=lambda aid: app_names.get(aid, str(aid)),
            default=[],
        )

        filter_params = DashboardFilterParams(
            start_date=selected_start_d,
            end_date=selected_end_d,
            selected_app_ids=selected_apps,
            selected_device_ids=[],
        )

    # 3. Settings Screen Routing
    if view_mode == "⚙️ 設定画面":
        st.header("⚙️ ダッシュボード表示設定")
        st.caption("タブの表示/非表示およびサマリー画面の表示項目をカスタマイズして永続化します。")

        st.subheader("1. タブ単位の表示・非表示")
        selected_tabs = st.multiselect(
            "ダッシュボードに表示するタブを選択してください",
            options=list(DEFAULT_VISIBLE_TABS),
            default=[t for t in settings.visible_tabs if t in DEFAULT_VISIBLE_TABS],
            key="settings_tabs_multiselect",
        )

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("全タブを表示", use_container_width=True):
                new_settings = DashboardSettings(
                    visible_tabs=list(DEFAULT_VISIBLE_TABS),
                    visible_summary_items=settings.visible_summary_items,
                )
                save_dashboard_settings(new_settings)
                st.session_state["dashboard_settings"] = new_settings
                st.rerun()
        with col_btn2:
            if st.button("最小構成 (サマリー・睡眠・バイタル)", use_container_width=True):
                new_settings = DashboardSettings(
                    visible_tabs=["📊 サマリー", "😴 睡眠", "❤️ バイタル"],
                    visible_summary_items=settings.visible_summary_items,
                )
                save_dashboard_settings(new_settings)
                st.session_state["dashboard_settings"] = new_settings
                st.rerun()

        st.divider()
        st.subheader("2. サマリー画面の表示項目")
        st.write("エグゼクティブ・サマリータブに表示する項目を選択してください。")

        summary_options = [k.value for k in SummaryItemKey]
        selected_summary_keys = st.multiselect(
            "サマリー表示項目",
            options=summary_options,
            format_func=lambda k: SUMMARY_ITEMS_LABEL_MAP.get(SummaryItemKey(k), k),
            default=[k for k in settings.visible_summary_items if k in summary_options],
            key="settings_summary_items_multiselect",
        )

        st.divider()
        col_save, col_reset = st.columns(2)
        with col_save:
            if st.button("💾 設定を保存して適用", use_container_width=True, type="primary"):
                saved_settings = DashboardSettings(
                    visible_tabs=selected_tabs,
                    visible_summary_items=selected_summary_keys,
                )
                if save_dashboard_settings(saved_settings):
                    st.session_state["dashboard_settings"] = saved_settings
                    st.success("✅ 設定を保存しました。(./data/dashboard_settings.json)")
                    st.rerun()
                else:
                    st.error("❌ 設定の保存に失敗しました。")
        with col_reset:
            if st.button("🔄 初期設定に戻す", use_container_width=True):
                default_settings = reset_dashboard_settings()
                st.session_state["dashboard_settings"] = default_settings
                st.success("✅ 設定を初期値にリセットしました。")
                st.rerun()

        render_backup_sidebar()
        return

    # 4. Main dashboard tab routing
    active_tabs = [t for t in DEFAULT_VISIBLE_TABS if t in settings.visible_tabs]
    if not active_tabs:
        st.warning(
            "⚠️ 表示対象のタブが1つも選択されていません。\n"
            "サイドバーの「表示タブ クイック切替」または「⚙️ 設定画面」からタブを有効化してください。"
        )
        render_backup_sidebar()
        return

    tabs = st.tabs(active_tabs)
    tab_map = dict(zip(active_tabs, tabs, strict=True))

    # ==========================================
    # Tab 1: サマリー
    # ==========================================
    if "📊 サマリー" in tab_map:
        with tab_map["📊 サマリー"]:
            st.subheader("📊 エグゼクティブ・サマリー")
            daily_acts = analytics.get_daily_activity_summary(filter_params)
            df_body = analytics.get_body_measurements_df(filter_params)
            sleep_sess = analytics.get_sleep_sessions(filter_params)
            df_hr = analytics.get_heart_rate_summary_df(filter_params)
            df_o2 = analytics.get_oxygen_saturation_df(filter_params)

            visible_summary = set(settings.visible_summary_items)
            metric_items: list[tuple[str, str, str | None]] = []

            latest_steps = daily_acts[-1].step_count if daily_acts else 0
            latest_dist = daily_acts[-1].distance_km if daily_acts else 0.0
            latest_cal = daily_acts[-1].total_calories_kcal if daily_acts else 0.0
            latest_weight = (
                df_body["weight_kg"].iloc[-1]
                if not df_body.empty and "weight_kg" in df_body.columns
                else None
            )
            sleep_min = sleep_sess[0].total_duration_minutes if sleep_sess else 0

            if SummaryItemKey.METRIC_STEPS.value in visible_summary:
                metric_items.append(("最新日歩数", f"{latest_steps:,} 歩", f"{latest_dist:.2f} km"))
            if SummaryItemKey.METRIC_CALORIES.value in visible_summary:
                metric_items.append(("総消費カロリー", f"{latest_cal:,.0f} kcal", None))
            if SummaryItemKey.METRIC_WEIGHT.value in visible_summary:
                w_str = f"{latest_weight:.1f} kg" if latest_weight else "-"
                metric_items.append(("最新体重", w_str, None))
            if SummaryItemKey.METRIC_SLEEP.value in visible_summary:
                metric_items.append(
                    ("直近睡眠時間", f"{int(sleep_min // 60)}時間 {int(sleep_min % 60)}分", None)
                )

            if metric_items:
                cols = st.columns(len(metric_items))
                for col, (label, val, delta) in zip(cols, metric_items, strict=True):
                    with col:
                        st.metric(label, val, delta=delta)

            if SummaryItemKey.CHART_ACTIVITY.value in visible_summary:
                st.plotly_chart(
                    build_activity_composite_chart(daily_acts),
                    use_container_width=True,
                    key="overview_activity_composite_chart",
                )

            if not metric_items and SummaryItemKey.CHART_ACTIVITY.value not in visible_summary:
                st.info(
                    "ℹ️ サマリーの表示項目がすべて無効化されています。設定画面から項目を有効化してください。"
                )

    # ==========================================
    # Tab 2: アクティビティ
    # ==========================================
    if "🏃 アクティビティ" in tab_map:
        with tab_map["🏃 アクティビティ"]:
            st.subheader("🏃 アクティビティ・運動セッション")
            daily_acts = analytics.get_daily_activity_summary(filter_params)
            st.plotly_chart(
                build_activity_composite_chart(daily_acts),
                use_container_width=True,
                key="activity_composite_chart",
            )
            st.plotly_chart(
                build_calories_chart(daily_acts),
                use_container_width=True,
                key="activity_calories_chart",
            )

            st.divider()
            st.subheader("🗺️ ワークアウトセッション & GPS ルート")
            sessions = analytics.get_exercise_sessions(filter_params)
            if not sessions:
                st.info("対象期間内に記録された運動セッションはありません。")
            else:
                col_s1, col_s2 = st.columns([1, 1])
                with col_s1:
                    sess_opts = {
                        s.row_id: f"{s.start_time.strftime('%Y-%m-%d %H:%M')} - {s.exercise_type_name} ({s.duration_minutes}分)"
                        for s in sessions
                    }
                    selected_sess_id = st.selectbox(
                        "運動セッションを選択",
                        options=list(sess_opts.keys()),
                        format_func=lambda sid: sess_opts[sid],
                    )
                    selected_session = next(s for s in sessions if s.row_id == selected_sess_id)
                    st.write(f"**ワークアウト種別**: `{selected_session.exercise_type_name}`")
                    st.write(f"**運動時間**: {selected_session.duration_minutes} 分")
                    st.write(
                        f"**GPSルート保持**: {'あり (可視化可能)' if selected_session.has_route else 'なし'}"
                    )

                with col_s2:
                    if selected_session.has_route:
                        route_pts = analytics.get_exercise_route_points(selected_session.row_id)
                        st.caption(f"GPS 追跡ポイント数: {len(route_pts):,} 点")
                        render_route_map(route_pts)
                    else:
                        st.info("このセッションには GPS 座標は記録されていません。")

    # ==========================================
    # Tab 3: 身体測定
    # ==========================================
    if "⚖️ 身体測定" in tab_map:
        with tab_map["⚖️ 身体測定"]:
            st.subheader("⚖️ 身体測定 & 体組成推移")
            df_body = analytics.get_body_measurements_df(filter_params)
            if df_body.empty:
                st.info("対象期間内の身体測定データ（体重・体脂肪率）はありません。")
            else:
                st.plotly_chart(
                    build_body_measurement_chart(df_body),
                    use_container_width=True,
                    key="body_measurement_chart",
                )
                st.subheader("測定レコード一覧")
                disp_df = df_body.copy()
                if "datetime" in disp_df.columns:
                    disp_df["datetime"] = disp_df["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
                render_paginated_table(disp_df, "body_measurements", "tab_body")

    # ==========================================
    # Tab 4: 睡眠
    # ==========================================
    if "😴 睡眠" in tab_map:
        with tab_map["😴 睡眠"]:
            st.subheader("📈 日毎の睡眠時間推移")
            daily_sleep = analytics.get_daily_sleep_summary(filter_params)
            st.plotly_chart(
                build_daily_sleep_trend_chart(daily_sleep),
                use_container_width=True,
                key="daily_sleep_trend_chart",
            )

            st.divider()
            st.subheader("😴 睡眠セッション & ステージ分析")
            sleep_sessions = analytics.get_sleep_sessions(filter_params)
            if not sleep_sessions:
                st.info("対象期間内に記録された睡眠セッションはありません。")
            else:
                s_map = {
                    s.row_id: f"{s.start_time.strftime('%Y-%m-%d %H:%M')} ~ {s.end_time.strftime('%H:%M')} (総 {int(s.total_duration_minutes // 60)}時間 {int(s.total_duration_minutes % 60)}分)"
                    for s in sleep_sessions
                }
                s_id = st.selectbox(
                    "睡眠日を選択", options=list(s_map.keys()), format_func=lambda sid: s_map[sid]
                )
                cur_sleep = next(s for s in sleep_sessions if s.row_id == s_id)

                st.plotly_chart(
                    build_sleep_stages_chart(cur_sleep.stages),
                    use_container_width=True,
                    key="sleep_stages_chart",
                )

                stage_summary = [
                    {
                        "ステージ": stg.stage_name,
                        "開始": stg.start_time.strftime("%H:%M:%S"),
                        "終了": stg.end_time.strftime("%H:%M:%S"),
                        "継続時間(分)": stg.duration_minutes,
                    }
                    for stg in cur_sleep.stages
                ]
                st.dataframe(pd.DataFrame(stage_summary), use_container_width=True, hide_index=True)

    # ==========================================
    # Tab 5: バイタル
    # ==========================================
    if "❤️ バイタル" in tab_map:
        with tab_map["❤️ バイタル"]:
            st.subheader("❤️ 心拍数 & 血中酸素濃度 (SpO2)")
            df_hr = analytics.get_heart_rate_summary_df(filter_params)
            df_o2 = analytics.get_oxygen_saturation_df(filter_params)

            col_v1, col_v2 = st.columns(2)
            with col_v1:
                st.plotly_chart(
                    build_heart_rate_chart(df_hr),
                    use_container_width=True,
                    key="heart_rate_chart",
                )
            with col_v2:
                st.plotly_chart(
                    build_oxygen_saturation_chart(df_o2),
                    use_container_width=True,
                    key="oxygen_saturation_chart",
                )

            if not df_o2.empty and "is_low_event" in df_o2.columns:
                low_events = df_o2[df_o2["is_low_event"].astype(bool)].copy()
                if not low_events.empty:
                    st.warning(f"⚠️ SpO2 低下イベント (< 95%): {len(low_events)} 件検出")
                    if "datetime" in low_events.columns:
                        low_events["datetime"] = low_events["datetime"].dt.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    st.dataframe(
                        low_events[["datetime", "percentage"]],
                        use_container_width=True,
                        hide_index=True,
                    )

    # ==========================================
    # Tab 6: 栄養・生活
    # ==========================================
    if "🍎 栄養・生活" in tab_map:
        with tab_map["🍎 栄養・生活"]:
            st.subheader("🍎 栄養素・水分・ライフスタイル（対応スキーマ）")
            st.markdown(
                "Google Health Connect で定義されている栄養・水分・マインドフルネス・嗜好品等のテーブルスキーマです。\n"
                "※ 本エクスポート DB ではレコード 0 件ですが、いつでも取り込み・受入可能な状態となっています。"
            )
            catalog_items = _get_catalog_cached(str(db_file), mtime)
            nutrition_tables = [
                c for c in catalog_items if c.category == HealthDomainCategory.NUTRITION_WELLNESS
            ]
            for tbl in nutrition_tables:
                with st.expander(f"📋 {tbl.table_name} (保持行数: {tbl.row_count} 行)"):
                    render_schema_table(tbl.columns)

    # ==========================================
    # Tab 7: 医療・月経
    # ==========================================
    if "🩺 医療・月経" in tab_map:
        with tab_map["🩺 医療・月経"]:
            st.subheader("🩺 医療データ (FHIR) & 月経周期（対応スキーマ）")
            st.markdown("FHIR 医療リソースおよび月経周期・排卵管理の完全スキーマカタログです。")
            catalog_items = _get_catalog_cached(str(db_file), mtime)
            med_tables = [
                c
                for c in catalog_items
                if c.category
                in (HealthDomainCategory.MEDICAL_RECORDS, HealthDomainCategory.CYCLE_TRACKING)
            ]
            for tbl in med_tables:
                with st.expander(
                    f"📋 {tbl.table_name} ({tbl.category} / 保持行数: {tbl.row_count} 行)"
                ):
                    render_schema_table(tbl.columns)

    # ==========================================
    # Tab 8: デバイス・監査
    # ==========================================
    if "📱 デバイス・監査" in tab_map:
        with tab_map["📱 デバイス・監査"]:
            st.subheader("📱 連携アプリ・登録デバイス & 読取監査ログ")
            col_dev1, col_dev2 = st.columns(2)
            with col_dev1:
                st.markdown("#### 登録アプリケーション")
                st.dataframe(
                    pd.DataFrame([a.model_dump() for a in apps]),
                    use_container_width=True,
                    hide_index=True,
                )
            with col_dev2:
                st.markdown("#### 登録デバイス")
                st.dataframe(
                    pd.DataFrame([d.model_dump() for d in devices]),
                    use_container_width=True,
                    hide_index=True,
                )

            st.divider()
            st.markdown("#### 読取アクセス監査ログ (最新500件)")
            audit_logs = analytics.get_read_access_audit_logs(limit=500)
            if audit_logs:
                df_logs = pd.DataFrame([log.model_dump() for log in audit_logs])
                df_logs["read_time"] = df_logs["read_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
                render_paginated_table(df_logs, "read_access_logs", "tab_audit")
            else:
                st.info("監査ログはありません。")

    # ==========================================
    # Tab 9: 全77テーブル探索
    # ==========================================
    if "🔍 全77テーブル探索" in tab_map:
        with tab_map["🔍 全77テーブル探索"]:
            st.subheader("🔍 全 77 テーブル探索カタログ & データプレビュー")
            catalog_items = _get_catalog_cached(str(db_file), mtime)
            df_catalog = pd.DataFrame(
                [
                    {
                        "テーブル名": c.table_name,
                        "カテゴリ": c.category,
                        "レコード数": c.row_count,
                        "カラム数": len(c.columns),
                        "データ保持": "あり" if c.has_data else "なし (空)",
                    }
                    for c in catalog_items
                ]
            )
            st.dataframe(df_catalog, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("動的テーブルプレビュー & カラムスキーマ")
            tbl_names = [c.table_name for c in catalog_items]
            selected_tbl = st.selectbox("表示するテーブルを選択", options=tbl_names)

            target_cat = next(c for c in catalog_items if c.table_name == selected_tbl)

            with st.expander("📌 カラム定義スキーマ", expanded=False):
                render_schema_table(target_cat.columns)

            limit_rows = st.select_slider("取得最大行数", options=[50, 100, 500, 1000], value=100)
            df_raw = engine.fetch_table_rows(selected_tbl, limit=limit_rows)
            render_paginated_table(df_raw, selected_tbl, "tab_explorer")

    # 4. Standard backup sidebar integration
    render_backup_sidebar()


if __name__ == "__main__":
    main()

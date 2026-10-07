"""Reusable UI components, chart builders, and widgets for Streamlit."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from backup_manager import get_backup_dir, run_backup, set_backup_dir
from domain_models import (
    ColumnMeta,
    DailyActivitySummary,
    DailySleepSummary,
    GpsRoutePoint,
    SleepStageInterval,
)


def render_backup_sidebar() -> None:
    """Render standardized Japanese backup management widget in Streamlit sidebar."""
    with st.sidebar:
        st.divider()
        st.subheader("データ保護・バックアップ")

        current_dir = str(get_backup_dir())
        new_dir = st.text_input("保存先フォルダ", value=current_dir)
        if new_dir != current_dir and st.button("保存先パスを更新", use_container_width=True):
            save_res = set_backup_dir(new_dir)
            if save_res["success"]:
                st.success(str(save_res["message"]))
                st.rerun()
            else:
                st.error(str(save_res["message"]))

        if st.button("今すぐバックアップを実行", use_container_width=True):
            with st.spinner("圧縮・整合性検証中..."):
                res = run_backup(app_name="health_viewer")
            if res["success"]:
                st.success(str(res["message"]))
                st.caption(f"完了日時: {res['timestamp']}")
                st.caption(f"保存先: {res['destination']}")
            else:
                st.error(str(res["message"]))


def build_activity_composite_chart(summaries: Sequence[DailyActivitySummary]) -> go.Figure:
    """Build composite dual-axis chart with daily steps (bar) and distance (line)."""
    df = pd.DataFrame([s.model_dump() for s in summaries])
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="アクティビティデータがありません")
        return fig

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["date_str"],
            y=df["step_count"],
            name="歩数 (歩)",
            marker_color="#2b825b",
            opacity=0.8,
            yaxis="y1",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["date_str"],
            y=df["distance_km"],
            name="距離 (km)",
            mode="lines+markers",
            line={"color": "#1f77b4", "width": 2.5},
            marker={"size": 6},
            yaxis="y2",
        )
    )

    fig.update_layout(
        title="日次歩数および移動距離の推移",
        xaxis={"title": "日付", "tickangle": -45},
        yaxis={"title": "歩数 (歩)", "side": "left", "showgrid": True},
        yaxis2={
            "title": "移動距離 (km)",
            "side": "right",
            "overlaying": "y",
            "showgrid": False,
        },
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 40, "r": 40, "t": 60, "b": 60},
        template="plotly_dark",
    )
    return fig


def build_calories_chart(summaries: Sequence[DailyActivitySummary]) -> go.Figure:
    """Build stacked or grouped bar chart comparing active vs total calories."""
    df = pd.DataFrame([s.model_dump() for s in summaries])
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="カロリーデータがありません")
        return fig

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["date_str"],
            y=df["active_calories_kcal"],
            name="アクティブ消費 (kcal)",
            marker_color="#ff7f0e",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["date_str"],
            y=df["total_calories_kcal"],
            name="総消費カロリー (kcal)",
            mode="lines+markers",
            line={"color": "#d62728", "width": 2},
        )
    )

    fig.update_layout(
        title="消費カロリー推移（アクティブ運動消費 / 総消費）",
        xaxis={"title": "日付", "tickangle": -45},
        yaxis={"title": "エネルギー (kcal)", "showgrid": True},
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 40, "r": 40, "t": 60, "b": 60},
        template="plotly_dark",
    )
    return fig


def build_body_measurement_chart(df: pd.DataFrame) -> go.Figure:
    """Build dual-axis chart for weight and body fat trends."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="身体測定データがありません")
        return fig

    fig = go.Figure()
    if "weight_kg" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=df["weight_kg"],
                name="体重 (kg)",
                mode="lines+markers",
                line={"color": "#00bc8c", "width": 2.5},
                marker={"size": 6},
                yaxis="y1",
            )
        )
    if "body_fat_pct" in df.columns and not df["body_fat_pct"].dropna().empty:
        fig.add_trace(
            go.Scatter(
                x=df["datetime"],
                y=df["body_fat_pct"],
                name="体脂肪率 (%)",
                mode="lines+markers",
                line={"color": "#f39c12", "width": 2},
                marker={"size": 6},
                yaxis="y2",
            )
        )

    fig.update_layout(
        title="体重および体脂肪率の長期推移",
        xaxis={"title": "測定日時"},
        yaxis={"title": "体重 (kg)", "side": "left", "showgrid": True},
        yaxis2={
            "title": "体脂肪率 (%)",
            "side": "right",
            "overlaying": "y",
            "showgrid": False,
        },
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 40, "r": 40, "t": 60, "b": 40},
        template="plotly_dark",
    )
    return fig


def build_daily_sleep_trend_chart(summaries: Sequence[DailySleepSummary]) -> go.Figure:
    """Render daily sleep duration trend line chart with recommended sleep threshold.

    Args:
        summaries: Sequence of DailySleepSummary ordered by date ascending.

    Returns:
        Plotly Figure object representing daily sleep duration in hours.
    """
    if not summaries:
        fig = go.Figure()
        fig.update_layout(title="日毎の睡眠時間推移データがありません", template="plotly_dark")
        return fig

    fig = go.Figure()

    # Recommended sleep threshold background band (7.0 to 8.0 hours)
    fig.add_hrect(
        y0=7.0,
        y1=8.0,
        line_width=0,
        fillcolor="#38bdf8",
        opacity=0.12,
        annotation_text="推奨睡眠基準 (7〜8h)",
        annotation_position="top left",
    )

    x_vals = [s.date_str for s in summaries]
    y_vals = [s.total_duration_hours for s in summaries]
    hover_texts = [
        f"{int(s.total_duration_minutes // 60)}時間 {int(s.total_duration_minutes % 60)}分 ({s.session_count}セッション)"
        for s in summaries
    ]

    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="lines+markers",
            line={"color": "#818cf8", "width": 3, "shape": "spline"},
            marker={"size": 8, "color": "#c7d2fe"},
            customdata=hover_texts,
            hovertemplate="<b>%{x}</b><br>合計睡眠時間: %{y:.2f} 時間<br>詳細: %{customdata}<extra></extra>",
            name="睡眠時間",
        )
    )

    fig.update_layout(
        title="📈 日毎の睡眠時間推移 (時間)",
        xaxis={"title": "日付", "showgrid": False},
        yaxis={"title": "睡眠時間 (時間)", "rangemode": "tozero"},
        height=360,
        margin={"l": 40, "r": 20, "t": 50, "b": 40},
        template="plotly_dark",
    )
    return fig


def build_sleep_stages_chart(stages: Sequence[SleepStageInterval]) -> go.Figure:
    """Render horizontal timeline / stage bands for single sleep session."""
    if not stages:
        fig = go.Figure()
        fig.update_layout(title="睡眠ステージ詳細データがありません")
        return fig

    color_map = {
        "覚醒 (AWAKE)": "#e74c3c",
        "浅い睡眠 (LIGHT)": "#3498db",
        "深い睡眠 (DEEP)": "#2c3e50",
        "レム睡眠 (REM)": "#9b59b6",
    }

    fig = go.Figure()
    for s in stages:
        c = color_map.get(s.stage_name, "#95a5a6")
        fig.add_trace(
            go.Bar(
                x=[s.duration_minutes],
                y=["睡眠ステージ"],
                orientation="h",
                name=s.stage_name,
                marker={"color": c},
                hoverinfo="text",
                hovertext=f"{s.stage_name}<br>開始: {s.start_time.strftime('%H:%M')}<br>終了: {s.end_time.strftime('%H:%M')}<br>継続: {s.duration_minutes}分",
                showlegend=False,
            )
        )

    fig.update_layout(
        barmode="stack",
        title="睡眠ステージ遷移タイムライン",
        xaxis={"title": "累積時間 (分)"},
        margin={"l": 20, "r": 20, "t": 40, "b": 40},
        height=200,
        template="plotly_dark",
    )
    return fig


def build_heart_rate_chart(df: pd.DataFrame) -> go.Figure:
    """Render heart rate trend with average line and min-max shaded range."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="心拍数データがありません")
        return fig

    fig = go.Figure()
    # Min-Max shaded band
    fig.add_trace(
        go.Scatter(
            x=df["date_str"],
            y=df["max_bpm"],
            mode="lines",
            line={"width": 0},
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["date_str"],
            y=df["min_bpm"],
            mode="lines",
            line={"width": 0},
            fill="tonexty",
            fillcolor="rgba(231, 76, 60, 0.2)",
            name="心拍変動幅 (Min-Max)",
        )
    )
    # Average line
    fig.add_trace(
        go.Scatter(
            x=df["date_str"],
            y=df["avg_bpm"],
            mode="lines+markers",
            name="日平均心拍数 (bpm)",
            line={"color": "#e74c3c", "width": 2.5},
            marker={"size": 6},
        )
    )

    fig.update_layout(
        title={
            "text": "日次平均心拍数と変動幅 (bpm)",
            "y": 0.98,
            "x": 0.0,
            "xanchor": "left",
            "yanchor": "top",
        },
        xaxis={"title": "日付", "tickangle": -45},
        yaxis={"title": "心拍数 (bpm)"},
        hovermode="x unified",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0.0,
        },
        margin={"l": 40, "r": 40, "t": 80, "b": 60},
        template="plotly_dark",
    )
    return fig


def build_oxygen_saturation_chart(df: pd.DataFrame) -> go.Figure:
    """Render oxygen saturation scatter trend and event highlights."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="血中酸素濃度データがありません")
        return fig

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["datetime"],
            y=df["percentage"],
            mode="markers",
            marker={"size": 5, "color": "#1abc9c", "opacity": 0.6},
            name="SpO2 計測値 (%)",
        )
    )
    # Reference threshold at 95%
    fig.add_hline(
        y=95.0,
        line_dash="dash",
        line_color="#e74c3c",
        annotation_text="警戒基準値 (95%)",
        annotation_position="bottom right",
    )

    fig.update_layout(
        title="血中酸素濃度 (SpO2) 測定分布",
        xaxis={"title": "測定日時"},
        yaxis={"title": "血中酸素濃度 (%)", "range": [85, 100]},
        hovermode="closest",
        margin={"l": 40, "r": 40, "t": 60, "b": 40},
        template="plotly_dark",
    )
    return fig


def render_route_map(points: Sequence[GpsRoutePoint]) -> None:
    """Render GPS route on an interactive 3D map using PyDeck."""
    if not points:
        st.info("🗺️ このセッションには GPS 経路データが記録されていません。")
        return

    coords = [[p.longitude, p.latitude] for p in points]
    center_lat = sum(p.latitude for p in points) / len(points)
    center_lon = sum(p.longitude for p in points) / len(points)

    path_data = [{"path": coords, "name": "GPS Route"}]

    layer = pdk.Layer(
        "PathLayer",
        path_data,
        pickable=True,
        get_color=[235, 87, 87, 255],
        width_scale=20,
        width_min_pixels=4,
        get_path="path",
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=14,
        pitch=30,
    )

    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view_state,
        tooltip={"text": "運動移動ルート"},
        map_style="mapbox://styles/mapbox/dark-v10",
    )
    st.pydeck_chart(deck)


def render_schema_table(columns: Sequence[ColumnMeta]) -> None:
    """Render formatted column schema table."""
    data = [
        {
            "CID": c.cid,
            "カラム名": c.name,
            "データ型": c.type_name,
            "主キー (PK)": "✓" if c.is_pk else "-",
            "Not Null": "✓" if c.not_null else "-",
            "デフォルト値": c.default_value or "-",
        }
        for c in columns
    ]
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)


def render_paginated_table(
    df: pd.DataFrame,
    table_name: str,
    key_prefix: str,
) -> None:
    """Render interactive DataFrame with CSV/JSON export buttons."""
    if df.empty:
        st.info(f"テーブル「{table_name}」には表示可能なレコードがありません（0件）。")
        return

    col_info, col_csv, col_json = st.columns([3, 1, 1])
    with col_info:
        st.caption(f"表示件数: {len(df):,} 行 / 全 {len(df.columns)} 列")
    with col_csv:
        csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 CSV ダウンロード",
            data=csv_bytes,
            file_name=f"{table_name}_export.csv",
            mime="text/csv",
            key=f"{key_prefix}_csv",
            use_container_width=True,
        )
    with col_json:
        json_bytes = df.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            label="📥 JSON ダウンロード",
            data=json_bytes,
            file_name=f"{table_name}_export.json",
            mime="application/json",
            key=f"{key_prefix}_json",
            use_container_width=True,
        )

    st.dataframe(df, use_container_width=True, hide_index=True)

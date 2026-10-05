from __future__ import annotations

import datetime
from unittest.mock import patch

import pandas as pd

from domain_models import (
    ColumnMeta,
    DailyActivitySummary,
    GpsRoutePoint,
    SleepStageInterval,
)
from ui_components import (
    build_activity_composite_chart,
    build_body_measurement_chart,
    build_calories_chart,
    build_heart_rate_chart,
    build_oxygen_saturation_chart,
    build_sleep_stages_chart,
    render_paginated_table,
    render_route_map,
    render_schema_table,
)


def test_build_activity_composite_chart() -> None:
    """Verify activity chart builder handles normal and empty inputs."""
    # Empty
    fig_empty = build_activity_composite_chart([])
    assert fig_empty is not None

    # Populated
    data = [
        DailyActivitySummary(
            date_str="2025-06-15",
            step_count=7000,
            distance_meters=5500.0,
            distance_km=5.5,
            active_calories_kcal=200.0,
            total_calories_kcal=1700.0,
        )
    ]
    fig = build_activity_composite_chart(data)
    assert len(fig.data) == 2


def test_build_calories_chart() -> None:
    """Verify calories chart construction."""
    data = [
        DailyActivitySummary(
            date_str="2025-06-15",
            step_count=7000,
            distance_meters=5500.0,
            distance_km=5.5,
            active_calories_kcal=200.0,
            total_calories_kcal=1700.0,
        )
    ]
    fig = build_calories_chart(data)
    assert len(fig.data) == 2


def test_build_body_measurement_chart() -> None:
    """Verify body measurements chart builder."""
    df = pd.DataFrame(
        [
            {
                "datetime": datetime.datetime(2025, 6, 15, 8, 0),
                "weight_kg": 68.5,
                "body_fat_pct": 17.5,
            }
        ]
    )
    fig = build_body_measurement_chart(df)
    assert len(fig.data) == 2

    fig_empty = build_body_measurement_chart(pd.DataFrame())
    assert fig_empty is not None


def test_build_sleep_stages_chart() -> None:
    """Verify sleep stage chart builder."""
    stages = [
        SleepStageInterval(
            stage_type=4,
            stage_name="浅い睡眠 (LIGHT)",
            start_time=datetime.datetime(2025, 6, 15, 0, 0),
            end_time=datetime.datetime(2025, 6, 15, 2, 0),
            duration_minutes=120.0,
        )
    ]
    fig = build_sleep_stages_chart(stages)
    assert len(fig.data) == 1

    fig_empty = build_sleep_stages_chart([])
    assert fig_empty is not None


def test_build_heart_rate_and_oxygen_saturation_charts() -> None:
    """Verify vitals chart builders."""
    df_hr = pd.DataFrame(
        [{"date_str": "2025-06-15", "avg_bpm": 72.0, "min_bpm": 60, "max_bpm": 120}]
    )
    fig_hr = build_heart_rate_chart(df_hr)
    assert len(fig_hr.data) == 3

    df_o2 = pd.DataFrame(
        [
            {
                "datetime": datetime.datetime(2025, 6, 15, 10, 0),
                "percentage": 98.0,
                "is_low_event": False,
            }
        ]
    )
    fig_o2 = build_oxygen_saturation_chart(df_o2)
    assert len(fig_o2.data) == 1


def test_render_route_map_calls_pydeck() -> None:
    """Verify render_route_map executes without errors."""
    points = [
        GpsRoutePoint(
            timestamp_millis=1750000000000, latitude=35.68, longitude=139.69, altitude_meters=10.0
        ),
        GpsRoutePoint(
            timestamp_millis=1750000010000, latitude=35.69, longitude=139.70, altitude_meters=11.0
        ),
    ]
    with patch("streamlit.pydeck_chart") as mock_pydeck:
        render_route_map(points)
        assert mock_pydeck.called


def test_render_schema_and_paginated_tables() -> None:
    """Verify table renderers."""
    cols = [ColumnMeta(cid=0, name="id", type_name="INTEGER", not_null=True, is_pk=True)]
    with patch("streamlit.dataframe") as mock_df:
        render_schema_table(cols)
        assert mock_df.called

    df = pd.DataFrame([{"id": 1, "name": "test"}])
    with patch("streamlit.dataframe") as mock_df, patch("streamlit.download_button"):
        render_paginated_table(df, "test_table", "prefix")
        assert mock_df.called


def test_render_backup_sidebar_triggers() -> None:
    """Verify render_backup_sidebar interaction flow."""
    from ui_components import render_backup_sidebar

    with (
        patch("streamlit.sidebar"),
        patch("streamlit.button", return_value=True),
        patch(
            "ui_components.run_backup",
            return_value={
                "success": True,
                "message": "OK",
                "timestamp": "now",
                "destination": "/tmp",
            },
        ),
    ):
        render_backup_sidebar()

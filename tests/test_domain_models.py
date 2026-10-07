import datetime

from domain_models import (
    DEFAULT_VISIBLE_TABS,
    PERIOD_PRESETS,
    SUMMARY_ITEMS_LABEL_MAP,
    DailySleepSummary,
    DashboardSettings,
    HealthDomainCategory,
    SummaryItemKey,
    resolve_category_for_table,
    resolve_filter_date_range,
)


def test_resolve_category_for_table_explicit() -> None:
    """Verify explicit mapping resolution."""
    assert resolve_category_for_table("steps_record_table") == HealthDomainCategory.ACTIVITY
    assert (
        resolve_category_for_table("weight_record_table") == HealthDomainCategory.BODY_MEASUREMENTS
    )
    assert resolve_category_for_table("sleep_session_record_table") == HealthDomainCategory.SLEEP
    assert (
        resolve_category_for_table("heart_rate_record_series_table") == HealthDomainCategory.VITALS
    )
    assert (
        resolve_category_for_table("menstruation_period_record_table")
        == HealthDomainCategory.CYCLE_TRACKING
    )
    assert (
        resolve_category_for_table("nutrition_record_table")
        == HealthDomainCategory.NUTRITION_WELLNESS
    )
    assert (
        resolve_category_for_table("medical_resource_table") == HealthDomainCategory.MEDICAL_RECORDS
    )
    assert (
        resolve_category_for_table("application_info_table") == HealthDomainCategory.SYSTEM_METADATA
    )


def test_resolve_category_for_table_fallbacks() -> None:
    """Verify keyword fallback inference rules."""
    assert resolve_category_for_table("custom_step_metrics") == HealthDomainCategory.ACTIVITY
    assert (
        resolve_category_for_table("patient_height_log") == HealthDomainCategory.BODY_MEASUREMENTS
    )
    assert resolve_category_for_table("nightly_sleep_summary") == HealthDomainCategory.SLEEP
    assert resolve_category_for_table("oxygen_monitor_events") == HealthDomainCategory.VITALS
    assert resolve_category_for_table("cervical_fluid_chart") == HealthDomainCategory.CYCLE_TRACKING
    assert (
        resolve_category_for_table("daily_hydrat_intake") == HealthDomainCategory.NUTRITION_WELLNESS
    )
    assert (
        resolve_category_for_table("hospital_medical_export")
        == HealthDomainCategory.MEDICAL_RECORDS
    )
    assert (
        resolve_category_for_table("unknown_unclassified_table")
        == HealthDomainCategory.SYSTEM_METADATA
    )


def test_health_domain_category_label_ja() -> None:
    """Verify all domain categories have Japanese display labels."""
    for cat in HealthDomainCategory:
        label = cat.label_ja
        assert isinstance(label, str)
        assert len(label) > 0


def test_daily_sleep_summary_model() -> None:
    """Verify DailySleepSummary instantiation and immutability."""
    summary = DailySleepSummary(
        date_str="2026-10-01",
        total_duration_minutes=450.0,
        total_duration_hours=7.5,
        session_count=1,
    )
    assert summary.date_str == "2026-10-01"
    assert summary.total_duration_minutes == 450.0
    assert summary.total_duration_hours == 7.5
    assert summary.session_count == 1


def test_dashboard_settings_model_defaults() -> None:
    """Verify DashboardSettings default values and item mappings."""
    settings = DashboardSettings()
    assert settings.visible_tabs == list(DEFAULT_VISIBLE_TABS)
    assert len(settings.visible_summary_items) == len(SummaryItemKey)
    for key in SummaryItemKey:
        assert key in SUMMARY_ITEMS_LABEL_MAP

    assert SummaryItemKey.CHART_CALORIES in SummaryItemKey
    assert SummaryItemKey.CHART_BODY_MEASUREMENT in SummaryItemKey
    assert SummaryItemKey.CHART_SLEEP_TREND in SummaryItemKey
    assert SummaryItemKey.CHART_HEART_RATE in SummaryItemKey
    assert SummaryItemKey.CHART_OXYGEN_SATURATION in SummaryItemKey


def test_period_presets_completeness() -> None:
    """Verify standard presets are defined."""
    assert "1か月" in PERIOD_PRESETS
    assert "3か月" in PERIOD_PRESETS
    assert "6か月" in PERIOD_PRESETS
    assert "1年" in PERIOD_PRESETS
    assert "3年" in PERIOD_PRESETS
    assert "5年" in PERIOD_PRESETS
    assert "全期間" in PERIOD_PRESETS
    assert "年月指定" in PERIOD_PRESETS


def test_resolve_filter_date_range_presets() -> None:
    """Verify date ranges calculated for relative presets."""
    anchor = datetime.date(2026, 10, 7)

    # 1 month
    s, e = resolve_filter_date_range("1か月", anchor)
    assert s == datetime.date(2026, 9, 7)
    assert e == anchor

    # 3 months
    s, e = resolve_filter_date_range("3か月", anchor)
    assert s == datetime.date(2026, 7, 7)
    assert e == anchor

    # 6 months
    s, e = resolve_filter_date_range("6か月", anchor)
    assert s == datetime.date(2026, 4, 7)
    assert e == anchor

    # 1 year
    s, e = resolve_filter_date_range("1年", anchor)
    assert s == datetime.date(2025, 10, 7)
    assert e == anchor

    # 3 years
    s, e = resolve_filter_date_range("3年", anchor)
    assert s == datetime.date(2023, 10, 7)
    assert e == anchor

    # 5 years
    s, e = resolve_filter_date_range("5年", anchor)
    assert s == datetime.date(2021, 10, 7)
    assert e == anchor

    # All time
    s, e = resolve_filter_date_range("全期間", anchor)
    assert s is None and e is None

    # Unknown preset fallback
    s, e = resolve_filter_date_range("invalid_preset", anchor)
    assert s is None and e is None


def test_resolve_filter_date_range_year_month() -> None:
    """Verify single month and range resolution under 年月指定."""
    anchor = datetime.date(2026, 10, 7)

    # Single month (defaults to anchor if None)
    s, e = resolve_filter_date_range("年月指定", anchor)
    assert s == datetime.date(2026, 10, 1)
    assert e == datetime.date(2026, 10, 31)

    # Specific single month (e.g., February leap year)
    s, e = resolve_filter_date_range("年月指定", anchor, custom_year=2024, custom_month=2)
    assert s == datetime.date(2024, 2, 1)
    assert e == datetime.date(2024, 2, 29)

    # Specific range (e.g., 2025-04 to 2025-09)
    s, e = resolve_filter_date_range(
        "年月指定",
        anchor,
        custom_year=2025,
        custom_month=4,
        custom_end_year=2025,
        custom_end_month=9,
    )
    assert s == datetime.date(2025, 4, 1)
    assert e == datetime.date(2025, 9, 30)

    # Inverted range auto-correction
    s, e = resolve_filter_date_range(
        "年月指定",
        anchor,
        custom_year=2026,
        custom_month=12,
        custom_end_year=2026,
        custom_end_month=1,
    )
    assert s == datetime.date(2026, 1, 1)
    assert e == datetime.date(2026, 12, 31)


def test_resolve_filter_date_range_boundary_clamping() -> None:
    """Verify end of month day clamping on month subtraction."""
    # March 31 to February (non-leap year)
    anchor_2025 = datetime.date(2025, 3, 31)
    s, e = resolve_filter_date_range("1か月", anchor_2025)
    assert s == datetime.date(2025, 2, 28)

    # March 31 to February (leap year 2024)
    anchor_2024 = datetime.date(2024, 3, 31)
    s, e = resolve_filter_date_range("1か月", anchor_2024)
    assert s == datetime.date(2024, 2, 29)

    # Leap day February 29 minus 1 year -> Feb 28
    anchor_leap = datetime.date(2024, 2, 29)
    s, e = resolve_filter_date_range("1年", anchor_leap)
    assert s == datetime.date(2023, 2, 28)

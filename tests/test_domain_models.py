from __future__ import annotations

from domain_models import (
    DEFAULT_VISIBLE_TABS,
    SUMMARY_ITEMS_LABEL_MAP,
    DailySleepSummary,
    DashboardSettings,
    HealthDomainCategory,
    SummaryItemKey,
    resolve_category_for_table,
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

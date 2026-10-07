"""Domain schemas, data models, and contracts for Google Health Connect Viewer."""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field


class HealthDomainCategory(StrEnum):
    """Google Health Connect の主要 8 大ドメイン分類。"""

    ACTIVITY = "activity"
    BODY_MEASUREMENTS = "body_measurements"
    SLEEP = "sleep"
    VITALS = "vitals"
    CYCLE_TRACKING = "cycle_tracking"
    NUTRITION_WELLNESS = "nutrition_wellness"
    MEDICAL_RECORDS = "medical_records"
    SYSTEM_METADATA = "system_metadata"

    @property
    def label_ja(self) -> str:
        """日本語ドメイン名表示ラベルを取得。"""
        labels: dict[HealthDomainCategory, str] = {
            HealthDomainCategory.ACTIVITY: "アクティビティ (運動・消費)",
            HealthDomainCategory.BODY_MEASUREMENTS: "身体測定 (体重・体組成)",
            HealthDomainCategory.SLEEP: "睡眠 (セッション・ステージ)",
            HealthDomainCategory.VITALS: "バイタル (心拍数・血中酸素)",
            HealthDomainCategory.CYCLE_TRACKING: "月経周期・生殖管理",
            HealthDomainCategory.NUTRITION_WELLNESS: "栄養・水分・ライフスタイル",
            HealthDomainCategory.MEDICAL_RECORDS: "医療データ (FHIR)",
            HealthDomainCategory.SYSTEM_METADATA: "システム・デバイス・監査ログ",
        }
        return labels[self]


class ColumnMeta(BaseModel):
    """SQLite カラムメタデータ定義。"""

    model_config = ConfigDict(frozen=True)

    cid: int
    name: str
    type_name: str
    not_null: bool
    default_value: str | None = None
    is_pk: bool = False


class TableCatalogMeta(BaseModel):
    """全 77 テーブルのカタログ構造およびレコード数定義。"""

    model_config = ConfigDict(frozen=True)

    table_name: str
    category: HealthDomainCategory
    row_count: int
    columns: Sequence[ColumnMeta]
    has_data: bool = False
    description: str = ""


class DashboardFilterParams(BaseModel):
    """ダッシュボード全体の共通絞り込みパラメータ契約。"""

    model_config = ConfigDict(frozen=True)

    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    selected_app_ids: Sequence[int] = Field(default_factory=tuple)
    selected_device_ids: Sequence[int] = Field(default_factory=tuple)


class DailyActivitySummary(BaseModel):
    """日次アクティビティ集計結果（歩数・距離・カロリー）。"""

    model_config = ConfigDict(frozen=True)

    date_str: str
    step_count: int = 0
    distance_meters: float = 0.0
    distance_km: float = 0.0
    active_calories_kcal: float = 0.0
    total_calories_kcal: float = 0.0


class GpsRoutePoint(BaseModel):
    """運動セッションに紐づく GPS 移動軌跡ポイント。"""

    model_config = ConfigDict(frozen=True)

    timestamp_millis: int
    latitude: float
    longitude: float
    altitude_meters: float = 0.0


class ExerciseSessionDetail(BaseModel):
    """ワークアウト・運動セッション詳細データ。"""

    model_config = ConfigDict(frozen=True)

    row_id: int
    title: str | None
    exercise_type: int
    exercise_type_name: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    duration_minutes: float
    has_route: bool
    route_points: Sequence[GpsRoutePoint] = Field(default_factory=tuple)


class SleepStageInterval(BaseModel):
    """睡眠ステージ区間情報。"""

    model_config = ConfigDict(frozen=True)

    stage_type: int
    stage_name: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    duration_minutes: float


class SleepSessionDetail(BaseModel):
    """睡眠セッションおよびステージ構成。"""

    model_config = ConfigDict(frozen=True)

    row_id: int
    start_time: datetime.datetime
    end_time: datetime.datetime
    total_duration_minutes: float
    stages: Sequence[SleepStageInterval] = Field(default_factory=tuple)


class DailySleepSummary(BaseModel):
    """日別睡眠集計データ契約。"""

    model_config = ConfigDict(frozen=True)

    date_str: str
    total_duration_minutes: float
    total_duration_hours: float
    session_count: int = 1


class SummaryItemKey(StrEnum):
    """サマリー表示項目の識別子。"""

    METRIC_STEPS = "metric_steps"
    METRIC_CALORIES = "metric_calories"
    METRIC_WEIGHT = "metric_weight"
    METRIC_SLEEP = "metric_sleep"
    CHART_ACTIVITY = "chart_activity"


DEFAULT_VISIBLE_TABS: Final[tuple[str, ...]] = (
    "📊 サマリー",
    "🏃 アクティビティ",
    "⚖️ 身体測定",
    "😴 睡眠",
    "❤️ バイタル",
    "🍎 栄養・生活",
    "🩺 医療・月経",
    "📱 デバイス・監査",
    "🔍 全77テーブル探索",
)

SUMMARY_ITEMS_LABEL_MAP: Final[Mapping[SummaryItemKey, str]] = {
    SummaryItemKey.METRIC_STEPS: "👟 最新日歩数・移動距離",
    SummaryItemKey.METRIC_CALORIES: "🔥 総消費カロリー",
    SummaryItemKey.METRIC_WEIGHT: "⚖️ 最新体重",
    SummaryItemKey.METRIC_SLEEP: "😴 直近睡眠時間",
    SummaryItemKey.CHART_ACTIVITY: "📈 アクティビティ複合推移グラフ",
}


class DashboardSettings(BaseModel):
    """ダッシュボード表示設定契約モデル。"""

    model_config = ConfigDict(frozen=True)

    visible_tabs: list[str] = Field(default_factory=lambda: list(DEFAULT_VISIBLE_TABS))
    visible_summary_items: list[str] = Field(
        default_factory=lambda: [k.value for k in SummaryItemKey]
    )


class HeartRatePoint(BaseModel):
    """心拍数時系列データポイント。"""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime.datetime
    bpm: int


class OxygenSaturationPoint(BaseModel):
    """血中酸素濃度 (SpO2) 計測ポイント。"""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime.datetime
    percentage: float


class BodyCompositionRecord(BaseModel):
    """体重・体脂肪率・BMR等の身体測定レコード。"""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime.datetime
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    bmr_kcal: float | None = None
    app_info_id: int | None = None
    device_info_id: int | None = None


class AppInfoItem(BaseModel):
    """連携アプリケーション情報。"""

    model_config = ConfigDict(frozen=True)

    row_id: int
    package_name: str
    app_name: str | None = None
    record_types_used: str | None = None


class DeviceInfoItem(BaseModel):
    """接続・登録デバイス情報。"""

    model_config = ConfigDict(frozen=True)

    row_id: int
    manufacturer: str | None = None
    model: str | None = None
    device_type: int = 0
    display_name: str | None = None


class ReadAccessLogItem(BaseModel):
    """データ読取アクセス監査ログ。"""

    model_config = ConfigDict(frozen=True)

    row_id: int
    reader_app_name: str
    writer_app_name: str
    record_type: str
    read_time: datetime.datetime


# 全 77 テーブルの静的ドメイン分類マッピング
_EXPLICIT_TABLE_CATEGORIES: Final[Mapping[str, HealthDomainCategory]] = {
    # 1. Activity
    "steps_record_table": HealthDomainCategory.ACTIVITY,
    "steps_cadence_record_table": HealthDomainCategory.ACTIVITY,
    "stepscadencerecordtable": HealthDomainCategory.ACTIVITY,
    "distance_record_table": HealthDomainCategory.ACTIVITY,
    "speed_record_table": HealthDomainCategory.ACTIVITY,
    "speedrecordtable": HealthDomainCategory.ACTIVITY,
    "active_calories_burned_record_table": HealthDomainCategory.ACTIVITY,
    "total_calories_burned_record_table": HealthDomainCategory.ACTIVITY,
    "exercise_session_record_table": HealthDomainCategory.ACTIVITY,
    "exercise_segments_table": HealthDomainCategory.ACTIVITY,
    "exercise_route_table": HealthDomainCategory.ACTIVITY,
    "exercise_laps_table": HealthDomainCategory.ACTIVITY,
    "activity_date_table": HealthDomainCategory.ACTIVITY,
    "activity_intensity_record_table": HealthDomainCategory.ACTIVITY,
    "elevation_gained_record_table": HealthDomainCategory.ACTIVITY,
    "floors_climbed_record_table": HealthDomainCategory.ACTIVITY,
    "power_record_table": HealthDomainCategory.ACTIVITY,
    "powerrecordtable": HealthDomainCategory.ACTIVITY,
    "cycling_pedaling_cadence_record_table": HealthDomainCategory.ACTIVITY,
    "cyclingpedalingcadencerecordtable": HealthDomainCategory.ACTIVITY,
    "wheelchair_pushes_record_table": HealthDomainCategory.ACTIVITY,
    "planned_exercise_session_record_table": HealthDomainCategory.ACTIVITY,
    "planned_exercise_session_blocks_table": HealthDomainCategory.ACTIVITY,
    "planned_exercise_session_steps_table": HealthDomainCategory.ACTIVITY,
    "planned_exercise_session_goals_table": HealthDomainCategory.ACTIVITY,
    # 2. Body Measurements
    "weight_record_table": HealthDomainCategory.BODY_MEASUREMENTS,
    "height_record_table": HealthDomainCategory.BODY_MEASUREMENTS,
    "body_fat_record_table": HealthDomainCategory.BODY_MEASUREMENTS,
    "basal_metabolic_rate_record_table": HealthDomainCategory.BODY_MEASUREMENTS,
    "bone_mass_record_table": HealthDomainCategory.BODY_MEASUREMENTS,
    "lean_body_mass_record_table": HealthDomainCategory.BODY_MEASUREMENTS,
    "body_water_mass_record_table": HealthDomainCategory.BODY_MEASUREMENTS,
    # 3. Sleep
    "sleep_session_record_table": HealthDomainCategory.SLEEP,
    "sleep_stages_table": HealthDomainCategory.SLEEP,
    # 4. Vitals
    "heart_rate_record_table": HealthDomainCategory.VITALS,
    "heart_rate_record_series_table": HealthDomainCategory.VITALS,
    "resting_heart_rate_record_table": HealthDomainCategory.VITALS,
    "heart_rate_variability_rmssd_record_table": HealthDomainCategory.VITALS,
    "oxygen_saturation_record_table": HealthDomainCategory.VITALS,
    "blood_glucose_record_table": HealthDomainCategory.VITALS,
    "blood_pressure_record_table": HealthDomainCategory.VITALS,
    "body_temperature_record_table": HealthDomainCategory.VITALS,
    "basal_body_temperature_record_table": HealthDomainCategory.VITALS,
    "respiratory_rate_record_table": HealthDomainCategory.VITALS,
    "skin_temperature_record_table": HealthDomainCategory.VITALS,
    "skin_temperature_delta_table": HealthDomainCategory.VITALS,
    "vo2_max_record_table": HealthDomainCategory.VITALS,
    # 5. Cycle Tracking
    "menstruation_period_record_table": HealthDomainCategory.CYCLE_TRACKING,
    "menstruation_flow_record_table": HealthDomainCategory.CYCLE_TRACKING,
    "menstrual_cycle_phase_record_table": HealthDomainCategory.CYCLE_TRACKING,
    "cervical_mucus_record_table": HealthDomainCategory.CYCLE_TRACKING,
    "ovulation_test_record_table": HealthDomainCategory.CYCLE_TRACKING,
    "intermenstrual_bleeding_record_table": HealthDomainCategory.CYCLE_TRACKING,
    "sexual_activity_record_table": HealthDomainCategory.CYCLE_TRACKING,
    # 6. Nutrition & Wellness
    "nutrition_record_table": HealthDomainCategory.NUTRITION_WELLNESS,
    "hydration_record_table": HealthDomainCategory.NUTRITION_WELLNESS,
    "mindfulness_session_record_table": HealthDomainCategory.NUTRITION_WELLNESS,
    "alcohol_consumption_record_table": HealthDomainCategory.NUTRITION_WELLNESS,
    "nicotine_intake_record_table": HealthDomainCategory.NUTRITION_WELLNESS,
    "symptom_record_table": HealthDomainCategory.NUTRITION_WELLNESS,
    # 7. Medical Records
    "medical_resource_table": HealthDomainCategory.MEDICAL_RECORDS,
    "medical_data_source_table": HealthDomainCategory.MEDICAL_RECORDS,
    "medical_resource_indices_table": HealthDomainCategory.MEDICAL_RECORDS,
    # 8. System & Metadata
    "application_info_table": HealthDomainCategory.SYSTEM_METADATA,
    "device_info_table": HealthDomainCategory.SYSTEM_METADATA,
    "device_data_sources_table": HealthDomainCategory.SYSTEM_METADATA,
    "device_data_provider_metadata_table": HealthDomainCategory.SYSTEM_METADATA,
    "read_access_logs_table": HealthDomainCategory.SYSTEM_METADATA,
    "access_logs_table": HealthDomainCategory.SYSTEM_METADATA,
    "change_logs_table": HealthDomainCategory.SYSTEM_METADATA,
    "change_log_request_table": HealthDomainCategory.SYSTEM_METADATA,
    "backup_change_token_table": HealthDomainCategory.SYSTEM_METADATA,
    "health_data_category_priority_table": HealthDomainCategory.SYSTEM_METADATA,
    "preference_table": HealthDomainCategory.SYSTEM_METADATA,
    "android_metadata": HealthDomainCategory.SYSTEM_METADATA,
    "migration_entity_table": HealthDomainCategory.SYSTEM_METADATA,
    "pre_migration_category_priority_table": HealthDomainCategory.SYSTEM_METADATA,
}


def resolve_category_for_table(table_name: str) -> HealthDomainCategory:
    """テーブル名に基づいて HealthDomainCategory を決定する。"""
    normalized = table_name.lower()
    if normalized in _EXPLICIT_TABLE_CATEGORIES:
        return _EXPLICIT_TABLE_CATEGORIES[normalized]

    # フォールバック推論ルール
    if any(
        k in normalized
        for k in ["step", "dist", "speed", "calor", "exerc", "elev", "floor", "power"]
    ):
        return HealthDomainCategory.ACTIVITY
    if any(k in normalized for k in ["weight", "height", "fat", "bmr", "bone", "mass"]):
        return HealthDomainCategory.BODY_MEASUREMENTS
    if "sleep" in normalized:
        return HealthDomainCategory.SLEEP
    if any(k in normalized for k in ["heart", "oxygen", "glucose", "press", "temp", "resp", "vo2"]):
        return HealthDomainCategory.VITALS
    if any(k in normalized for k in ["menstr", "cervic", "ovul", "bleed"]):
        return HealthDomainCategory.CYCLE_TRACKING
    if any(k in normalized for k in ["nutrit", "hydrat", "mindful", "alcoh", "nicot", "sympt"]):
        return HealthDomainCategory.NUTRITION_WELLNESS
    if "medic" in normalized:
        return HealthDomainCategory.MEDICAL_RECORDS

    return HealthDomainCategory.SYSTEM_METADATA


EXERCISE_TYPE_MAP: Final[Mapping[int, str]] = {
    0: "OTHER_WORKOUT",
    1: "BACK_EXTENSION",
    2: "BADMINTON",
    3: "BARBELL_SHOULDER_PRESS",
    4: "BASEBALL",
    5: "BASKETBALL",
    8: "BIKING",
    10: "BOOTCAMP",
    11: "BOXING",
    13: "CALISTHENICS",
    14: "CRICKET",
    16: "DANCING",
    25: "ELLIPTICAL",
    26: "EXERCISE_CLASS",
    27: "FENCING",
    28: "FOOTBALL_AMERICAN",
    29: "FOOTBALL_AUSTRALIAN",
    30: "FORWARD_TWIST",
    31: "FRISBEE_DISC",
    32: "GOLF",
    33: "GUIDED_BREATHING",
    34: "GYMNASTICS",
    35: "HANDBALL",
    36: "HIGH_INTENSITY_INTERVAL_TRAINING",
    37: "HIKING",
    38: "ICE_HOCKEY",
    39: "ICE_SKATING",
    40: "JUMPING_JACK",
    41: "JUMP_ROPE",
    42: "LAT_PULL_DOWN",
    43: "LUNGE",
    44: "MARTIAL_ARTS",
    48: "PADDLESPORTS",
    49: "PILATES",
    50: "PLANK",
    53: "WALKING",
    54: "WATER_POLO",
    55: "WEIGHTLIFTING",
    56: "WHEELCHAIR",
    57: "YOGA",
    79: "RUNNING",
}

SLEEP_STAGE_MAP: Final[Mapping[int, str]] = {
    0: "不明 (UNKNOWN)",
    1: "覚醒 (AWAKE)",
    2: "睡眠中 (SLEEPING)",
    3: "ベッド外 (OUT_OF_BED)",
    4: "浅い睡眠 (LIGHT)",
    5: "深い睡眠 (DEEP)",
    6: "レム睡眠 (REM)",
}

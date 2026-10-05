"""Analytics and aggregation service for Google Health Connect data with SQL pushdown."""

from __future__ import annotations

import datetime

import pandas as pd

from db_engine import HealthConnectDbEngine
from domain_models import (
    EXERCISE_TYPE_MAP,
    SLEEP_STAGE_MAP,
    AppInfoItem,
    DailyActivitySummary,
    DashboardFilterParams,
    DeviceInfoItem,
    ExerciseSessionDetail,
    GpsRoutePoint,
    ReadAccessLogItem,
    SleepSessionDetail,
    SleepStageInterval,
)


class HealthConnectAnalyticsService:
    """Domain analytics engine performing SQL pushdown aggregations."""

    def __init__(self, db_engine: HealthConnectDbEngine) -> None:
        """Initialize analytics service with database engine.

        Args:
            db_engine: HealthConnectDbEngine instance.
        """
        self._engine = db_engine

    def get_database_date_range(self) -> tuple[datetime.date | None, datetime.date | None]:
        """Determine min and max dates available across primary activity/vital records.

        Returns:
            Tuple of (earliest_date, latest_date).
        """
        query = """
            SELECT min(start_time), max(start_time) FROM steps_record_table
            WHERE start_time IS NOT NULL AND start_time > 0;
        """
        df = self._engine.execute_query(query)
        if df.empty or df.iloc[0, 0] is None:
            return None, None

        raw_min = df.iloc[0, 0]
        raw_max = df.iloc[0, 1]
        try:
            min_ms = float(str(raw_min)) if pd.notna(raw_min) else None
        except ValueError, TypeError:
            min_ms = None

        try:
            max_ms = float(str(raw_max)) if pd.notna(raw_max) else None
        except ValueError, TypeError:
            max_ms = None

        min_dt = self._engine.epoch_millis_to_dt(min_ms)
        max_dt = self._engine.epoch_millis_to_dt(max_ms)

        start_d = min_dt.date() if min_dt else None
        end_d = max_dt.date() if max_dt else None
        return start_d, end_d

    def get_apps_list(self) -> list[AppInfoItem]:
        """Fetch all registered apps in application_info_table.

        Returns:
            List of AppInfoItem.
        """
        query = """
            SELECT row_id, package_name, app_name, record_types_used
            FROM application_info_table
            ORDER BY row_id ASC;
        """
        df = self._engine.execute_query(query)
        items: list[AppInfoItem] = []
        for _, row in df.iterrows():
            items.append(
                AppInfoItem(
                    row_id=int(row["row_id"]),
                    package_name=str(row["package_name"]),
                    app_name=str(row["app_name"]) if pd.notna(row["app_name"]) else None,
                    record_types_used=str(row["record_types_used"])
                    if pd.notna(row["record_types_used"])
                    else None,
                )
            )
        return items

    def get_devices_list(self) -> list[DeviceInfoItem]:
        """Fetch all registered devices in device_info_table.

        Returns:
            List of DeviceInfoItem.
        """
        query = """
            SELECT row_id, manufacturer, model, device_type, display_name
            FROM device_info_table
            ORDER BY row_id ASC;
        """
        df = self._engine.execute_query(query)
        items: list[DeviceInfoItem] = []
        for _, row in df.iterrows():
            items.append(
                DeviceInfoItem(
                    row_id=int(row["row_id"]),
                    manufacturer=str(row["manufacturer"])
                    if pd.notna(row["manufacturer"])
                    else None,
                    model=str(row["model"]) if pd.notna(row["model"]) else None,
                    device_type=int(row["device_type"]) if pd.notna(row["device_type"]) else 0,
                    display_name=str(row["display_name"])
                    if pd.notna(row["display_name"])
                    else None,
                )
            )
        return items

    def get_daily_activity_summary(
        self,
        filters: DashboardFilterParams,
    ) -> list[DailyActivitySummary]:
        """Aggregate daily steps, distance, active calories and total calories.

        Args:
            filters: Filter parameters.

        Returns:
            List of DailyActivitySummary ordered by date ascending.
        """
        where_clause, params = self._engine.build_time_filter_clause("start_time", filters)

        # 1. Daily steps aggregation (JST +9 hours)
        steps_query = f"""
            SELECT
                strftime('%Y-%m-%d', datetime(start_time / 1000, 'unixepoch', '+9 hours')) AS day_str,
                sum(count) AS total_steps
            FROM steps_record_table
            WHERE start_time IS NOT NULL {where_clause}
            GROUP BY day_str
            ORDER BY day_str ASC;
        """
        df_steps = self._engine.execute_query(steps_query, params)

        # 2. Daily distance aggregation (m -> km)
        dist_query = f"""
            SELECT
                strftime('%Y-%m-%d', datetime(start_time / 1000, 'unixepoch', '+9 hours')) AS day_str,
                sum(distance) AS total_meters
            FROM distance_record_table
            WHERE start_time IS NOT NULL {where_clause}
            GROUP BY day_str;
        """
        df_dist = self._engine.execute_query(dist_query, params)

        # 3. Daily active calories (cal -> kcal)
        act_cal_query = f"""
            SELECT
                strftime('%Y-%m-%d', datetime(start_time / 1000, 'unixepoch', '+9 hours')) AS day_str,
                sum(energy) / 1000.0 AS active_kcal
            FROM active_calories_burned_record_table
            WHERE start_time IS NOT NULL {where_clause}
            GROUP BY day_str;
        """
        df_act_cal = self._engine.execute_query(act_cal_query, params)

        # 4. Daily total calories (cal -> kcal)
        tot_cal_query = f"""
            SELECT
                strftime('%Y-%m-%d', datetime(start_time / 1000, 'unixepoch', '+9 hours')) AS day_str,
                sum(energy) / 1000.0 AS total_kcal
            FROM total_calories_burned_record_table
            WHERE start_time IS NOT NULL {where_clause}
            GROUP BY day_str;
        """
        df_tot_cal = self._engine.execute_query(tot_cal_query, params)

        if df_steps.empty:
            return []

        merged = df_steps.merge(df_dist, on="day_str", how="left")
        merged = merged.merge(df_act_cal, on="day_str", how="left")
        merged = merged.merge(df_tot_cal, on="day_str", how="left")
        merged = merged.fillna(0.0)

        summaries: list[DailyActivitySummary] = []
        for _, row in merged.iterrows():
            d_m = float(row.get("total_meters", 0.0))
            summaries.append(
                DailyActivitySummary(
                    date_str=str(row["day_str"]),
                    step_count=int(row.get("total_steps", 0)),
                    distance_meters=d_m,
                    distance_km=round(d_m / 1000.0, 2),
                    active_calories_kcal=round(float(row.get("active_kcal", 0.0)), 1),
                    total_calories_kcal=round(float(row.get("total_kcal", 0.0)), 1),
                )
            )
        return summaries

    def get_exercise_sessions(
        self,
        filters: DashboardFilterParams,
    ) -> list[ExerciseSessionDetail]:
        """Fetch exercise sessions with optional route availability.

        Args:
            filters: Filter parameters.

        Returns:
            List of ExerciseSessionDetail.
        """
        where_clause, params = self._engine.build_time_filter_clause("start_time", filters)
        query = f"""
            SELECT
                s.row_id,
                s.title,
                s.exercise_type,
                s.start_time,
                s.end_time,
                (s.end_time - s.start_time) / 60000.0 AS duration_minutes,
                (SELECT count(*) FROM exercise_route_table r WHERE r.parent_key = s.row_id) > 0 AS has_route
            FROM exercise_session_record_table s
            WHERE s.start_time IS NOT NULL {where_clause}
            ORDER BY s.start_time DESC;
        """
        df = self._engine.execute_query(query, params)
        sessions: list[ExerciseSessionDetail] = []
        for _, row in df.iterrows():
            start_dt = self._engine.epoch_millis_to_dt(row["start_time"])
            end_dt = self._engine.epoch_millis_to_dt(row["end_time"])
            if not start_dt or not end_dt:
                continue

            etype = int(row["exercise_type"])
            sessions.append(
                ExerciseSessionDetail(
                    row_id=int(row["row_id"]),
                    title=str(row["title"]) if pd.notna(row["title"]) else None,
                    exercise_type=etype,
                    exercise_type_name=EXERCISE_TYPE_MAP.get(etype, f"WORKOUT_{etype}"),
                    start_time=start_dt,
                    end_time=end_dt,
                    duration_minutes=round(float(row["duration_minutes"]), 1),
                    has_route=bool(row["has_route"]),
                )
            )
        return sessions

    def get_exercise_route_points(self, session_row_id: int) -> list[GpsRoutePoint]:
        """Retrieve coordinate route points for specific exercise session.

        Args:
            session_row_id: row_id of exercise session.

        Returns:
            List of GpsRoutePoint ordered by timestamp.
        """
        query = """
            SELECT timestamp_millis, latitude, longitude, altitude
            FROM exercise_route_table
            WHERE parent_key = ?
            ORDER BY timestamp_millis ASC;
        """
        df = self._engine.execute_query(query, (session_row_id,))
        points: list[GpsRoutePoint] = []
        for _, row in df.iterrows():
            points.append(
                GpsRoutePoint(
                    timestamp_millis=int(row["timestamp_millis"]),
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    altitude_meters=float(row["altitude"]) if pd.notna(row["altitude"]) else 0.0,
                )
            )
        return points

    def get_body_measurements_df(
        self,
        filters: DashboardFilterParams,
    ) -> pd.DataFrame:
        """Fetch weight, body fat, and BMR measurements.

        Args:
            filters: Filter parameters.

        Returns:
            DataFrame with datetime, weight_kg, body_fat_pct, bmr_kcal.
        """
        where_w, params_w = self._engine.build_time_filter_clause("time", filters)
        query_w = f"""
            SELECT
                time,
                weight / 1000.0 AS weight_kg,
                device_info_id,
                app_info_id
            FROM weight_record_table
            WHERE time IS NOT NULL {where_w}
            ORDER BY time ASC;
        """
        df_w = self._engine.execute_query(query_w, params_w)

        query_f = f"""
            SELECT
                time,
                percentage AS body_fat_pct
            FROM body_fat_record_table
            WHERE time IS NOT NULL {where_w}
            ORDER BY time ASC;
        """
        df_f = self._engine.execute_query(query_f, params_w)

        query_b = f"""
            SELECT
                time,
                round(basal_metabolic_rate * 86400.0 / 4184.0, 1) AS bmr_kcal
            FROM basal_metabolic_rate_record_table
            WHERE time IS NOT NULL {where_w}
            ORDER BY time ASC;
        """
        df_b = self._engine.execute_query(query_b, params_w)

        if df_w.empty:
            return pd.DataFrame()

        df_w["datetime"] = df_w["time"].apply(self._engine.epoch_millis_to_dt)
        df_f["datetime"] = df_f["time"].apply(self._engine.epoch_millis_to_dt)
        df_b["datetime"] = df_b["time"].apply(self._engine.epoch_millis_to_dt)

        # Merge on approximate timestamp or exact datetime
        merged = df_w.merge(df_f[["datetime", "body_fat_pct"]], on="datetime", how="left")
        merged = merged.merge(df_b[["datetime", "bmr_kcal"]], on="datetime", how="left")
        merged = merged.sort_values("datetime").reset_index(drop=True)
        return merged

    def get_sleep_sessions(
        self,
        filters: DashboardFilterParams,
    ) -> list[SleepSessionDetail]:
        """Retrieve sleep sessions and their associated sleep stage intervals.

        Args:
            filters: Filter parameters.

        Returns:
            List of SleepSessionDetail.
        """
        where_clause, params = self._engine.build_time_filter_clause("start_time", filters)
        query = f"""
            SELECT row_id, start_time, end_time,
                   (end_time - start_time) / 60000.0 AS total_duration_min
            FROM sleep_session_record_table
            WHERE start_time IS NOT NULL {where_clause}
            ORDER BY start_time DESC;
        """
        df_sessions = self._engine.execute_query(query, params)
        results: list[SleepSessionDetail] = []

        for _, srow in df_sessions.iterrows():
            session_id = int(srow["row_id"])
            s_dt = self._engine.epoch_millis_to_dt(srow["start_time"])
            e_dt = self._engine.epoch_millis_to_dt(srow["end_time"])
            if not s_dt or not e_dt:
                continue

            # Query stages
            st_query = """
                SELECT stage_type, stage_start_time, stage_end_time,
                       (stage_end_time - stage_start_time) / 60000.0 AS stage_dur_min
                FROM sleep_stages_table
                WHERE parent_key = ?
                ORDER BY stage_start_time ASC;
            """
            df_stages = self._engine.execute_query(st_query, (session_id,))
            stages: list[SleepStageInterval] = []
            for _, strow in df_stages.iterrows():
                st_dt = self._engine.epoch_millis_to_dt(strow["stage_start_time"])
                et_dt = self._engine.epoch_millis_to_dt(strow["stage_end_time"])
                if st_dt and et_dt:
                    stype = int(strow["stage_type"])
                    stages.append(
                        SleepStageInterval(
                            stage_type=stype,
                            stage_name=SLEEP_STAGE_MAP.get(stype, f"STAGE_{stype}"),
                            start_time=st_dt,
                            end_time=et_dt,
                            duration_minutes=round(float(strow["stage_dur_min"]), 1),
                        )
                    )

            results.append(
                SleepSessionDetail(
                    row_id=session_id,
                    start_time=s_dt,
                    end_time=e_dt,
                    total_duration_minutes=round(float(srow["total_duration_min"]), 1),
                    stages=stages,
                )
            )
        return results

    def get_heart_rate_summary_df(
        self,
        filters: DashboardFilterParams,
    ) -> pd.DataFrame:
        """Fetch downsampled daily/hourly heart rate stats.

        Args:
            filters: Filter parameters.

        Returns:
            DataFrame with date_str, avg_bpm, min_bpm, max_bpm, sample_count.
        """
        where_clause, params = self._engine.build_time_filter_clause("epoch_millis", filters)
        query = f"""
            SELECT
                strftime('%Y-%m-%d', datetime(epoch_millis / 1000, 'unixepoch', '+9 hours')) AS date_str,
                round(avg(beats_per_minute), 1) AS avg_bpm,
                min(beats_per_minute) AS min_bpm,
                max(beats_per_minute) AS max_bpm,
                count(*) AS sample_count
            FROM heart_rate_record_series_table
            WHERE epoch_millis IS NOT NULL {where_clause}
            GROUP BY date_str
            ORDER BY date_str ASC;
        """
        return self._engine.execute_query(query, params)

    def get_oxygen_saturation_df(
        self,
        filters: DashboardFilterParams,
    ) -> pd.DataFrame:
        """Fetch oxygen saturation records with datetime and status.

        Args:
            filters: Filter parameters.

        Returns:
            DataFrame with datetime, percentage, is_low_event.
        """
        where_clause, params = self._engine.build_time_filter_clause("time", filters)
        query = f"""
            SELECT
                time,
                percentage,
                (percentage < 95.0) AS is_low_event
            FROM oxygen_saturation_record_table
            WHERE time IS NOT NULL {where_clause}
            ORDER BY time ASC;
        """
        df = self._engine.execute_query(query, params)
        if not df.empty:
            df["datetime"] = df["time"].apply(self._engine.epoch_millis_to_dt)
        return df

    def get_read_access_audit_logs(self, limit: int = 500) -> list[ReadAccessLogItem]:
        """Fetch audit logs of data reads between apps.

        Args:
            limit: Maximum rows to return.

        Returns:
            List of ReadAccessLogItem.
        """
        query = f"""
            SELECT
                l.row_id,
                coalesce(r.app_name, r.package_name, 'App_' || l.reader_app_id) AS reader_name,
                coalesce(w.app_name, w.package_name, 'App_' || l.writer_app_id) AS writer_name,
                l.record_type,
                l.read_time
            FROM read_access_logs_table l
            LEFT JOIN application_info_table r ON l.reader_app_id = r.row_id
            LEFT JOIN application_info_table w ON l.writer_app_id = w.row_id
            ORDER BY l.read_time DESC
            LIMIT {limit};
        """
        df = self._engine.execute_query(query)
        items: list[ReadAccessLogItem] = []
        for _, row in df.iterrows():
            r_dt = self._engine.epoch_millis_to_dt(row["read_time"])
            if r_dt:
                items.append(
                    ReadAccessLogItem(
                        row_id=int(row["row_id"]),
                        reader_app_name=str(row["reader_name"]),
                        writer_app_name=str(row["writer_name"]),
                        record_type=str(row["record_type"]),
                        read_time=r_dt,
                    )
                )
        return items

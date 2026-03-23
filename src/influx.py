"""InfluxDB v2 writer for Speediance workout data."""

import logging
from datetime import datetime, timezone

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from .config import InfluxConfig, MainConfig
from .models import MuscleDetail, StrengthEstimate, Workout

logger = logging.getLogger(__name__)


class InfluxWriter:
    def __init__(self, config: InfluxConfig, main_config: MainConfig):
        self._config = config
        self._main_config = main_config
        self._client = InfluxDBClient(
            url=config.url,
            token=config.token,
            org=config.org,
        )
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        self._query_api = self._client.query_api()

    def close(self):
        self._client.close()

    def get_last_workout_timestamp(self) -> int:
        """Query InfluxDB for the most recent workout timestamp (epoch seconds)."""
        query = f'''
            from(bucket: "{self._config.bucket}")
                |> range(start: -365d)
                |> filter(fn: (r) => r._measurement == "workout")
                |> filter(fn: (r) => r._field == "duration_secs")
                |> keep(columns: ["_time"])
                |> sort(columns: ["_time"], desc: true)
                |> limit(n: 1)
        '''
        try:
            tables = self._query_api.query(query, org=self._config.org)
            for table in tables:
                for record in table.records:
                    return int(record.get_time().timestamp())
        except Exception:
            logger.exception("Failed to query last workout timestamp")
        return 0

    def write_workout(self, workout: Workout):
        """Write a workout summary point to InfluxDB."""
        ts = datetime.fromtimestamp(workout.end_timestamp, tz=timezone.utc)

        point = (
            Point("workout")
            .tag("type", workout.workout_type or "Unknown")
            .tag("title", workout.title)
            .field("duration_secs", workout.duration_secs)
            .field("calories", workout.calories)
            .field("volume_kg", workout.volume_kg)
            .field("energy_j", workout.energy_j)
            .field("mileage", workout.mileage)
            .field("completion_rate", workout.completion_rate)
            .field("exercise_count", workout.exercise_count)
            .field("training_id", workout.training_id)
            .time(ts, WritePrecision.S)
        )

        self._write_api.write(bucket=self._config.bucket, record=point)
        logger.debug("Wrote workout: %s", workout.title)

        if self._main_config.write_sets and workout.sets:
            self._write_sets(workout)

    def _write_sets(self, workout: Workout):
        """Write per-set data points."""
        ts_base = datetime.fromtimestamp(workout.start_timestamp, tz=timezone.utc)
        points = []

        for s in workout.sets:
            # Offset each set by its index to avoid timestamp collisions
            point = (
                Point("workout_sets")
                .tag("workout_title", workout.title)
                .tag("exercise", s.exercise_name)
                .tag("workout_type", workout.workout_type or "Unknown")
                .field("set_index", s.set_index)
                .field("finished_reps", s.finished_reps)
                .field("target_reps", s.target_reps)
                .field("capacity", s.capacity)
                .field("max_heart_rate", s.max_heart_rate)
                .field("time_secs", s.time_secs)
                .field("score", s.score)
                .field("force_control_score", s.force_control_score)
                .field("completion_score", s.completion_score)
                .field("max_weight", s.max_weight)
                .field("left_right", s.left_right)
                .field("training_id", workout.training_id)
                .time(ts_base, WritePrecision.S)
            )
            points.append(point)

        if points:
            self._write_api.write(bucket=self._config.bucket, record=points)
            logger.debug("Wrote %d set points for %s", len(points), workout.title)

    def write_muscles(self, muscles: list[MuscleDetail], timestamp: int):
        """Write muscle activation detail."""
        ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        points = []

        for m in muscles:
            point = (
                Point("workout_muscles")
                .tag("muscle_group", m.muscle_group_name)
                .tag("muscle_group_id", m.muscle_group_config_id)
                .field("intensity_level", m.intensity_level)
                .field("fatigue", m.fatigue)
                .field("min_weight", m.min_weight)
                .field("max_weight", m.max_weight)
                .field("training_time_secs", m.training_time_secs)
                .field("total_capacity", m.total_capacity)
                .field("exercise_count", m.exercise_count)
                .time(ts, WritePrecision.S)
            )
            points.append(point)

        if points:
            self._write_api.write(bucket=self._config.bucket, record=points)
            logger.debug("Wrote %d muscle points", len(points))

    def write_1rm(self, estimates: list[StrengthEstimate]):
        """Write 1RM strength estimates."""
        points = []

        for e in estimates:
            # Use assessment date as timestamp
            try:
                ts = datetime.strptime(e.assessment_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            point = (
                Point("strength_1rm")
                .tag("exercise", e.exercise_name)
                .field("rm1_weight", e.rm1_weight)
                .field("exercise_group_id", e.exercise_group_id)
                .field("training_part_id", e.training_part_id)
                .time(ts, WritePrecision.S)
            )
            points.append(point)

        if points:
            self._write_api.write(bucket=self._config.bucket, record=points)
            logger.debug("Wrote %d 1RM points", len(points))

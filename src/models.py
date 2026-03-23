"""Dataclasses for Speediance workout data."""

from dataclasses import dataclass, field


@dataclass
class SetData:
    exercise_name: str
    muscle_group_id: int  # trainingPartId2
    set_index: int
    finished_reps: int = 0
    target_reps: int = 0
    capacity: float = 0.0
    max_heart_rate: float = 0.0
    time_secs: int = 0
    score: int = 0
    force_control_score: int = 0
    completion_score: int = 0
    bilateral_balance_score: int = 0
    left_right: int = 0  # 0=both, 1=left, 2=right
    category_id: int = 0  # 1=warmup, 2=cardio, 3=strength, etc.
    is_custom: bool = False
    max_weight: float = 0.0


@dataclass
class MuscleDetail:
    muscle_group_name: str
    muscle_group_config_id: str
    training_part_id: int
    intensity_level: int = 0
    fatigue: int = 0
    min_weight: float = 0.0
    max_weight: float = 0.0
    training_time_secs: int = 0
    total_capacity: float = 0.0
    exercise_count: int = 0


@dataclass
class Workout:
    id: int
    training_id: int
    title: str
    workout_type: str  # Strength, Cardio, etc.
    start_timestamp: int
    end_timestamp: int
    duration_secs: int = 0
    calories: int = 0
    volume_kg: float = 0.0
    energy_j: float = 0.0
    mileage: float = 0.0
    device_type: int = 0
    course_id: int = 0
    course_category: str = ""
    course_difficulty: int = 0
    completion_rate: float = 0.0
    exercise_count: int = 0
    uuid: str = ""

    # Populated from detail endpoints
    sets: list[SetData] = field(default_factory=list)
    muscles: list[MuscleDetail] = field(default_factory=list)

    @classmethod
    def from_record(cls, r: dict) -> "Workout":
        return cls(
            id=r.get("id", 0),
            training_id=r.get("trainingId", 0),
            title=r.get("title", ""),
            workout_type=r.get("courseTypeStr", r.get("courseCategoryName", "")),
            start_timestamp=r.get("startTimestamp", 0),
            end_timestamp=r.get("endTimestamp", 0),
            duration_secs=r.get("trainingTime", 0),
            calories=r.get("calorie", 0),
            volume_kg=r.get("totalCapacity", 0.0),
            energy_j=r.get("totalEnergy", 0.0),
            mileage=r.get("mileage", 0.0),
            device_type=r.get("deviceType", 0),
            course_id=r.get("courseId", 0),
            course_category=r.get("courseCategoryName", ""),
            course_difficulty=r.get("courseDifficultyId", 0),
        )


@dataclass
class StrengthEstimate:
    exercise_name: str
    exercise_group_id: int
    training_part_id: int
    rm1_weight: float
    assessment_date: str  # YYYY-MM-DD


@dataclass
class WeeklySummary:
    training_time_secs: int = 0
    total_capacity: float = 0.0
    total_energy: float = 0.0
    calories: int = 0
    ride_mileage: float = 0.0
    workout_count: float = 0.0

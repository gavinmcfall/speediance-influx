"""Speediance cloud API client."""

import logging
import time

import requests

from .models import MuscleDetail, SetData, StrengthEstimate, Workout

logger = logging.getLogger(__name__)

BASE_URLS = {
    "Global": "https://api2.speediance.com/api",
    "EU": "https://euapi.speediance.com/api",
}


class SpeedianceClient:
    """Client for the Speediance cloud API.

    Auth flow discovered via APK reverse engineering (jadx decompilation)
    and the UnofficialSpeedianceWorkoutManager project.
    """

    def __init__(self, email: str, password: str, region: str = "Global"):
        self._email = email
        self._password = password
        self._base = BASE_URLS.get(region, BASE_URLS["Global"])
        self._host = self._base.split("//")[1].split("/")[0]
        self._session = requests.Session()
        self._token: str = ""
        self._user_id: str = ""

    def _headers(self) -> dict:
        h = {
            "Host": self._host,
            "User-Agent": "Dart/3.9 (dart:io)",
            "Content-Type": "application/json",
            "Timestamp": str(int(time.time() * 1000)),
            "Timezone": time.tzname[0] if time.tzname else "GMT",
            "Utc_offset": self._utc_offset(),
            "Versioncode": "40304",
            "Accept-Language": "en",
            "App_type": "SOFTWARE",
        }
        if self._token:
            h["Token"] = self._token
        if self._user_id:
            h["App_user_id"] = self._user_id
        return h

    @staticmethod
    def _utc_offset() -> str:
        if time.localtime().tm_isdst and time.daylight:
            offset = -time.altzone
        else:
            offset = -time.timezone
        sign = "+" if offset >= 0 else "-"
        offset = abs(offset)
        return f"{sign}{offset // 3600:02d}{(offset % 3600) // 60:02d}"

    def login(self) -> bool:
        """Authenticate with email/password. Returns True on success."""
        try:
            # Step 1: Verify identity
            resp = self._session.post(
                f"{self._base}/app/v2/login/verifyIdentity",
                json={"type": 2, "userIdentity": self._email},
                headers=self._headers(),
                timeout=15,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("verifyIdentity failed: %s", data.get("message"))
                return False

            verify = data.get("data", {})
            if not verify.get("isExist"):
                logger.error("Account does not exist: %s", self._email)
                return False
            if not verify.get("hasPwd"):
                logger.error("Account has no password set")
                return False

            # Step 2: Login
            resp = self._session.post(
                f"{self._base}/app/v2/login/byPass",
                json={"userIdentity": self._email, "password": self._password, "type": 2},
                headers=self._headers(),
                timeout=15,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("Login failed: %s", data.get("message"))
                return False

            d = data["data"]
            self._token = d["token"]
            self._user_id = str(d["appUserId"])
            logger.info("Logged in as %s (user %s)", d.get("username"), self._user_id)
            return True

        except Exception:
            logger.exception("Login error")
            return False

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Make an authenticated GET request. Re-authenticates on token expiry."""
        resp = self._session.get(
            f"{self._base}{path}",
            headers=self._headers(),
            params=params,
            timeout=15,
        )
        data = resp.json()

        # Token expired — re-login and retry once
        if data.get("code") == 91:
            logger.info("Token expired, re-authenticating...")
            if self.login():
                resp = self._session.get(
                    f"{self._base}{path}",
                    headers=self._headers(),
                    params=params,
                    timeout=15,
                )
                data = resp.json()

        return data

    def fetch_workouts(self) -> list[Workout]:
        """Fetch all workout records."""
        if not self._token and not self.login():
            return []

        data = self._get("/mobile/v2/report/userTrainingDataRecord")
        if data.get("code") != 0 or not data.get("data"):
            logger.warning("Failed to fetch workouts: %s", data.get("message"))
            return []

        workouts = []
        for r in data["data"]:
            w = Workout.from_record(r)
            workouts.append(w)

        logger.info("Fetched %d workout records", len(workouts))
        return workouts

    def fetch_workout_detail(self, workout: Workout) -> None:
        """Populate a workout's sets and detail from the training info endpoints."""
        # Get training info (uuid, completion rate, exercise count)
        data = self._get(f"/app/trainingInfo/cttTrainingInfo/{workout.training_id}")
        if data.get("code") == 0 and data.get("data"):
            d = data["data"]
            workout.uuid = d.get("uuid", "")
            workout.completion_rate = d.get("completionRate", 0.0)
            workout.exercise_count = d.get("trainingCount", 0)

        # Get set-by-set detail
        data = self._get(f"/app/trainingInfo/cttTrainingInfoDetail/{workout.training_id}")
        if data.get("code") == 0 and isinstance(data.get("data"), list):
            for exercise in data["data"]:
                exercise_name = exercise.get("actionLibraryName", "")
                muscle_group_id = exercise.get("trainingPartId2", 0)
                max_weight = exercise.get("maxWeight", 0.0)
                category_id = exercise.get("categoryId", 0)
                is_custom = exercise.get("isCustom", 0) == 1

                for i, rep in enumerate(exercise.get("finishedReps", [])):
                    workout.sets.append(SetData(
                        exercise_name=exercise_name,
                        muscle_group_id=muscle_group_id,
                        set_index=i + 1,
                        finished_reps=rep.get("finishedCount", 0),
                        target_reps=rep.get("targetCount", 0),
                        capacity=rep.get("capacity", 0.0),
                        max_heart_rate=rep.get("maxHeartRate", 0.0),
                        time_secs=rep.get("time", 0),
                        score=exercise.get("score", 0),
                        force_control_score=exercise.get("forceControlScore", 0),
                        completion_score=exercise.get("completionScore", 0),
                        bilateral_balance_score=exercise.get("bilateralBalanceScore", 0),
                        left_right=rep.get("leftRight", 0),
                        category_id=category_id,
                        is_custom=is_custom,
                        max_weight=max_weight,
                    ))

            logger.debug("Fetched %d sets for workout %s", len(workout.sets), workout.title)

    def fetch_muscle_detail(self) -> list[MuscleDetail]:
        """Fetch current muscle activation detail."""
        data = self._get("/app/userDataStat/trainingMuscleDetail")
        if data.get("code") != 0 or not isinstance(data.get("data"), list):
            return []

        muscles = []
        for group in data["data"]:
            for m in group.get("muscleDetailList", []):
                if not m.get("isTrained"):
                    continue
                muscles.append(MuscleDetail(
                    muscle_group_name=m.get("muscleGroupName", ""),
                    muscle_group_config_id=m.get("muscleGroupConfigId", ""),
                    training_part_id=group.get("trainingPartId2", 0),
                    intensity_level=m.get("intensityLevel", 0),
                    fatigue=m.get("fatigue", 0),
                    min_weight=m.get("minWeight", 0.0),
                    max_weight=m.get("maxWeight", 0.0),
                    training_time_secs=m.get("trainingTime", 0),
                    total_capacity=m.get("totalCapacity", 0.0),
                    exercise_count=m.get("actionLibraryCount", 0),
                ))
        return muscles

    def fetch_1rm_estimates(self) -> list[StrengthEstimate]:
        """Fetch current 1RM strength estimates."""
        data = self._get("/app/strengthAssessmentReport/getPart")
        if data.get("code") != 0 or not data.get("data"):
            return []

        estimates = []
        for p in data["data"].get("partList", []):
            estimates.append(StrengthEstimate(
                exercise_name=p.get("actionLibraryGroupName", ""),
                exercise_group_id=p.get("actionLibraryGroupId", 0),
                training_part_id=p.get("trainingPartId2s", 0),
                rm1_weight=p.get("rm1Weight", 0.0),
                assessment_date=p.get("lastAssessmentDateStr", ""),
            ))
        return estimates

"""Entry point: config load → poll loop for multiple users."""

import logging
import signal
import time

from .config import AppConfig, UserConfig, load_config
from .influx import InfluxWriter
from .speediance import SpeedianceClient

logger = logging.getLogger("speediance-influx")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Received signal %d, shutting down", signum)
    _shutdown = True


def main():
    global _shutdown

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    config = load_config()

    logging.basicConfig(
        level=getattr(logging, config.main.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("Starting speediance-influx")
    logger.info("Users: %s", ", ".join(u.name for u in config.users))
    logger.info("Loop interval: %d minutes", config.main.loop_minutes)
    logger.info(
        "Write options — sets: %s, muscles: %s, 1rm: %s",
        config.main.write_sets,
        config.main.write_muscles,
        config.main.write_1rm,
    )

    writer = InfluxWriter(config.influx, config.main)

    try:
        while not _shutdown:
            for user_config in config.users:
                if _shutdown:
                    break
                try:
                    _poll_user(user_config, writer, config)
                except Exception:
                    logger.exception("Error polling user %s", user_config.name)

            if _shutdown:
                break

            logger.info("Sleeping %d minutes until next poll", config.main.loop_minutes)
            sleep_until = time.time() + config.main.loop_minutes * 60
            while time.time() < sleep_until and not _shutdown:
                time.sleep(1)
    finally:
        writer.close()
        logger.info("Shutdown complete")


def _poll_user(user_config: UserConfig, writer: InfluxWriter, config: AppConfig):
    """Run one poll cycle for a single user."""
    user = user_config.name
    logger.info("[%s] Polling...", user)

    client = SpeedianceClient(user_config.email, user_config.password, user_config.region)

    last_ts = writer.get_last_workout_timestamp(user)
    if last_ts:
        logger.info("[%s] Last recorded workout at %d", user, last_ts)
    else:
        logger.info("[%s] No existing data, fetching all workouts", user)

    workouts = client.fetch_workouts()
    if not workouts:
        logger.info("[%s] No workout records found", user)
        return

    new_workouts = [w for w in workouts if w.end_timestamp > last_ts]
    if not new_workouts:
        logger.info("[%s] All %d workouts already recorded", user, len(workouts))
        return

    logger.info("[%s] Found %d new workouts (of %d total)", user, len(new_workouts), len(workouts))

    written = 0
    for workout in new_workouts:
        try:
            client.fetch_workout_detail(workout)
            writer.write_workout(workout, user)
            written += 1
        except Exception:
            logger.exception("[%s] Failed to write workout: %s", user, workout.title)

    logger.info("[%s] Wrote %d/%d new workouts", user, written, len(new_workouts))

    if config.main.write_muscles:
        try:
            muscles = client.fetch_muscle_detail()
            if muscles:
                ts = max(w.end_timestamp for w in new_workouts)
                writer.write_muscles(muscles, ts, user)
                logger.info("[%s] Wrote %d muscle detail points", user, len(muscles))
        except Exception:
            logger.exception("[%s] Failed to write muscle detail", user)

    if config.main.write_1rm:
        try:
            estimates = client.fetch_1rm_estimates()
            if estimates:
                writer.write_1rm(estimates, user)
                logger.info("[%s] Wrote %d 1RM estimates", user, len(estimates))
        except Exception:
            logger.exception("[%s] Failed to write 1RM estimates", user)


if __name__ == "__main__":
    main()

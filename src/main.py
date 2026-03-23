"""Entry point: config load → poll loop."""

import logging
import signal
import time

from .config import load_config
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
    logger.info("Region: %s", config.speediance.region)
    logger.info("Loop interval: %d minutes", config.main.loop_minutes)
    logger.info(
        "Write options — sets: %s, muscles: %s, 1rm: %s",
        config.main.write_sets,
        config.main.write_muscles,
        config.main.write_1rm,
    )

    client = SpeedianceClient(
        config.speediance.email,
        config.speediance.password,
        config.speediance.region,
    )
    writer = InfluxWriter(config.influx, config.main)

    try:
        while not _shutdown:
            try:
                _poll_once(client, writer, config)
            except Exception:
                logger.exception("Error during poll cycle")

            if _shutdown:
                break

            logger.info("Sleeping %d minutes until next poll", config.main.loop_minutes)
            sleep_until = time.time() + config.main.loop_minutes * 60
            while time.time() < sleep_until and not _shutdown:
                time.sleep(1)
    finally:
        writer.close()
        logger.info("Shutdown complete")


def _poll_once(client: SpeedianceClient, writer: InfluxWriter, config):
    """Run one poll cycle."""
    last_ts = writer.get_last_workout_timestamp()
    if last_ts:
        logger.info("Last recorded workout at %d, checking for new data", last_ts)
    else:
        logger.info("No existing data, fetching all workouts")

    # Fetch workout records
    workouts = client.fetch_workouts()
    if not workouts:
        logger.info("No workout records found")
        return

    # Filter to new workouts only
    new_workouts = [w for w in workouts if w.end_timestamp > last_ts]
    if not new_workouts:
        logger.info("All %d workouts already recorded", len(workouts))
        return

    logger.info("Found %d new workouts (of %d total)", len(new_workouts), len(workouts))

    written = 0
    for workout in new_workouts:
        try:
            # Fetch set-by-set detail
            client.fetch_workout_detail(workout)
            writer.write_workout(workout)
            written += 1
        except Exception:
            logger.exception("Failed to write workout: %s", workout.title)

    logger.info("Wrote %d/%d new workouts", written, len(new_workouts))

    # Write muscle detail (current state snapshot)
    if config.main.write_muscles:
        try:
            muscles = client.fetch_muscle_detail()
            if muscles:
                ts = max(w.end_timestamp for w in new_workouts)
                writer.write_muscles(muscles, ts)
                logger.info("Wrote %d muscle detail points", len(muscles))
        except Exception:
            logger.exception("Failed to write muscle detail")

    # Write 1RM estimates
    if config.main.write_1rm:
        try:
            estimates = client.fetch_1rm_estimates()
            if estimates:
                writer.write_1rm(estimates)
                logger.info("Wrote %d 1RM estimates", len(estimates))
        except Exception:
            logger.exception("Failed to write 1RM estimates")


if __name__ == "__main__":
    main()

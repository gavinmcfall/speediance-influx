"""Manual backfill command for historical Speediance workout data.

Usage:
    python -m src.backfill --since 2026-01-01
    python -m src.backfill --since 2026-01-01 --dry-run

Run inside the container:
    kubectl exec -it -n vitals deploy/speediance-influx -- python -m src.backfill --since 2026-01-01
"""

import argparse
import logging
import sys
from datetime import date, datetime

from .config import load_config
from .influx import InfluxWriter
from .speediance import SpeedianceClient

logger = logging.getLogger("speediance-influx.backfill")


def main():
    parser = argparse.ArgumentParser(description="Backfill Speediance workout data to InfluxDB")
    parser.add_argument("--since", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't write to InfluxDB")
    parser.add_argument("--config", default=None, help="Path to config.toml")
    args = parser.parse_args()

    config = load_config(args.config)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        since_date = datetime.strptime(args.since, "%Y-%m-%d").date()
    except ValueError:
        logger.error("Invalid date format: %s (use YYYY-MM-DD)", args.since)
        sys.exit(1)

    days_back = (date.today() - since_date).days + 1

    logger.info("=" * 60)
    logger.info("Speediance Backfill")
    logger.info("  Since: %s (%d days)", args.since, days_back)
    logger.info("  Users: %s", ", ".join(u.name for u in config.users))
    logger.info("  Dry run: %s", args.dry_run)
    logger.info("=" * 60)

    writer = InfluxWriter(config.influx, config.main) if not args.dry_run else None

    try:
        for user_config in config.users:
            user = user_config.name
            logger.info("[%s] Fetching workouts...", user)

            client = SpeedianceClient(user_config.email, user_config.password, user_config.region)
            workouts = client.fetch_workouts(days=days_back)

            if not workouts:
                logger.info("[%s] No workouts found", user)
                continue

            logger.info("[%s] Found %d workouts", user, len(workouts))
            for w in workouts:
                logger.info("[%s]   %s — %s — %ds — %.0fkg — %d cal",
                            user, w.title, datetime.fromtimestamp(w.start_timestamp).strftime("%Y-%m-%d %H:%M"),
                            w.duration_secs, w.volume_kg, w.calories)

            if args.dry_run:
                logger.info("[%s] DRY RUN — no data written", user)
                continue

            written = 0
            for workout in workouts:
                try:
                    client.fetch_workout_detail(workout)
                    writer.write_workout(workout, user)
                    written += 1
                except Exception:
                    logger.exception("[%s] Failed to write: %s", user, workout.title)

            logger.info("[%s] Wrote %d/%d workouts", user, written, len(workouts))

            if config.main.write_muscles:
                try:
                    muscles = client.fetch_muscle_detail()
                    if muscles:
                        ts = max(w.end_timestamp for w in workouts)
                        writer.write_muscles(muscles, ts, user)
                except Exception:
                    logger.exception("[%s] Failed to write muscles", user)

            if config.main.write_1rm:
                try:
                    estimates = client.fetch_1rm_estimates()
                    if estimates:
                        writer.write_1rm(estimates, user)
                except Exception:
                    logger.exception("[%s] Failed to write 1RM", user)

    finally:
        if writer:
            writer.close()

    logger.info("Done.")


if __name__ == "__main__":
    main()

# speediance-influx

Fetches workout data from the [Speediance](https://speediance.com) cloud API (Gym Monster, Gym Pal, etc.) and writes it to InfluxDB v2.

## What it captures

| InfluxDB Measurement | Data | Source |
|---------------------|------|--------|
| `workout` | Per-session summary: duration, calories, volume (kg), energy (J), mileage, completion rate | `/mobile/v2/report/userTrainingDataRecord` |
| `workout_sets` | Per-set detail: exercise name, reps, capacity, max HR, form scores, weight range | `/app/trainingInfo/cttTrainingInfoDetail/{id}` |
| `workout_muscles` | Muscle group activation: intensity, fatigue, weight range, time, volume per muscle | `/app/userDataStat/trainingMuscleDetail` |
| `strength_1rm` | Estimated 1RM per compound lift (squat, bench, row, OHP) | `/app/strengthAssessmentReport/getPart` |

## Prerequisites

- A Speediance account with completed workouts
- InfluxDB v2 instance with a bucket and API token
- Docker (or Python 3.12+)

## Quick start (Docker)

```bash
# 1. Create config
cp config.toml.template config.toml
# Edit config.toml with your credentials

# 2. Run
docker run -d \
  --name speediance-influx \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  ghcr.io/gavinmcfall/speediance-influx:latest
```

## Quick start (Python)

```bash
pip install -r requirements.txt
cp config.toml.template config.toml
# Edit config.toml
python -m src.main
```

## Configuration

Create a `config.toml` (or set environment variables):

```toml
[speediance]
email = "you@example.com"      # Your Speediance account email
password = "your-password"      # Your Speediance account password
region = "Global"               # "Global" or "EU"

[influx]
url = "http://localhost:8086"
bucket = "health"
org = "my-org"
token = "your-influxdb-token"

[main]
log_level = "INFO"
loop_minutes = 60               # How often to poll for new workouts
write_sets = true               # Write per-set exercise detail
write_muscles = true            # Write muscle activation data
write_1rm = true                # Write 1RM strength estimates
```

### Environment variable overrides

| Variable | Overrides |
|----------|-----------|
| `SPEEDIANCE_EMAIL` | `speediance.email` |
| `SPEEDIANCE_PASSWORD` | `speediance.password` |
| `SPEEDIANCE_REGION` | `speediance.region` |
| `INFLUX_URL` | `influx.url` |
| `INFLUX_BUCKET` | `influx.bucket` |
| `INFLUX_ORG` | `influx.org` |
| `INFLUX_TOKEN` | `influx.token` |
| `LOG_LEVEL` | `main.log_level` |
| `LOOP_MINUTES` | `main.loop_minutes` |
| `WRITE_SETS` | `main.write_sets` |
| `WRITE_MUSCLES` | `main.write_muscles` |
| `WRITE_1RM` | `main.write_1rm` |
| `CONFIG_PATH` | Path to config file (default: `/app/config.toml`) |

## Region selection

| Region | Base URL | Use when |
|--------|----------|----------|
| `Global` | `api2.speediance.com` | Americas, Asia-Pacific, most accounts |
| `EU` | `euapi.speediance.com` | European accounts |

Your region matches where your Speediance account was created. If unsure, try `Global` first.

## How it works

1. Authenticates with the Speediance cloud API using email/password
2. Fetches all workout records via the mobile API endpoint
3. For each new workout (not yet in InfluxDB), fetches set-by-set detail
4. Writes workout summaries, set data, muscle activation, and 1RM estimates to InfluxDB
5. Sleeps for `loop_minutes`, then repeats

Writes are idempotent — InfluxDB overwrites points with the same timestamp and tags, so re-fetching is safe.

## InfluxDB schema

### `workout` (one point per session)

**Tags:** `type` (Strength/Cardio), `title` (workout name)

| Field | Type | Unit |
|-------|------|------|
| `duration_secs` | int | seconds |
| `calories` | int | kcal |
| `volume_kg` | float | kg |
| `energy_j` | float | joules |
| `mileage` | float | km |
| `completion_rate` | float | % |
| `exercise_count` | int | count |
| `training_id` | int | Speediance ID |

**Timestamp:** workout end time

### `workout_sets` (one point per set per exercise)

**Tags:** `workout_title`, `exercise` (exercise name), `workout_type`

| Field | Type | Unit |
|-------|------|------|
| `set_index` | int | 1-based |
| `finished_reps` | int | count |
| `target_reps` | int | count |
| `capacity` | float | kg (volume) |
| `max_heart_rate` | float | bpm |
| `time_secs` | int | seconds |
| `score` | int | 0-20 |
| `force_control_score` | int | 0-5 |
| `completion_score` | int | 0-5 |
| `max_weight` | float | kg/lbs |
| `left_right` | int | 0=both, 1=left, 2=right |
| `training_id` | int | Speediance ID |

**Timestamp:** workout start time

### `workout_muscles` (one point per muscle group)

**Tags:** `muscle_group` (e.g. "Pecs"), `muscle_group_id`

| Field | Type | Unit |
|-------|------|------|
| `intensity_level` | int | 0-3 |
| `fatigue` | int | 0-3 |
| `min_weight` | float | kg/lbs |
| `max_weight` | float | kg/lbs |
| `training_time_secs` | int | seconds |
| `total_capacity` | float | kg |
| `exercise_count` | int | count |

**Timestamp:** most recent workout end time

### `strength_1rm` (one point per exercise)

**Tags:** `exercise` (e.g. "Barbell Bench Press")

| Field | Type | Unit |
|-------|------|------|
| `rm1_weight` | float | kg/lbs |
| `exercise_group_id` | int | Speediance ID |
| `training_part_id` | int | body part ID |

**Timestamp:** assessment date

## Kubernetes deployment

Kubernetes manifests are included in `kubernetes/` for deployment to a home-ops style cluster using Flux CD + bjw-s app-template.

### 1Password setup

Create a `speediance-influx` item in your 1Password vault with:
- `SPEEDIANCE_EMAIL` — your Speediance account email
- `SPEEDIANCE_PASSWORD` — your Speediance account password

The InfluxDB token is pulled from the existing `influxdb` 1Password item.

## Supported devices

Any device that syncs workout data to the Speediance cloud:
- Gym Monster 2 (Works Plus 2.0)
- Gym Monster (original)
- Gym Pal
- Speediance Strap / Strap PRO

## API details

The Speediance cloud API was reverse-engineered from the official Android app (`com.speediance.speediance_mobile`) via APK decompilation. Auth uses a two-step flow:

1. `POST /api/app/v2/login/verifyIdentity` — confirms account exists
2. `POST /api/app/v2/login/byPass` — email/password login, returns session token

All subsequent requests use the token in a `Token` header. Sessions expire after a period of inactivity; the client re-authenticates automatically.

## License

MIT

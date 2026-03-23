"""TOML config loader with environment variable overrides."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

logger = logging.getLogger(__name__)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config.toml")


@dataclass
class SpeedianceConfig:
    email: str = ""
    password: str = ""
    region: str = "Global"  # Global, EU


@dataclass
class InfluxConfig:
    url: str = "http://influxdb.vitals.svc.cluster.local:8086"
    bucket: str = "health"
    org: str = "vitals"
    token: str = ""


@dataclass
class MainConfig:
    log_level: str = "INFO"
    loop_minutes: int = 60
    write_sets: bool = True
    write_muscles: bool = True
    write_1rm: bool = True


@dataclass
class AppConfig:
    speediance: SpeedianceConfig = field(default_factory=SpeedianceConfig)
    influx: InfluxConfig = field(default_factory=InfluxConfig)
    main: MainConfig = field(default_factory=MainConfig)


def load_config(path: str | None = None) -> AppConfig:
    config_path = Path(path or CONFIG_PATH)

    if config_path.exists():
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
        logger.info("Loaded config from %s", config_path)
    else:
        logger.warning("Config file not found at %s, using defaults + env", config_path)
        raw = {}

    sp_raw = raw.get("speediance", {})
    influx_raw = raw.get("influx", {})
    main_raw = raw.get("main", {})

    speediance = SpeedianceConfig(
        email=os.environ.get("SPEEDIANCE_EMAIL", sp_raw.get("email", "")),
        password=os.environ.get("SPEEDIANCE_PASSWORD", sp_raw.get("password", "")),
        region=os.environ.get("SPEEDIANCE_REGION", sp_raw.get("region", "Global")),
    )

    influx = InfluxConfig(
        url=os.environ.get("INFLUX_URL", influx_raw.get("url", "http://influxdb.vitals.svc.cluster.local:8086")),
        bucket=os.environ.get("INFLUX_BUCKET", influx_raw.get("bucket", "health")),
        org=os.environ.get("INFLUX_ORG", influx_raw.get("org", "vitals")),
        token=os.environ.get("INFLUX_TOKEN", influx_raw.get("token", "")),
    )

    main = MainConfig(
        log_level=os.environ.get("LOG_LEVEL", main_raw.get("log_level", "INFO")),
        loop_minutes=int(os.environ.get("LOOP_MINUTES", main_raw.get("loop_minutes", 60))),
        write_sets=_bool(os.environ.get("WRITE_SETS", main_raw.get("write_sets", True))),
        write_muscles=_bool(os.environ.get("WRITE_MUSCLES", main_raw.get("write_muscles", True))),
        write_1rm=_bool(os.environ.get("WRITE_1RM", main_raw.get("write_1rm", True))),
    )

    return AppConfig(speediance=speediance, influx=influx, main=main)


def _bool(val: object) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)

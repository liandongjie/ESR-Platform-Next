from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_DEVELOPMENT_SECRETS = {"dev-only-change-me", "dev-only-change-me-too"}


class BaseConfig:
    APP_ENV = os.getenv("APP_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-me-too")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///esr_dev.sqlite3",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY = {
        "broker_url": os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        "result_backend": os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
        "task_track_started": True,
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        "timezone": "Asia/Shanghai",
        "enable_utc": True,
    }

    SOURCE_RASTER_DIR = Path(os.getenv("ESR_SOURCE_RASTER_DIR", "data/source"))
    RUNTIME_DATA_DIR = Path(os.getenv("ESR_RUNTIME_DATA_DIR", "data/runtime"))
    RESULT_TTL_HOURS = int(os.getenv("ESR_RESULT_TTL_HOURS", "24"))
    MAX_BUFFER_METERS = int(os.getenv("ESR_MAX_BUFFER_METERS", "5000"))
    MAX_ANALYSIS_AREA_KM2 = float(os.getenv("ESR_MAX_ANALYSIS_AREA_KM2", "50"))


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    CELERY = {**BaseConfig.CELERY, "task_always_eager": True, "task_eager_propagates": True}


class ProductionConfig(BaseConfig):
    DEBUG = False
    SECRET_KEY = os.getenv("SECRET_KEY")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL")
    CELERY = {
        **BaseConfig.CELERY,
        "broker_url": os.getenv("CELERY_BROKER_URL"),
        "result_backend": os.getenv("CELERY_RESULT_BACKEND"),
    }


CONFIG_BY_NAME = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def _validate_url(
    key: str,
    value: Any,
    *,
    schemes: set[str],
    require_database: bool = False,
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{key} is required"

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return f"{key} is malformed"

    if parsed.scheme not in schemes:
        return f"{key} uses an unsupported scheme"
    if not hostname:
        return f"{key} must include a host"
    if require_database and not parsed.path.strip("/"):
        return f"{key} must include a database"
    return None


def validate_production_config(config: Mapping[str, Any]) -> None:
    errors: list[str] = []

    for key in ("SECRET_KEY", "JWT_SECRET_KEY"):
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{key} is required")
        elif value in _DEVELOPMENT_SECRETS or value.startswith("replace-with-"):
            errors.append(f"{key} uses a development placeholder")

    url_checks = (
        (
            "DATABASE_URL",
            config.get("SQLALCHEMY_DATABASE_URI"),
            {"postgresql+psycopg"},
            True,
        ),
        ("REDIS_URL", config.get("REDIS_URL"), {"redis", "rediss"}, False),
        (
            "CELERY_BROKER_URL",
            config.get("CELERY", {}).get("broker_url"),
            {"redis", "rediss"},
            False,
        ),
        (
            "CELERY_RESULT_BACKEND",
            config.get("CELERY", {}).get("result_backend"),
            {"redis", "rediss"},
            False,
        ),
    )
    for key, value, schemes, require_database in url_checks:
        error = _validate_url(
            key,
            value,
            schemes=schemes,
            require_database=require_database,
        )
        if error:
            errors.append(error)

    if errors:
        raise ValueError("Invalid production configuration: " + "; ".join(errors))

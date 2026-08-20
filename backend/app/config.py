from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_DEVELOPMENT_SECRETS = {"dev-only-change-me", "dev-only-change-me-too"}


def _environment_flag(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


class BaseConfig:
    APP_ENV = os.getenv("APP_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-me-too")
    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_COOKIE_SAMESITE = "Lax"
    JWT_COOKIE_SECURE = False
    JWT_REFRESH_COOKIE_PATH = "/api/v1/auth"
    REGISTRATION_ENABLED = _environment_flag("ESR_REGISTRATION_ENABLED", True)

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///esr_dev.sqlite3",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DB_POOL_SIZE = int(os.getenv("ESR_DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW = int(os.getenv("ESR_DB_MAX_OVERFLOW", "0"))
    DB_POOL_TIMEOUT_SECONDS = int(os.getenv("ESR_DB_POOL_TIMEOUT_SECONDS", "10"))
    DB_POOL_RECYCLE_SECONDS = int(os.getenv("ESR_DB_POOL_RECYCLE_SECONDS", "1800"))
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_size": DB_POOL_SIZE,
        "max_overflow": DB_MAX_OVERFLOW,
        "pool_timeout": DB_POOL_TIMEOUT_SECONDS,
        "pool_recycle": DB_POOL_RECYCLE_SECONDS,
    }
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
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        "worker_prefetch_multiplier": 1,
        "task_soft_time_limit": int(
            os.getenv("ESR_CELERY_TASK_SOFT_TIME_LIMIT_SECONDS", "300")
        ),
        "task_time_limit": int(
            os.getenv("ESR_CELERY_TASK_TIME_LIMIT_SECONDS", "360")
        ),
        "worker_max_tasks_per_child": int(
            os.getenv("ESR_CELERY_MAX_TASKS_PER_CHILD", "20")
        ),
        "broker_transport_options": {
            "visibility_timeout": int(
                os.getenv("ESR_CELERY_VISIBILITY_TIMEOUT_SECONDS", "420")
            )
        },
        "beat_schedule": {
            "reconcile-pending-risk-dispatches": {
                "task": "app.tasks.maintenance.reconcile_pending_dispatches",
                "schedule": int(
                    os.getenv("ESR_DISPATCH_RECONCILE_INTERVAL_SECONDS", "30")
                ),
            },
            "cleanup-expired-risk-results": {
                "task": "app.tasks.maintenance.cleanup_expired_results",
                "schedule": int(
                    os.getenv("ESR_RESULT_CLEANUP_INTERVAL_SECONDS", "300")
                ),
            },
        },
    }

    SOURCE_RASTER_DIR = Path(os.getenv("ESR_SOURCE_RASTER_DIR", "data/source"))
    RUNTIME_DATA_DIR = Path(os.getenv("ESR_RUNTIME_DATA_DIR", "data/runtime"))
    RESULT_TTL_HOURS = int(os.getenv("ESR_RESULT_TTL_HOURS", "24"))
    MAX_BUFFER_METERS = int(os.getenv("ESR_MAX_BUFFER_METERS", "5000"))
    MAX_ANALYSIS_AREA_KM2 = float(os.getenv("ESR_MAX_ANALYSIS_AREA_KM2", "50"))
    MAX_ACTIVE_JOBS_PER_USER = int(os.getenv("ESR_MAX_ACTIVE_JOBS_PER_USER", "3"))
    SUBMISSION_RATE_LIMIT_PER_MINUTE = int(
        os.getenv("ESR_SUBMISSION_RATE_LIMIT_PER_MINUTE", "10")
    )
    CELERY_TASK_SOFT_TIME_LIMIT_SECONDS = int(
        os.getenv("ESR_CELERY_TASK_SOFT_TIME_LIMIT_SECONDS", "300")
    )
    CELERY_TASK_TIME_LIMIT_SECONDS = int(
        os.getenv("ESR_CELERY_TASK_TIME_LIMIT_SECONDS", "360")
    )
    CELERY_MAX_TASKS_PER_CHILD = int(
        os.getenv("ESR_CELERY_MAX_TASKS_PER_CHILD", "20")
    )
    CELERY_VISIBILITY_TIMEOUT_SECONDS = int(
        os.getenv("ESR_CELERY_VISIBILITY_TIMEOUT_SECONDS", "420")
    )
    DISPATCH_RECONCILE_INTERVAL_SECONDS = int(
        os.getenv("ESR_DISPATCH_RECONCILE_INTERVAL_SECONDS", "30")
    )
    RESULT_CLEANUP_INTERVAL_SECONDS = int(
        os.getenv("ESR_RESULT_CLEANUP_INTERVAL_SECONDS", "300")
    )


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestingConfig(BaseConfig):
    TESTING = True
    JWT_SECRET_KEY = "testing-only-jwt-secret-at-least-32-bytes"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    # SQLite 内存库由测试进程共享单连接，不套用生产 QueuePool 容量参数。
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    CELERY = {**BaseConfig.CELERY, "task_always_eager": True, "task_eager_propagates": True}
    JWT_COOKIE_CSRF_PROTECT = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    SECRET_KEY = os.getenv("SECRET_KEY")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL")
    JWT_COOKIE_SECURE = True
    REGISTRATION_ENABLED = _environment_flag("ESR_REGISTRATION_ENABLED", False)
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

    positive_limits = (
        "MAX_ACTIVE_JOBS_PER_USER",
        "SUBMISSION_RATE_LIMIT_PER_MINUTE",
        "CELERY_TASK_SOFT_TIME_LIMIT_SECONDS",
        "CELERY_TASK_TIME_LIMIT_SECONDS",
        "CELERY_MAX_TASKS_PER_CHILD",
        "CELERY_VISIBILITY_TIMEOUT_SECONDS",
        "DISPATCH_RECONCILE_INTERVAL_SECONDS",
        "RESULT_CLEANUP_INTERVAL_SECONDS",
    )
    for key in positive_limits:
        if not isinstance(config.get(key), int) or config[key] <= 0:
            errors.append(f"{key} must be a positive integer")
    for key in ("DB_POOL_SIZE", "DB_POOL_TIMEOUT_SECONDS", "DB_POOL_RECYCLE_SECONDS"):
        if not isinstance(config.get(key), int) or config[key] <= 0:
            errors.append(f"{key} must be a positive integer")
    max_overflow = config.get("DB_MAX_OVERFLOW")
    if not isinstance(max_overflow, int) or max_overflow < 0:
        errors.append("DB_MAX_OVERFLOW must be a non-negative integer")
    pool_size = config.get("DB_POOL_SIZE")
    if (
        isinstance(pool_size, int)
        and pool_size > 0
        and isinstance(max_overflow, int)
        and max_overflow >= 0
        and pool_size + max_overflow > 10
    ):
        errors.append(
            "DB_POOL_SIZE + DB_MAX_OVERFLOW must not exceed the "
            "single-host per-process budget of 10"
        )
    hard_limit = config.get("CELERY_TASK_TIME_LIMIT_SECONDS")
    soft_limit = config.get("CELERY_TASK_SOFT_TIME_LIMIT_SECONDS")
    visibility_timeout = config.get("CELERY_VISIBILITY_TIMEOUT_SECONDS")
    if isinstance(hard_limit, int) and isinstance(soft_limit, int) and hard_limit <= soft_limit:
        errors.append(
            "CELERY_TASK_TIME_LIMIT_SECONDS must exceed "
            "CELERY_TASK_SOFT_TIME_LIMIT_SECONDS"
        )
    if (
        isinstance(visibility_timeout, int)
        and isinstance(hard_limit, int)
        and visibility_timeout <= hard_limit
    ):
        errors.append(
            "CELERY_VISIBILITY_TIMEOUT_SECONDS must exceed "
            "CELERY_TASK_TIME_LIMIT_SECONDS"
        )

    if errors:
        raise ValueError("Invalid production configuration: " + "; ".join(errors))

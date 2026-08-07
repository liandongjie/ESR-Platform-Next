from __future__ import annotations

import os
from pathlib import Path


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


CONFIG_BY_NAME = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}

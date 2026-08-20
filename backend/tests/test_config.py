import pytest

from app import create_app
from app.config import DevelopmentConfig, ProductionConfig, TestingConfig


@pytest.fixture()
def valid_production_config(tmp_path, monkeypatch):
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "production-secret")
    monkeypatch.setattr(ProductionConfig, "JWT_SECRET_KEY", "production-jwt-secret")
    monkeypatch.setattr(
        ProductionConfig,
        "SQLALCHEMY_DATABASE_URI",
        "postgresql+psycopg://esr:password@unreachable.invalid:5432/esr_platform",
    )
    monkeypatch.setattr(ProductionConfig, "REDIS_URL", "redis://unreachable.invalid:6379/0")
    monkeypatch.setattr(
        ProductionConfig,
        "CELERY",
        {
            **ProductionConfig.CELERY,
            "broker_url": "redis://unreachable.invalid:6379/0",
            "result_backend": "redis://unreachable.invalid:6379/1",
        },
    )
    monkeypatch.setattr(ProductionConfig, "SOURCE_RASTER_DIR", tmp_path / "source")
    monkeypatch.setattr(ProductionConfig, "RUNTIME_DATA_DIR", tmp_path / "runtime")


def test_valid_production_config_creates_app_without_connecting(valid_production_config):
    app = create_app("production")

    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://")
    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"] == {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 0,
        "pool_timeout": 10,
        "pool_recycle": 1800,
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("SECRET_KEY", None),
        ("JWT_SECRET_KEY", ""),
        ("SECRET_KEY", "dev-only-change-me"),
        ("JWT_SECRET_KEY", "replace-with-another-long-random-production-secret"),
    ],
)
def test_production_rejects_missing_or_placeholder_secrets(
    valid_production_config, monkeypatch, key, value
):
    monkeypatch.setattr(ProductionConfig, key, value)

    with pytest.raises(ValueError, match=key) as error:
        create_app("production")

    if value:
        assert value not in str(error.value)


@pytest.mark.parametrize(
    "database_url",
    [
        None,
        "sqlite:///esr_dev.sqlite3",
        "postgresql+psycopg://localhost",
        "postgresql+psycopg://:5432/esr_platform",
        "postgresql+psycopg://localhost:not-a-port/esr_platform",
        "not a url",
    ],
)
def test_production_rejects_invalid_database_url(
    valid_production_config, monkeypatch, database_url
):
    monkeypatch.setattr(ProductionConfig, "SQLALCHEMY_DATABASE_URI", database_url)

    with pytest.raises(ValueError, match="DATABASE_URL") as error:
        create_app("production")

    if database_url:
        assert database_url not in str(error.value)


@pytest.mark.parametrize(
    ("key", "url"),
    [
        ("REDIS_URL", None),
        ("CELERY_BROKER_URL", ""),
        ("REDIS_URL", "http://redis:6379/0"),
        ("CELERY_BROKER_URL", "redis:///0"),
        ("CELERY_RESULT_BACKEND", "redis://redis:not-a-port/1"),
    ],
)
def test_production_rejects_invalid_redis_urls(valid_production_config, monkeypatch, key, url):
    if key == "REDIS_URL":
        monkeypatch.setattr(ProductionConfig, key, url)
    else:
        celery_key = "broker_url" if key == "CELERY_BROKER_URL" else "result_backend"
        monkeypatch.setattr(
            ProductionConfig,
            "CELERY",
            {**ProductionConfig.CELERY, celery_key: url},
        )

    with pytest.raises(ValueError, match=key) as error:
        create_app("production")

    if url:
        assert url not in str(error.value)


@pytest.mark.parametrize(
    ("config_class", "config_name"),
    [(DevelopmentConfig, "development"), (TestingConfig, "testing")],
)
def test_non_production_config_keeps_sqlite_defaults(
    tmp_path, monkeypatch, config_class, config_name
):
    monkeypatch.setattr(config_class, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(
        config_class, "SQLALCHEMY_ENGINE_OPTIONS", {"pool_pre_ping": True}
    )
    monkeypatch.setattr(config_class, "RUNTIME_DATA_DIR", tmp_path / config_name)

    app = create_app(config_name)

    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"


def test_testing_sqlite_does_not_receive_queue_pool_capacity_options(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", "sqlite:///:memory:")
    monkeypatch.setattr(TestingConfig, "RUNTIME_DATA_DIR", tmp_path / "testing-pool")

    app = create_app("testing")

    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"] == {"pool_pre_ping": True}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("DB_POOL_SIZE", 0),
        ("DB_MAX_OVERFLOW", -1),
        ("DB_POOL_TIMEOUT_SECONDS", 0),
        ("DB_POOL_RECYCLE_SECONDS", 0),
    ],
)
def test_production_rejects_invalid_database_pool_limits(
    valid_production_config, monkeypatch, key, value
):
    monkeypatch.setattr(ProductionConfig, key, value)

    with pytest.raises(ValueError, match=key):
        create_app("production")


def test_production_rejects_pool_capacity_above_single_host_budget(
    valid_production_config, monkeypatch
):
    monkeypatch.setattr(ProductionConfig, "DB_POOL_SIZE", 6)
    monkeypatch.setattr(ProductionConfig, "DB_MAX_OVERFLOW", 5)

    with pytest.raises(ValueError, match="per-process budget of 10"):
        create_app("production")


def test_production_rejects_visibility_timeout_not_above_hard_limit(
    valid_production_config, monkeypatch
):
    monkeypatch.setattr(
        ProductionConfig, "CELERY_VISIBILITY_TIMEOUT_SECONDS", 360
    )
    monkeypatch.setattr(ProductionConfig, "CELERY_TASK_TIME_LIMIT_SECONDS", 360)

    with pytest.raises(ValueError, match="CELERY_VISIBILITY_TIMEOUT_SECONDS"):
        create_app("production")

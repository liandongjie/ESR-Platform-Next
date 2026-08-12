from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from app.extensions import create_redis_client, db
from app.gis.indicators import INDICATORS

health_bp = Blueprint("health", __name__)


@health_bp.get("/live")
def live():
    return jsonify(
        {
            "status": "ok",
            "service": "esr-platform-backend",
            "environment": current_app.config["APP_ENV"],
        }
    )


@health_bp.get("/ready")
def ready():
    checks: dict[str, dict] = {}

    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception:  # readiness converts temporary dependency failures to 503
        checks["database"] = {"status": "unavailable", "reason": "connection_failed"}

    checks["redis"] = _check_redis_endpoints()
    checks["source_rasters"] = _check_source_rasters(
        Path(current_app.config["SOURCE_RASTER_DIR"])
    )
    checks["runtime_data"] = _check_runtime_directory(
        Path(current_app.config["RUNTIME_DATA_DIR"])
    )

    is_ready = all(check["status"] == "ok" for check in checks.values())
    status_code = 200 if is_ready else 503
    return jsonify({"status": "ready" if is_ready else "not_ready", "checks": checks}), status_code


def _check_redis_endpoints() -> dict:
    celery_config = current_app.config["CELERY"]
    configured_endpoints = (
        ("redis", current_app.config["REDIS_URL"]),
        ("celery_broker", celery_config["broker_url"]),
        ("celery_result_backend", celery_config["result_backend"]),
    )
    endpoints: dict[str, list[str]] = {}
    for role, url in configured_endpoints:
        endpoints.setdefault(url, []).append(role)

    results: list[dict] = []
    for url, roles in endpoints.items():
        redis_client = None
        try:
            redis_client = create_redis_client(url)
            endpoint_status = "ok" if redis_client.ping() else "unavailable"
        except Exception:  # readiness must not expose endpoint or raw exception details
            endpoint_status = "unavailable"
        finally:
            if redis_client is not None:
                with suppress(Exception):
                    redis_client.close()

        result = {"roles": roles, "status": endpoint_status}
        if endpoint_status != "ok":
            result["reason"] = "connection_failed"
        results.append(result)

    status = "ok" if all(result["status"] == "ok" for result in results) else "unavailable"
    return {"status": status, "endpoints": results}


def _check_source_rasters(source_dir: Path) -> dict:
    if not source_dir.is_dir():
        return {"status": "unavailable", "reason": "source_directory_missing"}

    try:
        with os.scandir(source_dir):
            pass
    except OSError:
        return {"status": "unavailable", "reason": "source_directory_unreadable"}

    missing: list[str] = []
    unreadable: list[str] = []
    for indicator in INDICATORS:
        raster_path = source_dir / indicator.filename
        if not raster_path.is_file():
            missing.append(indicator.filename)
            continue
        try:
            with raster_path.open("rb"):
                pass
        except OSError:
            unreadable.append(indicator.filename)

    if missing:
        return {"status": "unavailable", "reason": "required_rasters_missing", "files": missing}
    if unreadable:
        return {
            "status": "unavailable",
            "reason": "required_rasters_unreadable",
            "files": unreadable,
        }
    return {"status": "ok"}


def _check_runtime_directory(runtime_dir: Path) -> dict:
    if not runtime_dir.is_dir():
        return {"status": "unavailable", "reason": "runtime_directory_missing"}

    try:
        with tempfile.TemporaryFile(
            mode="w+b",
            dir=runtime_dir,
            prefix=".readiness-",
        ) as probe:
            probe.write(b"1")
            probe.flush()
    except OSError:
        return {"status": "unavailable", "reason": "runtime_directory_unwritable"}

    return {"status": "ok"}

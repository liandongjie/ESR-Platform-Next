from __future__ import annotations

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from app.extensions import create_redis_client, db

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
    checks: dict[str, str] = {}

    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as error:  # readiness must report dependency failure
        current_app.logger.warning("Database readiness check failed: %s", error)
        checks["database"] = "unavailable"

    try:
        redis_client = create_redis_client(current_app.config["REDIS_URL"])
        checks["redis"] = "ok" if redis_client.ping() else "unavailable"
    except Exception as error:  # readiness must report dependency failure
        current_app.logger.warning("Redis readiness check failed: %s", error)
        checks["redis"] = "unavailable"

    source_dir = current_app.config["SOURCE_RASTER_DIR"]
    runtime_dir = current_app.config["RUNTIME_DATA_DIR"]
    checks["source_rasters"] = "ok" if source_dir.exists() else "missing"
    checks["runtime_data"] = "ok" if runtime_dir.exists() else "missing"

    is_ready = checks["database"] == "ok" and checks["redis"] == "ok"
    status_code = 200 if is_ready else 503
    return jsonify({"status": "ready" if is_ready else "not_ready", "checks": checks}), status_code

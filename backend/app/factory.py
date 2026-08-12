from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

from app.api.v1 import api_v1
from app.config import CONFIG_BY_NAME, validate_production_config
from app.extensions import celery, cors, db, jwt, migrate


def create_app(config_name: str | None = None) -> Flask:
    resolved_name = config_name or os.getenv("APP_ENV", "development")
    config_class = CONFIG_BY_NAME.get(resolved_name)
    if config_class is None:
        raise ValueError(f"Unsupported APP_ENV: {resolved_name}")

    app = Flask(__name__)
    app.config.from_object(config_class)
    if resolved_name == "production":
        validate_production_config(app.config)

    _configure_logging(app)
    _ensure_runtime_directories(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)

    return app


def _configure_logging(app: Flask) -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app.logger.setLevel(getattr(logging, level_name, logging.INFO))


def _ensure_runtime_directories(app: Flask) -> None:
    runtime_dir = Path(app.config["RUNTIME_DATA_DIR"])
    runtime_dir.mkdir(parents=True, exist_ok=True)


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config.get("CORS_ORIGINS", "*")}},
    )
    # Web 进程也要投递和查询 Celery 任务，因此必须复用与 Worker 相同的 broker/result 配置。
    # 如果只在 celery_app.py 中配置，普通 Flask Web 进程会保留 Celery 的默认连接配置。
    celery.conf.update(app.config["CELERY"])


def _register_blueprints(app: Flask) -> None:
    app.register_blueprint(api_v1, url_prefix="/api/v1")


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_: RequestEntityTooLarge):
        return jsonify({"code": "UPLOAD_TOO_LARGE", "message": "上传请求超过服务端容量限制"}), 413

    @app.errorhandler(404)
    def not_found(_: Exception):
        return jsonify({"code": "NOT_FOUND", "message": "Resource not found"}), 404

    @app.errorhandler(500)
    def internal_error(error: Exception):
        app.logger.exception("Unhandled server error")
        return jsonify({"code": "INTERNAL_ERROR", "message": "Internal server error"}), 500

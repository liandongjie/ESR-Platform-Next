from flask import Blueprint

from app.api.v1.health import health_bp
from app.api.v1.meta import meta_bp

api_v1 = Blueprint("api_v1", __name__)
api_v1.register_blueprint(health_bp, url_prefix="/health")
api_v1.register_blueprint(meta_bp, url_prefix="/meta")

__all__ = ["api_v1"]

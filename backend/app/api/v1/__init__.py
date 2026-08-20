from flask import Blueprint

from app.api.v1.analysis_areas import analysis_areas_bp
from app.api.v1.auth import auth_bp
from app.api.v1.health import health_bp
from app.api.v1.meta import meta_bp
from app.api.v1.risk_analysis import risk_analysis_bp

api_v1 = Blueprint("api_v1", __name__)
api_v1.register_blueprint(analysis_areas_bp, url_prefix="/analysis-areas")
api_v1.register_blueprint(auth_bp, url_prefix="/auth")
api_v1.register_blueprint(health_bp, url_prefix="/health")
api_v1.register_blueprint(meta_bp, url_prefix="/meta")
api_v1.register_blueprint(risk_analysis_bp, url_prefix="/risk-analysis")

__all__ = ["api_v1"]

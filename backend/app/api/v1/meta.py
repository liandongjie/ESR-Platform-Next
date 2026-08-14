from flask import Blueprint, current_app, jsonify

from app.gis.indicators import (
    INDICATOR_CATEGORIES,
    INDICATORS,
    risk_model_contract_payload,
)
from app.schemas.risk_analysis import RiskIndicatorCatalogOutput

meta_bp = Blueprint("meta", __name__)


@meta_bp.get("/capabilities")
def capabilities():
    return jsonify(
        {
            "project": "ESR-Platform-Next",
            "stage": "framework",
            "coordinate_system": "EPSG:4326",
            "result_ttl_hours": current_app.config["RESULT_TTL_HOURS"],
            "limits": {
                "max_buffer_meters": current_app.config["MAX_BUFFER_METERS"],
                "max_analysis_area_km2": current_app.config["MAX_ANALYSIS_AREA_KM2"],
            },
            "implemented": ["health_checks", "configuration_baseline"],
            "planned": [
                "authentication",
                "study_area",
                "poi_analysis",
                "raster_analysis",
                "task_history",
                "exports",
            ],
        }
    )


@meta_bp.get("/risk-indicators")
def risk_indicators():
    catalog = RiskIndicatorCatalogOutput.model_validate(
        {
            "schema_version": 1,
            "model_contract": risk_model_contract_payload(),
            "categories": [
                {"code": code, "name": name, "order": order}
                for order, (code, name) in enumerate(INDICATOR_CATEGORIES)
            ],
            "indicators": [
                {
                    "code": indicator.code,
                    "name": indicator.name,
                    "category": indicator.category,
                    "source_tif": indicator.filename,
                    "normalized_range": {
                        "minimum": indicator.expected_min,
                        "maximum": indicator.expected_max,
                    },
                    "risk_direction": indicator.risk_direction,
                    "risk_semantics": indicator.risk_semantics,
                    "legacy_mvp_default_selected": indicator.default_selected,
                    "legacy_mvp_default_weight_percent": (
                        indicator.default_weight_percent
                    ),
                }
                for indicator in INDICATORS
            ],
        }
    )
    return jsonify(catalog.model_dump(mode="json"))

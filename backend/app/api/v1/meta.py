from flask import Blueprint, current_app, jsonify

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

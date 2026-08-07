from __future__ import annotations

from typing import Any

from pydantic import Field, FiniteFloat

from app.schemas.common import ApiModel


class RiskIndicatorWeightInput(ApiModel):
    """JSON-safe weight item accepted at the asynchronous job boundary."""

    code: str = Field(min_length=1, max_length=64)
    weight_percent: FiniteFloat = Field(ge=0.0, le=100.0)


class RiskAnalysisJobRequest(ApiModel):
    """Serializable request passed from the API process to a Celery worker.

    Geometry stays as GeoJSON at the transport boundary. The worker converts it to
    Shapely only after deserialization, which keeps the Celery message JSON-only and
    avoids sending Python/GDAL objects through Redis.
    """

    geometry: dict[str, Any]
    weights: list[RiskIndicatorWeightInput] = Field(min_length=1, max_length=12)

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import floor, isfinite

from pyproj import CRS, Transformer
from shapely.errors import ShapelyError
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

_WGS84 = CRS.from_epsg(4326)
_SUPPORTED_GEOMETRY_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
}
_UTM_MIN_LATITUDE = -80.0
_UTM_MAX_LATITUDE = 84.0


class AnalysisAreaValidationError(ValueError):
    """研究区或缓冲区参数不满足当前空间分析约束。"""


@dataclass(frozen=True, slots=True)
class MetricBufferResult:
    """米制缓冲区结果及其空间元数据。"""

    source_geometry: BaseGeometry
    buffer_geometry: BaseGeometry
    distance_m: float
    working_crs: CRS
    area_m2: float


def normalize_boundaries(boundaries: list[list[tuple[float, float]]]) -> BaseGeometry:
    """把 Provider 返回的全部 WGS84 填充区面 dissolve 为一个面 geometry。"""

    if not boundaries:
        raise AnalysisAreaValidationError("boundaries 至少需要一个 boundary")

    polygons: list[Polygon] = []
    for index, boundary in enumerate(boundaries):
        if len(boundary) < 4:
            raise AnalysisAreaValidationError(
                f"boundary[{index}] 至少需要三个不同顶点并闭合"
            )

        coordinates: list[tuple[float, float]] = []
        for coordinate in boundary:
            if len(coordinate) != 2:
                raise AnalysisAreaValidationError(f"boundary[{index}] 坐标必须包含经度和纬度")
            longitude, latitude = (float(value) for value in coordinate)
            if not isfinite(longitude) or not isfinite(latitude):
                raise AnalysisAreaValidationError(f"boundary[{index}] 坐标必须是有限数值")
            if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise AnalysisAreaValidationError(f"boundary[{index}] 坐标超出 WGS84 经纬度范围")
            coordinates.append((longitude, latitude))

        if coordinates[0] != coordinates[-1]:
            raise AnalysisAreaValidationError(f"boundary[{index}] 必须闭合")
        if len(set(coordinates[:-1])) < 3:
            raise AnalysisAreaValidationError(f"boundary[{index}] 至少需要三个不同顶点")

        polygon = Polygon(coordinates)
        if polygon.is_empty or not polygon.is_valid:
            raise AnalysisAreaValidationError(f"boundary[{index}] 不是有效 Polygon")
        polygons.append(polygon)

    return dissolve_polygon_geometries(polygons, error_subject="boundaries")


def dissolve_polygon_geometries(
    geometries: Sequence[BaseGeometry],
    *,
    error_subject: str = "polygon",
) -> BaseGeometry:
    """把有效 Polygon/MultiPolygon dissolve 为单个面 geometry。"""

    if not geometries:
        raise AnalysisAreaValidationError(f"{error_subject} geometries 不能为空")
    if any(
        geometry.is_empty
        or not geometry.is_valid
        or geometry.geom_type not in {"Polygon", "MultiPolygon"}
        for geometry in geometries
    ):
        raise AnalysisAreaValidationError(
            f"{error_subject} dissolve 输入必须是有效 Polygon 或 MultiPolygon"
        )

    try:
        geometry = unary_union(geometries)
    except ShapelyError as exc:
        raise AnalysisAreaValidationError(f"{error_subject} dissolve 失败") from exc

    if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in {
        "Polygon",
        "MultiPolygon",
    }:
        raise AnalysisAreaValidationError(
            f"{error_subject} dissolve 结果必须是有效 Polygon 或 MultiPolygon"
        )
    return geometry


def create_metric_buffer(geometry: BaseGeometry, distance_m: float) -> MetricBufferResult:
    """在局部 UTM 投影中按米生成缓冲区，再转换回 WGS84。

    不能直接对 EPSG:4326 经纬度调用 ``buffer(distance_m)``：4326 的坐标单位
    是角度而不是米。这里先根据研究区位置选择局部 UTM，再执行米制 buffer，
    从源头避免把“3000 米”错误解释成“3000 度”。
    """

    validate_wgs84_source_geometry(geometry)
    _validate_distance(distance_m)

    working_crs = local_utm_crs(geometry)
    to_metric = Transformer.from_crs(_WGS84, working_crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(working_crs, _WGS84, always_xy=True)

    metric_geometry = shapely_transform(to_metric.transform, geometry)
    metric_buffer = metric_geometry.buffer(float(distance_m))
    if metric_buffer.is_empty or not metric_buffer.is_valid:
        raise AnalysisAreaValidationError("缓冲区计算结果为空或无效")

    buffer_geometry = shapely_transform(to_wgs84.transform, metric_buffer)
    if buffer_geometry.is_empty or not buffer_geometry.is_valid:
        raise AnalysisAreaValidationError("缓冲区转换回 WGS84 后为空或无效")

    return MetricBufferResult(
        source_geometry=geometry,
        buffer_geometry=buffer_geometry,
        distance_m=float(distance_m),
        working_crs=working_crs,
        area_m2=float(metric_buffer.area),
    )


def local_utm_crs(geometry: BaseGeometry) -> CRS:
    """根据研究区中心选择局部 UTM CRS；南京区域会得到 EPSG:32650。"""

    point = geometry.representative_point()
    longitude = float(point.x)
    latitude = float(point.y)

    if not _UTM_MIN_LATITUDE <= latitude <= _UTM_MAX_LATITUDE:
        raise AnalysisAreaValidationError("当前缓冲区实现仅支持 UTM 有效纬度范围 -80°~84°")

    zone = floor((longitude + 180.0) / 6.0) + 1
    zone = min(60, max(1, zone))
    epsg = 32600 + zone if latitude >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def metric_area_m2(geometry: BaseGeometry) -> float:
    """Calculate polygon area in a local metric CRS instead of square degrees."""

    validate_wgs84_source_geometry(geometry)
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise AnalysisAreaValidationError("研究区 geometry 必须是 Polygon 或 MultiPolygon")
    transformer = Transformer.from_crs(_WGS84, local_utm_crs(geometry), always_xy=True)
    return float(shapely_transform(transformer.transform, geometry).area)


def validate_wgs84_source_geometry(geometry: BaseGeometry) -> None:
    """校验当前 SourceGeometry 公共约定：有效 geometry 且坐标为 WGS84。"""

    if geometry.is_empty:
        raise AnalysisAreaValidationError("研究区 geometry 不能为空")
    if geometry.geom_type not in _SUPPORTED_GEOMETRY_TYPES:
        raise AnalysisAreaValidationError(
            f"暂不支持 {geometry.geom_type}，请使用点、线、面或对应 MultiGeometry"
        )
    if not geometry.is_valid:
        raise AnalysisAreaValidationError("研究区 geometry 无效，请先修复自相交等拓扑问题")
    _validate_wgs84_bounds(geometry)


def _validate_distance(distance_m: float) -> None:
    if not isfinite(distance_m) or distance_m <= 0:
        raise AnalysisAreaValidationError("缓冲距离必须是大于 0 的有限米制数值")


def _validate_wgs84_bounds(geometry: BaseGeometry) -> None:
    min_x, min_y, max_x, max_y = (float(value) for value in geometry.bounds)
    if min_x < -180 or max_x > 180 or min_y < -90 or max_y > 90:
        raise AnalysisAreaValidationError(
            "研究区坐标超出 WGS84 经纬度范围；后端接口约定输入 CRS 为 EPSG:4326"
        )

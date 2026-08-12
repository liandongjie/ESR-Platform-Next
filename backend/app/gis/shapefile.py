from __future__ import annotations

import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile, ZipInfo

import geopandas as gpd
import shapely
from pyogrio.errors import DataSourceError
from pyproj import CRS
from pyproj.exceptions import CRSError, ProjError
from shapely.geometry.base import BaseGeometry

from app.gis.analysis_area import (
    AnalysisAreaValidationError,
    dissolve_polygon_geometries,
    validate_wgs84_source_geometry,
)

MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_ZIP_MEMBERS = 16
MAX_COMPRESSION_RATIO = 100
MAX_FEATURES = 1_000
MAX_COORDINATES = 50_000
_CHUNK_SIZE = 64 * 1024
_REQUIRED_EXTENSIONS = {".shp", ".shx", ".dbf", ".prj"}
_ALLOWED_EXTENSIONS = _REQUIRED_EXTENSIONS | {".cpg"}
_WGS84 = CRS.from_epsg(4326)


class ShapefileImportError(ValueError):
    """ZIP 或 Shapefile 不满足首版导入 Contract。"""


class ShapefileCapacityError(ShapefileImportError):
    """上传或展开字节容量超过安全上限。"""


@dataclass(frozen=True, slots=True)
class ShapefileImportResult:
    geometry: BaseGeometry
    source_crs: str
    feature_count: int
    coordinate_count: int


def import_shapefile_zip(stream: BinaryIO) -> ShapefileImportResult:
    """安全解压唯一 Shapefile dataset，并返回 WGS84 SourceGeometry。"""

    with TemporaryDirectory(prefix="esr-shapefile-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        archive_path = temporary_path / "upload.zip"
        _copy_with_limit(stream, archive_path, MAX_ARCHIVE_BYTES, "ZIP 文件超过 10 MiB")
        dataset_path = _extract_dataset(archive_path, temporary_path / "dataset")
        return _read_dataset(dataset_path)


def _copy_with_limit(
    source: BinaryIO,
    destination: Path,
    limit: int,
    message: str,
) -> int:
    copied = 0
    with destination.open("wb") as output:
        while chunk := source.read(_CHUNK_SIZE):
            copied += len(chunk)
            if copied > limit:
                raise ShapefileCapacityError(message)
            output.write(chunk)
    return copied


def _extract_dataset(archive_path: Path, destination: Path) -> Path:
    destination.mkdir()
    try:
        with ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise ShapefileImportError(f"ZIP 成员不能超过 {MAX_ZIP_MEMBERS} 个")

            files = _validate_members(members)
            total_written = 0
            for extension, member in files.items():
                output_path = destination / f"dataset{extension}"
                try:
                    with archive.open(member) as source:
                        written = _copy_with_limit(
                            source,
                            output_path,
                            MAX_EXPANDED_BYTES,
                            "ZIP 单个成员展开后超过 50 MiB",
                        )
                except (BadZipFile, RuntimeError, NotImplementedError) as exc:
                    raise ShapefileImportError("ZIP 成员损坏或压缩方式不受支持") from exc
                total_written += written
                if total_written > MAX_EXPANDED_BYTES:
                    raise ShapefileCapacityError("ZIP 展开总量超过 50 MiB")
    except BadZipFile as exc:
        raise ShapefileImportError("上传文件不是有效 ZIP") from exc

    return destination / "dataset.shp"


def _validate_members(members: Sequence[ZipInfo]) -> dict[str, ZipInfo]:
    seen_paths: set[str] = set()
    files: dict[str, ZipInfo] = {}
    dataset_parent: str | None = None
    dataset_stem: str | None = None
    declared_total = 0

    for member in members:
        name = member.filename
        if not name or "\x00" in name or "\\" in name:
            raise ShapefileImportError("ZIP 包含非法成员路径")

        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ShapefileImportError("ZIP 包含非法成员路径")
        if ":" in path.parts[0]:
            raise ShapefileImportError("ZIP 包含非法成员路径")

        path_key = path.as_posix().casefold()
        if path_key in seen_paths:
            raise ShapefileImportError("ZIP 包含重复或大小写冲突路径")
        seen_paths.add(path_key)

        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ShapefileImportError("ZIP 不允许 symlink 成员")
        if member.flag_bits & 0x1:
            raise ShapefileImportError("ZIP 不允许加密成员")
        if member.is_dir():
            continue

        extension = path.suffix.casefold()
        if extension not in _ALLOWED_EXTENSIONS:
            # 无关普通文件不参与 dataset 识别，也不会被解压；成员级安全检查仍已执行。
            continue
        if len(path.parts) > 2:
            raise ShapefileImportError("Shapefile sidecar 仅允许根目录或一层共同父目录")

        parent = path.parent.as_posix().casefold()
        stem = path.stem.casefold()
        if dataset_parent is None:
            dataset_parent, dataset_stem = parent, stem
        elif parent != dataset_parent or stem != dataset_stem:
            raise ShapefileImportError("ZIP 必须且只能包含一个同 stem Shapefile dataset")
        if extension in files:
            raise ShapefileImportError(f"ZIP 包含重复 {extension} sidecar")
        files[extension] = member

        declared_total += member.file_size
        if member.file_size > MAX_EXPANDED_BYTES or declared_total > MAX_EXPANDED_BYTES:
            raise ShapefileCapacityError("ZIP 声明的展开字节超过 50 MiB")
        if member.file_size and (
            member.compress_size == 0
            or member.file_size / member.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise ShapefileCapacityError("ZIP 成员压缩比超过 100:1")

    missing = _REQUIRED_EXTENSIONS - files.keys()
    if missing:
        missing_text = "、".join(sorted(missing))
        raise ShapefileImportError(f"Shapefile 缺少必需 sidecar: {missing_text}")
    return files


def _read_dataset(dataset_path: Path) -> ShapefileImportResult:
    try:
        frame = gpd.read_file(
            dataset_path,
            engine="pyogrio",
            columns=[],
            max_features=MAX_FEATURES + 1,
        )
    except (DataSourceError, OSError, ValueError) as exc:
        raise ShapefileImportError("Shapefile 无法读取") from exc

    feature_count = len(frame)
    if feature_count == 0:
        raise ShapefileImportError("Shapefile 不能没有 feature")
    if feature_count > MAX_FEATURES:
        raise ShapefileImportError(f"Shapefile feature 不能超过 {MAX_FEATURES} 个")
    if frame.crs is None:
        raise ShapefileImportError("Shapefile 缺少 CRS，禁止猜测 EPSG:4326")

    geometries = list(frame.geometry)
    if any(geometry is None or geometry.is_empty for geometry in geometries):
        raise ShapefileImportError("Shapefile 包含空 geometry")
    if any(not geometry.is_valid for geometry in geometries):
        raise ShapefileImportError("Shapefile 包含非法 geometry，不执行自动修复")
    if any(
        bool(shapely.has_z(geometry)) or bool(shapely.has_m(geometry))
        for geometry in geometries
    ):
        raise ShapefileImportError("Shapefile 首版仅支持二维 geometry，不允许 Z/M")
    if int(shapely.count_coordinates(geometries)) > MAX_COORDINATES:
        raise ShapefileImportError(f"Shapefile 输入坐标不能超过 {MAX_COORDINATES} 个")

    try:
        source_crs = CRS.from_user_input(frame.crs)
        if not source_crs.equals(_WGS84):
            frame = frame.to_crs(_WGS84)
    except (CRSError, ProjError, ValueError) as exc:
        raise ShapefileImportError("Shapefile CRS 无法解析或转换到 EPSG:4326") from exc

    geometries = list(frame.geometry)
    geometry_types = {geometry.geom_type for geometry in geometries}
    if feature_count == 1 and geometry_types <= {"Point", "LineString"}:
        geometry = geometries[0]
    elif geometry_types <= {"Polygon", "MultiPolygon"}:
        try:
            geometry = dissolve_polygon_geometries(geometries)
        except AnalysisAreaValidationError as exc:
            raise ShapefileImportError(str(exc)) from exc
    else:
        raise ShapefileImportError(
            "首版仅支持单 Point、单 LineString 或 Polygon/MultiPolygon feature"
        )

    try:
        validate_wgs84_source_geometry(geometry)
    except AnalysisAreaValidationError as exc:
        raise ShapefileImportError(str(exc)) from exc

    coordinate_count = int(shapely.get_num_coordinates(geometry))
    if coordinate_count > MAX_COORDINATES:
        raise ShapefileImportError(f"Shapefile 输出坐标不能超过 {MAX_COORDINATES} 个")
    return ShapefileImportResult(
        geometry=geometry,
        source_crs=source_crs.to_string(),
        feature_count=feature_count,
        coordinate_count=coordinate_count,
    )

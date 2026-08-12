from __future__ import annotations

import stat
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import geopandas as gpd
import pytest
from shapely import from_wkt
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from werkzeug.datastructures import MultiDict

import app.gis.shapefile as shapefile_module
from app.gis.shapefile import ShapefileImportError, _validate_members


def _archive_from_geometries(
    tmp_path: Path,
    geometries,
    *,
    crs: str = "EPSG:4326",
    nested: bool = False,
) -> BytesIO:
    dataset_dir = tmp_path / f"dataset-{len(list(tmp_path.iterdir()))}"
    dataset_dir.mkdir()
    dataset_path = dataset_dir / "study.shp"
    gpd.GeoDataFrame(geometry=geometries, crs=crs).to_file(dataset_path, engine="pyogrio")

    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for sidecar in dataset_dir.glob("study.*"):
            name = f"input/{sidecar.name}" if nested else sidecar.name
            output.write(sidecar, name)
    archive.seek(0)
    return archive


def _raw_archive(entries: dict[str, bytes]) -> BytesIO:
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for name, content in entries.items():
            output.writestr(name, content)
    archive.seek(0)
    return archive


def _replace_or_add_archive_entries(archive: BytesIO, entries: dict[str, bytes]) -> BytesIO:
    updated = BytesIO()
    with ZipFile(archive) as source, ZipFile(updated, "w", ZIP_DEFLATED) as output:
        replaced_names = {name.casefold() for name in entries}
        for member in source.infolist():
            if member.filename.casefold() not in replaced_names:
                output.writestr(member, source.read(member))
        for name, content in entries.items():
            output.writestr(name, content)
    updated.seek(0)
    return updated


def _stub_dataset_archive(**extra: bytes) -> BytesIO:
    entries = {
        "study.shp": b"shp",
        "study.shx": b"shx",
        "study.dbf": b"dbf",
        "study.prj": b"prj",
    }
    entries.update(extra)
    return _raw_archive(entries)


def _post_archive(client, archive: BytesIO, filename: str = "study.zip"):
    return client.post(
        "/api/v1/analysis-areas/import-shapefile",
        data={"file": (archive, filename)},
        content_type="multipart/form-data",
    )


@pytest.mark.parametrize(
    ("geometry", "geometry_type"),
    [
        (Point(118.9, 32.1), "Point"),
        (LineString([(118.8, 32.0), (118.9, 32.1)]), "LineString"),
    ],
)
def test_import_accepts_single_point_or_line(client, tmp_path, geometry, geometry_type):
    response = _post_archive(client, _archive_from_geometries(tmp_path, [geometry], nested=True))

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload["crs"] == "EPSG:4326"
    assert payload["source_crs"] == "EPSG:4326"
    assert payload["feature_count"] == 1
    assert payload["geometry"]["type"] == geometry_type


def test_import_explicitly_reprojects_to_wgs84(client, tmp_path):
    archive = _archive_from_geometries(tmp_path, [Point(13235881.0, 3773314.0)], crs="EPSG:3857")

    response = _post_archive(client, archive)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source_crs"] == "EPSG:3857"
    longitude, latitude = payload["geometry"]["coordinates"]
    assert longitude == pytest.approx(118.9, abs=0.1)
    assert latitude == pytest.approx(32.1, abs=0.1)


def test_import_reprojects_polygon_with_hole_and_preserves_hole(client, tmp_path):
    polygon = Polygon(
        [
            (13_230_000, 3_770_000),
            (13_240_000, 3_770_000),
            (13_240_000, 3_780_000),
            (13_230_000, 3_780_000),
            (13_230_000, 3_770_000),
        ],
        [
            [
                (13_233_000, 3_773_000),
                (13_237_000, 3_773_000),
                (13_237_000, 3_777_000),
                (13_233_000, 3_777_000),
                (13_233_000, 3_773_000),
            ]
        ],
    )

    response = _post_archive(
        client,
        _archive_from_geometries(tmp_path, [polygon], crs="EPSG:3857"),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source_crs"] == "EPSG:3857"
    assert payload["geometry"]["type"] == "Polygon"
    assert len(payload["geometry"]["coordinates"]) == 2


def test_import_dissolves_polygon_features_and_preserves_hole(client, tmp_path):
    polygon_with_hole = Polygon(
        [(118.8, 32.0), (118.9, 32.0), (118.9, 32.1), (118.8, 32.1), (118.8, 32.0)],
        [[(118.82, 32.02), (118.84, 32.02), (118.84, 32.04), (118.82, 32.04), (118.82, 32.02)]],
    )
    disjoint = Polygon(
        [(119.0, 32.2), (119.1, 32.2), (119.1, 32.3), (119.0, 32.3), (119.0, 32.2)]
    )

    response = _post_archive(
        client,
        _archive_from_geometries(tmp_path, [polygon_with_hole, disjoint]),
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["feature_count"] == 2
    assert payload["geometry"]["type"] == "MultiPolygon"
    assert any(len(polygon) == 2 for polygon in payload["geometry"]["coordinates"])


@pytest.mark.parametrize(
    ("geometry", "geometry_type"),
    [
        (
            Polygon(
                [(118.8, 32.0), (118.9, 32.0), (118.9, 32.1), (118.8, 32.0)]
            ),
            "Polygon",
        ),
        (
            MultiPolygon(
                [
                    Polygon(
                        [(118.8, 32.0), (118.9, 32.0), (118.9, 32.1), (118.8, 32.0)]
                    ),
                    Polygon(
                        [(119.0, 32.2), (119.1, 32.2), (119.1, 32.3), (119.0, 32.2)]
                    ),
                ]
            ),
            "MultiPolygon",
        ),
    ],
)
def test_import_accepts_single_polygon_or_multipolygon_feature(
    client, tmp_path, geometry, geometry_type
):
    response = _post_archive(client, _archive_from_geometries(tmp_path, [geometry]))

    assert response.status_code == 200
    assert response.get_json()["geometry"]["type"] == geometry_type


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"wrong": (BytesIO(b"zip"), "study.zip")},
        {"file": (BytesIO(b"zip"), "study.zip"), "extra": "value"},
    ],
)
def test_import_requires_exactly_one_file_field(client, data):
    response = client.post(
        "/api/v1/analysis-areas/import-shapefile",
        data=data,
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "INVALID_UPLOAD"


def test_import_rejects_duplicate_file_fields(client):
    data = MultiDict(
        [
            ("file", (BytesIO(b"first"), "first.zip")),
            ("file", (BytesIO(b"second"), "second.zip")),
        ]
    )

    response = client.post(
        "/api/v1/analysis-areas/import-shapefile",
        data=data,
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "INVALID_UPLOAD"


def test_import_rejects_non_zip_filename(client):
    response = _post_archive(client, BytesIO(b"not a zip"), "study.shp")

    assert response.status_code == 415
    assert response.get_json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


@pytest.mark.parametrize(
    "archive",
    [
        BytesIO(b"not a zip"),
        _raw_archive({"study.shp": b"x", "study.shx": b"x", "study.dbf": b"x"}),
        _stub_dataset_archive(**{"other.cpg": b"utf-8"}),
        _raw_archive(
            {
                "../study.shp": b"x",
                "study.shx": b"x",
                "study.dbf": b"x",
                "study.prj": b"x",
            }
        ),
    ],
)
def test_import_maps_invalid_zip_structures_to_422(client, archive):
    archive.seek(0)
    response = _post_archive(client, archive)

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_SHAPEFILE"


def test_import_ignores_unrelated_regular_files(client, tmp_path):
    archive = _archive_from_geometries(tmp_path, [Point(118.9, 32.1)])
    archive = _replace_or_add_archive_entries(
        archive,
        {
            "README.txt": b"metadata",
            "preview.png": b"not extracted",
            "docs/metadata/details.json": b"also ignored",
        },
    )

    response = _post_archive(client, archive)

    assert response.status_code == 200
    assert response.get_json()["geometry"]["type"] == "Point"


def test_import_rejects_second_shapefile_dataset(client):
    archive = _stub_dataset_archive(
        **{
            "other.shp": b"shp",
            "other.shx": b"shx",
            "other.dbf": b"dbf",
            "other.prj": b"prj",
        }
    )

    response = _post_archive(client, archive)

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_SHAPEFILE"


def test_import_rejects_more_than_sixteen_zip_members(client):
    archive = _stub_dataset_archive(
        **{f"folder-{index}/": b"" for index in range(13)}
    )

    response = _post_archive(client, archive)

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_SHAPEFILE"


@pytest.mark.parametrize(
    "geometry",
    [
        MultiPoint([(118.8, 32.0), (118.9, 32.1)]),
        MultiLineString(
            [[(118.8, 32.0), (118.9, 32.1)], [(119.0, 32.2), (119.1, 32.3)]]
        ),
        GeometryCollection([Point(118.9, 32.1)]),
    ],
)
def test_import_rejects_unsupported_geometry_types(client, monkeypatch, geometry):
    monkeypatch.setattr(
        shapefile_module.gpd,
        "read_file",
        lambda *args, **kwargs: gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:4326"),
    )

    response = _post_archive(client, _stub_dataset_archive())

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_SHAPEFILE"


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)]),
        from_wkt("POINT M (118.9 32.1 5)"),
    ],
)
def test_import_rejects_empty_invalid_or_m_geometry(client, monkeypatch, geometry):
    monkeypatch.setattr(
        shapefile_module.gpd,
        "read_file",
        lambda *args, **kwargs: gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:4326"),
    )

    response = _post_archive(client, _stub_dataset_archive())

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_SHAPEFILE"


def test_import_rejects_real_z_shapefile(client, tmp_path):
    archive = _archive_from_geometries(tmp_path, [Point(118.9, 32.1, 5)])

    response = _post_archive(client, archive)

    assert response.status_code == 422
    assert "Z/M" in response.get_json()["message"]


@pytest.mark.parametrize(
    "geometries",
    [
        [Point(118.8, 32.0), Point(118.9, 32.1)],
        [
            LineString([(118.8, 32.0), (118.9, 32.1)]),
            LineString([(119.0, 32.2), (119.1, 32.3)]),
        ],
    ],
)
def test_import_rejects_multiple_point_or_line_features(client, tmp_path, geometries):
    response = _post_archive(client, _archive_from_geometries(tmp_path, geometries))

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_SHAPEFILE"


def test_import_rejects_missing_crs(client, monkeypatch):
    monkeypatch.setattr(
        shapefile_module.gpd,
        "read_file",
        lambda *args, **kwargs: gpd.GeoDataFrame(geometry=[Point(118.9, 32.1)]),
    )

    response = _post_archive(client, _stub_dataset_archive())

    assert response.status_code == 422
    assert "CRS" in response.get_json()["message"]


@pytest.mark.parametrize("prj_content", [b"", b"this is not a coordinate system"])
def test_import_rejects_real_empty_or_invalid_prj(client, tmp_path, prj_content):
    archive = _archive_from_geometries(tmp_path, [Point(118.9, 32.1)])
    archive = _replace_or_add_archive_entries(archive, {"study.prj": prj_content})

    response = _post_archive(client, archive)

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_SHAPEFILE"
    assert "CRS" in response.get_json()["message"] or "无法读取" in response.get_json()["message"]


def test_geometry_complexity_is_422_not_413(client, tmp_path, monkeypatch):
    monkeypatch.setattr(shapefile_module, "MAX_FEATURES", 1)
    polygons = [
        Polygon([(118.8, 32.0), (118.9, 32.0), (118.9, 32.1), (118.8, 32.0)]),
        Polygon([(119.0, 32.2), (119.1, 32.2), (119.1, 32.3), (119.0, 32.2)]),
    ]

    response = _post_archive(client, _archive_from_geometries(tmp_path, polygons))

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_SHAPEFILE"


def test_coordinate_complexity_is_422_not_413(client, tmp_path, monkeypatch):
    monkeypatch.setattr(shapefile_module, "MAX_COORDINATES", 3)
    line = LineString([(118.8, 32.0), (118.9, 32.1), (119.0, 32.2), (119.1, 32.3)])

    response = _post_archive(client, _archive_from_geometries(tmp_path, [line]))

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_SHAPEFILE"


def test_archive_byte_limit_is_413(client, monkeypatch):
    monkeypatch.setattr(shapefile_module, "MAX_ARCHIVE_BYTES", 8)

    response = _post_archive(client, _stub_dataset_archive())

    assert response.status_code == 413
    assert response.get_json()["code"] == "UPLOAD_TOO_LARGE"


def test_expanded_byte_limit_is_413(client, monkeypatch):
    monkeypatch.setattr(shapefile_module, "MAX_EXPANDED_BYTES", 3)

    response = _post_archive(client, _stub_dataset_archive())

    assert response.status_code == 413
    assert response.get_json()["code"] == "UPLOAD_TOO_LARGE"


def test_compression_ratio_limit_is_413(client, monkeypatch):
    monkeypatch.setattr(shapefile_module, "MAX_COMPRESSION_RATIO", 2)
    archive = _stub_dataset_archive(**{"study.shp": b"\x00" * 1_000})

    response = _post_archive(client, archive)

    assert response.status_code == 413
    assert response.get_json()["code"] == "UPLOAD_TOO_LARGE"


def test_global_request_limit_returns_json_413(client, app):
    app.config["MAX_CONTENT_LENGTH"] = 128

    response = _post_archive(client, _stub_dataset_archive())

    assert response.status_code == 413
    assert response.get_json()["code"] == "UPLOAD_TOO_LARGE"


@pytest.mark.parametrize("kind", ["symlink", "encrypted"])
def test_member_validator_rejects_symlink_and_encrypted_members(kind):
    member = ZipInfo("study.shp")
    if kind == "symlink":
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
    else:
        member.flag_bits = 0x1

    with pytest.raises(ShapefileImportError):
        _validate_members([member])


def test_temporary_directory_is_removed_after_success(client, tmp_path, monkeypatch):
    created_paths: list[Path] = []

    def tracked_temporary_directory(*args, **kwargs):
        directory = TemporaryDirectory(*args, **kwargs)
        created_paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(shapefile_module, "TemporaryDirectory", tracked_temporary_directory)

    response = _post_archive(client, _archive_from_geometries(tmp_path, [Point(118.9, 32.1)]))

    assert response.status_code == 200
    assert created_paths and all(not path.exists() for path in created_paths)


def test_temporary_directory_is_removed_after_failure(client, monkeypatch):
    created_paths: list[Path] = []

    def tracked_temporary_directory(*args, **kwargs):
        directory = TemporaryDirectory(*args, **kwargs)
        created_paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(shapefile_module, "TemporaryDirectory", tracked_temporary_directory)

    response = _post_archive(client, BytesIO(b"not a zip"))

    assert response.status_code == 422
    assert created_paths and all(not path.exists() for path in created_paths)

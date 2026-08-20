from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.io import MemoryFile

from app.gis.risk_preview import (
    PNG_SIGNATURE,
    RISK_PREVIEW_ALPHA,
    encode_risk_preview_png,
    raster_bounds,
    risk_preview_rgba,
    write_risk_preview_png,
)
from app.gis.risk_preview_benchmark import load_recorded_baseline


def test_risk_preview_uses_exact_frontend_palette_boundaries_and_transparency():
    values = np.array([[0.0, 0.2, 0.4, 0.6, 0.8, 1.0, np.nan]])

    rgba = risk_preview_rgba(values)

    np.testing.assert_array_equal(
        rgba[0, :, :3],
        np.array(
            [
                [0x44, 0x01, 0x54],
                [0x3B, 0x52, 0x8B],
                [0x21, 0x91, 0x8C],
                [0x5E, 0xC9, 0x62],
                [0xFD, 0xE7, 0x25],
                [0xFD, 0xE7, 0x25],
                [0, 0, 0],
            ],
            dtype=np.uint8,
        ),
    )
    np.testing.assert_array_equal(
        rgba[0, :, 3],
        np.array([RISK_PREVIEW_ALPHA] * 6 + [0], dtype=np.uint8),
    )


def test_preview_png_is_rgba_with_source_dimensions_and_atomic_output(tmp_path: Path):
    values = np.array([[0.1, np.nan, 0.9], [0.3, 0.5, 0.7]], dtype=np.float32)
    output = write_risk_preview_png(values, tmp_path / "preview.png")

    assert output.read_bytes().startswith(PNG_SIGNATURE)
    assert not (tmp_path / ".preview.png.tmp").exists()
    assert list(tmp_path.glob("*.aux.xml")) == []
    with MemoryFile(output.read_bytes()) as memory_file:
        with memory_file.open() as dataset:
            assert (dataset.height, dataset.width, dataset.count) == (2, 3, 4)
            assert dataset.dtypes == ("uint8",) * 4
            np.testing.assert_array_equal(
                np.moveaxis(dataset.read(), 0, -1), risk_preview_rgba(values)
            )


def test_rotated_affine_bounds_use_all_four_grid_corners():
    transform = Affine(0.01, 0.003, 118.0, 0.002, -0.01, 32.0)
    corners = [
        transform * (0, 0),
        transform * (4, 0),
        transform * (4, 3),
        transform * (0, 3),
    ]

    assert raster_bounds(transform, width=4, height=3) == (
        min(point[0] for point in corners),
        min(point[1] for point in corners),
        max(point[0] for point in corners),
        max(point[1] for point in corners),
    )


def test_memory_png_encoder_does_not_need_georeferencing():
    payload = encode_risk_preview_png(np.array([[0.5]], dtype=np.float32))

    with MemoryFile(payload) as memory_file:
        with memory_file.open() as dataset:
            assert dataset.crs is None
            assert dataset.transform == rasterio.Affine.identity()


def test_recorded_large_12_indicator_baseline_provenance_is_consistent():
    baseline = load_recorded_baseline(
        Path(__file__).parents[2]
        / "docs"
        / "performance"
        / "risk-analysis-baseline.json"
    )

    assert baseline["subject_baseline_sha"] == (
        "5810240e14d1d5a86562d73d6b85f2cdd2083cc4"
    )
    assert baseline["transport"] == "flask_test_client_no_network"
    assert baseline["sample_count"] == 5
    assert baseline["valid_pixel_count"] == baseline["polygon_count"] == 16_139
    assert baseline["geojson_bytes"] == 4_966_037
    assert len(str(baseline["source_sha256"])) == 64

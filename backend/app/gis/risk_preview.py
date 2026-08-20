from __future__ import annotations

import struct
import warnings
from pathlib import Path

import numpy as np
from affine import Affine
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

RISK_PREVIEW_PALETTE_VERSION = "risk-viridis-5-v1"
# 与旧 Polygon fillOpacity=0.72 保持同一视觉口径。
RISK_PREVIEW_ALPHA = 184
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_PALETTE = np.array(
    [
        (0x44, 0x01, 0x54),
        (0x3B, 0x52, 0x8B),
        (0x21, 0x91, 0x8C),
        (0x5E, 0xC9, 0x62),
        (0xFD, 0xE7, 0x25),
    ],
    dtype=np.uint8,
)
_BREAKS = np.array((0.2, 0.4, 0.6, 0.8), dtype=np.float64)


def risk_preview_rgba(values: np.ndarray) -> np.ndarray:
    """Map normalized risk cells to the frontend's five-color RGBA palette."""

    array = np.asarray(values)
    if array.ndim != 2:
        raise ValueError("风险预览输入必须是二维数组")

    valid = np.isfinite(array)
    if np.any((array[valid] < 0.0) | (array[valid] > 1.0)):
        raise ValueError("风险预览有效值必须位于 [0,1]")

    rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
    if np.any(valid):
        bins = np.searchsorted(_BREAKS, array[valid], side="right")
        rgba[valid, :3] = _PALETTE[bins]
        rgba[valid, 3] = RISK_PREVIEW_ALPHA
    return rgba


def encode_risk_preview_png(values: np.ndarray) -> bytes:
    """Encode a risk matrix as a small, georeference-free RGBA PNG."""

    rgba = risk_preview_rgba(values)
    height, width = rgba.shape[:2]
    with MemoryFile() as memory_file:
        # 预览的空间定位由 manifest bounds 提供，PNG 不写地理元数据，也不会产生 PAM sidecar。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with memory_file.open(
                driver="PNG",
                width=width,
                height=height,
                count=4,
                dtype="uint8",
            ) as dataset:
                dataset.write(np.moveaxis(rgba, -1, 0))
        payload = memory_file.read()
    if not payload.startswith(PNG_SIGNATURE):
        raise RuntimeError("Rasterio PNG driver 未生成有效 PNG")
    return payload


def write_risk_preview_png(values: np.ndarray, output_path: Path) -> Path:
    """Write a complete PNG before atomically publishing it."""

    output_path = Path(output_path)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary_path.write_bytes(encode_risk_preview_png(values))
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def raster_bounds(transform: Affine, *, width: int, height: int) -> tuple[float, ...]:
    """Return the WGS84 envelope using all four corners of a full Affine transform."""

    corners = (
        transform * (0, 0),
        transform * (width, 0),
        transform * (width, height),
        transform * (0, height),
    )
    xs, ys = zip(*corners, strict=True)
    return (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))


def validate_preview_png(payload: bytes, *, shape: tuple[int, int]) -> None:
    """Validate the fixed PNG signature, IHDR, dimensions, and RGBA contract."""

    if len(payload) < 33 or not payload.startswith(PNG_SIGNATURE):
        raise ValueError("风险预览 PNG 签名无效")
    if payload[8:16] != b"\x00\x00\x00\rIHDR":
        raise ValueError("风险预览 PNG 缺少有效 IHDR")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", payload[16:29]
    )
    expected_height, expected_width = shape
    if (height, width) != (expected_height, expected_width):
        raise ValueError("风险预览 PNG 尺寸与结果清单不一致")
    if (bit_depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
        raise ValueError("风险预览 PNG 必须是 8-bit RGBA")
    try:
        with MemoryFile(payload) as memory_file, warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with memory_file.open() as dataset:
                if dataset.count != 4 or dataset.dtypes != ("uint8",) * 4:
                    raise ValueError("风险预览 PNG 必须是四波段 uint8")
                dataset.read()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("风险预览 PNG 无法完整读取") from exc

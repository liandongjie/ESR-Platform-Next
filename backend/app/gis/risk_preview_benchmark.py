from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio

if __package__:
    from app.gis.risk_preview import (
        RISK_PREVIEW_PALETTE_VERSION,
        encode_risk_preview_png,
    )
else:
    from risk_preview import RISK_PREVIEW_PALETTE_VERSION, encode_risk_preview_png

PREVIEW_OVERLAY_COUNT = 1


def load_recorded_baseline(path: Path) -> dict[str, object]:
    """Load and cross-check the recorded large/12-indicator spatial evidence."""

    source_bytes = path.read_bytes()
    document = json.loads(source_bytes)
    subject_sha = document.get("subject_baseline_sha")
    provenance = document.get("source_provenance", {})
    if not isinstance(subject_sha, str) or provenance.get("subject_baseline_sha") != subject_sha:
        raise ValueError("旧基线 subject SHA 不一致")

    spatial = document.get("spatial", {})
    raw_samples = [
        sample
        for sample in spatial.get("raw_samples", [])
        if sample.get("aoi") == "large" and sample.get("indicator_count") == 12
    ]
    summaries = [
        summary
        for summary in spatial.get("summaries", [])
        if summary.get("aoi") == "large" and summary.get("indicator_count") == 12
    ]
    scenarios = [
        scenario
        for scenario in spatial.get("scenarios", [])
        if scenario.get("aoi") == "large" and scenario.get("indicator_count") == 12
    ]
    if not raw_samples or len(summaries) != 1 or len(scenarios) != 1:
        raise ValueError("旧基线缺少唯一 large/12 指标空间场景")

    summary = summaries[0]
    scenario = scenarios[0]
    if summary.get("sample_count") != len(raw_samples):
        raise ValueError("旧基线 raw sample 数量与 summary 不一致")

    fields = {
        "valid_cells": "valid_cells",
        "feature_count": "feature_count",
        "response_bytes": "response_bytes",
    }
    stable_values: dict[str, int] = {}
    for raw_field, summary_field in fields.items():
        values = [int(sample[raw_field]) for sample in raw_samples]
        metric = (
            summary["valid_cells"]
            if summary_field == "valid_cells"
            else summary["metrics"][summary_field]
        )
        summary_matches = all(
            float(metric[key]) == values[0] for key in ("min", "median", "max")
        )
        if len(set(values)) != 1 or not summary_matches:
            raise ValueError(f"旧基线 {raw_field} raw/summary 不一致")
        stable_values[raw_field] = values[0]

    rows = {int(sample["rows"]) for sample in raw_samples}
    cols = {int(sample["cols"]) for sample in raw_samples}
    transports = {str(sample["transport"]) for sample in raw_samples}
    if (
        len(rows) != 1
        or len(cols) != 1
        or len(transports) != 1
        or scenario.get("output_rows") not in rows
        or scenario.get("output_cols") not in cols
        or int(scenario.get("output_valid_cells", -1)) != stable_values["valid_cells"]
        or stable_values["feature_count"] != stable_values["valid_cells"]
    ):
        raise ValueError("旧基线场景、raw sample 与 summary 空间口径不一致")

    return {
        "source_path": path.as_posix(),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "subject_baseline_sha": subject_sha,
        "transport": transports.pop(),
        "sample_count": len(raw_samples),
        "aoi": "large",
        "indicator_count": 12,
        "rows": rows.pop(),
        "cols": cols.pop(),
        "valid_pixel_count": stable_values["valid_cells"],
        "geojson_bytes": stable_values["response_bytes"],
        "polygon_count": stable_values["feature_count"],
    }


def representative_matrix(baseline: dict[str, object]) -> np.ndarray:
    """Return a deterministic representative grid sized from recorded evidence."""

    rows = int(baseline["rows"])
    cols = int(baseline["cols"])
    valid_count = int(baseline["valid_pixel_count"])
    values = np.full(rows * cols, np.nan, dtype=np.float32)
    values[:valid_count] = np.random.default_rng(20260820).random(
        valid_count, dtype=np.float32
    )
    return values.reshape(rows, cols)


def run_benchmark(*, iterations: int, baseline_path: Path) -> dict[str, object]:
    if iterations < 5:
        raise ValueError("iterations 必须至少为 5")
    baseline = load_recorded_baseline(baseline_path)
    matrix = representative_matrix(baseline)
    for _ in range(3):
        encode_risk_preview_png(matrix)

    timings_ms: list[float] = []
    preview = b""
    for _ in range(iterations):
        started = time.perf_counter_ns()
        preview = encode_risk_preview_png(matrix)
        timings_ms.append((time.perf_counter_ns() - started) / 1_000_000)

    sorted_timings = sorted(timings_ms)
    p95_index = int(np.ceil(0.95 * len(sorted_timings))) - 1
    preview_bytes = len(preview)
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": "server-side deterministic PNG encoding microbenchmark",
        "limitations": {
            "browser_first_display_p95_ms": None,
            "note": "该基准不测量网络、浏览器解码、ImageLayer 首次显示或交互帧率。",
        },
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "rasterio": rasterio.__version__,
            "platform": platform.platform(),
        },
        "input": {
            "shape": list(matrix.shape),
            "valid_pixel_count": int(np.count_nonzero(np.isfinite(matrix))),
            "seed": 20260820,
            "iterations": iterations,
            "warmup_iterations": 3,
        },
        "baseline": baseline,
        "preview": {
            "palette_version": RISK_PREVIEW_PALETTE_VERSION,
            "png_bytes": preview_bytes,
            "overlay_count": PREVIEW_OVERLAY_COUNT,
            "generation_ms": {
                "p50": round(float(np.median(timings_ms)), 3),
                "p95": round(sorted_timings[p95_index], 3),
                "p95_method": "nearest-rank",
                "samples": [round(value, 3) for value in timings_ms],
            },
        },
        "comparison": {
            "payload_compression_ratio": round(
                int(baseline["geojson_bytes"]) / preview_bytes, 3
            ),
            "payload_reduction_percent": round(
                (1 - preview_bytes / int(baseline["geojson_bytes"])) * 100, 3
            ),
            "overlay_reduction_percent": round(
                (1 - PREVIEW_OVERLAY_COUNT / int(baseline["polygon_count"])) * 100,
                3,
            ),
            "method": "recorded_baseline_vs_deterministic_representative_png",
            "indicative": True,
            "controlled_same_artifact_ab": False,
        },
    }


def render_markdown(report: dict[str, object]) -> str:
    baseline = report["baseline"]
    preview = report["preview"]
    comparison = report["comparison"]
    input_data = report["input"]
    assert isinstance(baseline, dict)
    assert isinstance(preview, dict)
    assert isinstance(comparison, dict)
    assert isinstance(input_data, dict)
    generation = preview["generation_ms"]
    assert isinstance(generation, dict)
    return f"""# Risk preview benchmark

本报告由 `scripts/benchmark-risk-preview.ps1` 生成。旧值来自仓库已记录基线，
新值来自按相同 shape/有效像元数构造的确定性代表矩阵。

- 旧基线来源：`{baseline['source_path']}`。
- Subject SHA：`{baseline['subject_baseline_sha']}`。
- 来源文件 SHA256：`{baseline['source_sha256']}`。
- 传输口径：`{baseline['transport']}`，样本数 `{baseline['sample_count']}`。

| 指标 | 旧 GeoJSON | 新 PNG |
|---|---:|---:|
| 有效像元 / Polygon | {input_data['valid_pixel_count']:,} | {input_data['valid_pixel_count']:,} |
| 响应体 | {baseline['geojson_bytes']:,} bytes | {preview['png_bytes']:,} bytes |
| 地图覆盖物 | {baseline['polygon_count']:,} | {preview['overlay_count']} |
| 服务端 PNG 生成 p95 | 不适用 | {generation['p95']} ms |

- 响应体压缩比：{comparison['payload_compression_ratio']}x。
- 指示性响应体减少：{comparison['payload_reduction_percent']}%。
- 地图覆盖物减少：{comparison['overlay_reduction_percent']}%。
- 色带版本：`{preview['palette_version']}`。
- p95 统计口径：`{generation['p95_method']}`（第 `ceil(0.95*n)` 个有序样本）。

> 范围说明：这是服务端确定性 PNG 编码微基准，不是浏览器首次显示 p95；
> 网络、浏览器解码、ImageLayer 首次显示与交互帧率尚未测量。

> 该百分比是“已记录旧基线 vs 确定性代表矩阵 PNG”的跨运行指示性对比，
> 不是同一 artifact 的受控 A/B；最终真实 A/B 留待 Compose 集成环境执行。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=30)
    args = parser.parse_args()

    report = run_benchmark(iterations=args.iterations, baseline_path=args.baseline)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "risk-preview-benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "risk-preview-benchmark.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    print(json.dumps(report["comparison"], ensure_ascii=False))


if __name__ == "__main__":
    main()

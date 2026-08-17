# Risk Analysis Performance Baseline

- Subject production baseline: `5810240e14d1d5a86562d73d6b85f2cdd2083cc4`
- Repository HEAD: `6be91e9af9ea02348ae3f320efc35c03d17f53f4`
- Source-tree verification: `host_git_diff_and_untracked_allowlist_v1`
- Source tree verified: `true`
- Verified invariant: outside the benchmark-only allowlist, the working tree matches the subject production baseline. Repository HEAD may be newer.
- Benchmark elapsed: `64.716s`
- Repetition: warm-up 1 + measured 5 per scenario

## Timing semantics

- `pipeline_elapsed_ms` wraps `pipeline.run()` inside the same service `execute()`.
- `total_service_elapsed_ms` measures that same `execute()` call.
- `validation_elapsed_ms` is `standalone_post_execute_warm_cache`; `included_in_total_service=false`. It is not a decomposition of service time.
- `spatial_elapsed_ms` calls the real Flask route through its test client. It includes response serialization but excludes network transport.

## Compute results

Times are min/median/max milliseconds.

| Indicators | AOI | Rows×Cols | Cells | Valid cells | Pipeline | Validation (standalone) | Total service |
|---:|---|---:|---:|---:|---:|---:|---:|
| 3 | small | 128×128 | 16384 | 16384/16384/16384 | 89.463/109.639/125.741 | 21.402/24.240/27.918 | 91.383/112.626/128.326 |
| 3 | medium | 384×384 | 147456 | 145560/145560/145560 | 37.987/128.597/231.485 | 162.213/165.865/173.446 | 40.319/131.166/234.576 |
| 3 | large | 1024×1024 | 1048576 | 736372/736372/736372 | 134.805/224.864/407.284 | 978.611/1003.000/1021.505 | 140.027/232.497/416.403 |
| 6 | small | 128×128 | 16384 | 16139/16139/16139 | 98.012/115.736/149.281 | 19.082/19.724/28.843 | 103.073/119.319/154.359 |
| 6 | medium | 384×384 | 147456 | 140156/140156/140156 | 315.579/357.844/455.378 | 156.368/159.840/179.603 | 318.163/360.917/461.228 |
| 6 | large | 1024×1024 | 1048576 | 724106/724106/724106 | 416.684/730.632/1325.692 | 966.394/971.162/997.650 | 422.882/736.048/1330.620 |
| 12 | small | 128×128 | 16384 | 16139/16139/16139 | 60.419/310.310/415.758 | 18.941/19.680/23.284 | 62.247/313.782/418.279 |
| 12 | medium | 384×384 | 147456 | 140149/140149/140149 | 254.747/315.101/724.890 | 157.935/169.413/229.824 | 257.530/317.390/731.364 |
| 12 | large | 1024×1024 | 1048576 | 723902/723902/723902 | 1282.650/1603.377/1774.874 | 948.130/973.797/993.342 | 1288.264/1611.234/1780.572 |

## Spatial results

Latency is min/median/max milliseconds; counts and bytes are actual responses.

| AOI | Rows×Cols | Cells | Valid cells | Latency | Feature count | Response bytes |
|---|---:|---:|---:|---:|---:|---:|
| small | 32×32 | 1024 | 1006/1006/1006 | 23.397/23.756/71.800 | 1006/1006/1006 | 302601/302601/302601 |
| medium | 64×64 | 4096 | 4057/4057/4057 | 93.490/129.969/137.498 | 4057/4057/4057 | 1238623/1238623/1238623 |
| large | 128×128 | 16384 | 16139/16139/16139 | 456.111/510.243/517.373 | 16139/16139/16139 | 4966037/4966037/4966037 |

## Hotspot hypotheses

- **Hypothesis:** Per-indicator raster reads, float64 copies, masks, scans, and statistics may scale with indicators × cells.
- **Hypothesis:** GeoTIFF and manifest persistence may explain part of total service minus pipeline time.
- **Hypothesis:** Standalone raster validation uses a Python np.ndindex loop and a Python value list.
- **Hypothesis:** Spatial generation validates again, then builds one Polygon/Pydantic object per valid cell and serializes JSON.

Raw measured samples and full environment/TIF metadata are in the JSON and CSV files.

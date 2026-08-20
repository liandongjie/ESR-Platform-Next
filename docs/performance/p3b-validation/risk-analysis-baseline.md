# Risk Analysis Performance Baseline

- Subject production baseline: `8f85c420dcc07edbcbf03674478b973c108e6746`
- Repository HEAD: `8f85c420dcc07edbcbf03674478b973c108e6746`
- Source-tree verification: `host_git_diff_and_untracked_allowlist_v1`
- Source tree verified: `true`
- Verified invariant: outside the benchmark-only allowlist, the working tree matches the subject production baseline. Repository HEAD may be newer.
- Benchmark elapsed: `32.775s`
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
| 3 | small | 128×128 | 16384 | 16384/16384/16384 | 28.491/43.905/65.394 | 1.020/1.089/1.101 | 30.874/46.317/67.400 |
| 3 | medium | 384×384 | 147456 | 145560/145560/145560 | 42.262/177.329/252.701 | 1.407/2.430/4.036 | 45.618/182.553/259.512 |
| 3 | large | 1024×1024 | 1048576 | 736372/736372/736372 | 122.597/179.242/766.134 | 4.739/5.354/5.631 | 128.617/186.419/776.429 |
| 6 | small | 128×128 | 16384 | 16139/16139/16139 | 33.222/46.641/152.960 | 0.725/0.819/1.409 | 34.943/48.483/156.401 |
| 6 | medium | 384×384 | 147456 | 140156/140156/140156 | 68.493/83.624/637.216 | 1.412/1.760/2.505 | 71.974/86.879/642.964 |
| 6 | large | 1024×1024 | 1048576 | 724106/724106/724106 | 306.920/578.156/818.989 | 4.806/5.824/7.177 | 314.535/586.034/827.206 |
| 12 | small | 128×128 | 16384 | 16139/16139/16139 | 227.004/287.316/424.344 | 0.833/0.943/2.629 | 229.891/290.802/431.400 |
| 12 | medium | 384×384 | 147456 | 140149/140149/140149 | 122.318/323.142/551.744 | 1.345/1.589/2.496 | 125.699/327.718/557.012 |
| 12 | large | 1024×1024 | 1048576 | 723902/723902/723902 | 731.156/1488.263/1810.922 | 4.979/6.449/8.271 | 739.034/1500.730/1818.797 |

## Spatial results

Latency is min/median/max milliseconds; counts and bytes are actual responses.

| AOI | Rows×Cols | Cells | Valid cells | Latency | Feature count | Response bytes |
|---|---:|---:|---:|---:|---:|---:|
| small | 32×32 | 1024 | 1006/1006/1006 | 20.326/21.761/55.742 | 1006/1006/1006 | 302601/302601/302601 |
| medium | 64×64 | 4096 | 4057/4057/4057 | 82.621/125.096/143.533 | 4057/4057/4057 | 1238623/1238623/1238623 |
| large | 128×128 | 16384 | 16139/16139/16139 | 415.745/454.572/478.767 | 16139/16139/16139 | 4966037/4966037/4966037 |

## Hotspot hypotheses

- **Hypothesis:** Per-indicator raster reads, float64 copies, masks, scans, and statistics may scale with indicators × cells.
- **Hypothesis:** GeoTIFF and manifest persistence may explain part of total service minus pipeline time.
- **Hypothesis:** Standalone raster validation uses a Python np.ndindex loop and a Python value list.
- **Hypothesis:** Spatial generation validates again, then builds one Polygon/Pydantic object per valid cell and serializes JSON.

Raw measured samples and full environment/TIF metadata are in the JSON and CSV files.

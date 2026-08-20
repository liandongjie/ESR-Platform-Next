# Risk Analysis Pipeline Stage Timing

- Production candidate: `8f85c420dcc07edbcbf03674478b973c108e6746`
- Instrumented subject: `637337b29dbe604f3dd9877521dc6d69acad0047`
- Repository HEAD: `637337b29dbe604f3dd9877521dc6d69acad0047`
- Source-tree verification: `host_git_diff_and_untracked_allowlist_v1`
- Source tree and instrumentation lineage verified: `true`
- Benchmark elapsed: `19.134s`
- Repetition: warm-up 1 + measured 5 per scenario

## Timing semantics

- Timers wrap non-overlapping stages inside `RiskAnalysisPipeline.run()`.
- Stage timing is diagnostic and is not a replacement latency baseline.
- `unattributed` is pipeline wall time minus timed stages; it includes resource cleanup, control flow, callback and timer overhead.
- Raw integer nanosecond events and output statistics are retained in JSON.

## Scenarios

All timings are min/median/max milliseconds unless stated otherwise.

| Indicators | Rows×Cols | Cells | Valid cells | Pipeline | Unattributed | Unattributed % |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 1024×1024 | 1048576 | 736372/736372/736372 | 263.730/586.681/717.667 | 2.896/3.652/4.612 | 0.507/0.599/1.098 |
| 6 | 1024×1024 | 1048576 | 724106/724106/724106 | 507.890/918.333/1562.533 | 3.708/6.401/8.743 | 0.237/0.534/1.260 |
| 12 | 1024×1024 | 1048576 | 723902/723902/723902 | 1107.064/1521.499/2316.266 | 6.977/15.964/23.056 | 0.500/0.812/1.515 |

## 3-indicator stages

| Stage | Calls/sample | Elapsed ms | Pipeline share % |
|---|---:|---:|---:|
| `input_validation` | 1/1/1 | 0.419/0.715/2.113 | 0.058/0.154/0.472 |
| `source_open` | 3/3/3 | 37.035/42.425/80.595 | 6.313/9.203/16.086 |
| `grid_validation` | 1/1/1 | 0.127/0.206/0.486 | 0.029/0.048/0.068 |
| `window_geometry_setup` | 1/1/1 | 5.132/5.834/9.879 | 0.965/1.303/1.946 |
| `raster_read` | 3/3/3 | 183.966/505.058/582.499 | 69.755/81.166/86.087 |
| `mask_preparation` | 3/3/3 | 8.660/9.622/15.186 | 1.579/1.732/3.391 |
| `value_validation_and_stats` | 3/3/3 | 5.929/7.847/9.920 | 1.234/1.287/2.248 |
| `weighted_accumulation` | 3/3/3 | 11.358/15.230/19.173 | 1.953/3.146/4.307 |
| `result_finalization` | 1/1/1 | 2.523/3.969/4.249 | 0.525/0.658/0.956 |

## 6-indicator stages

| Stage | Calls/sample | Elapsed ms | Pipeline share % |
|---|---:|---:|---:|
| `input_validation` | 1/1/1 | 0.470/0.743/1.141 | 0.053/0.073/0.103 |
| `source_open` | 6/6/6 | 43.844/92.674/121.872 | 5.706/8.633/10.092 |
| `grid_validation` | 1/1/1 | 0.193/0.194/0.304 | 0.012/0.025/0.038 |
| `window_geometry_setup` | 1/1/1 | 5.013/7.212/8.250 | 0.462/0.701/0.987 |
| `raster_read` | 6/6/6 | 390.643/739.113/1383.908 | 76.915/83.544/88.568 |
| `mask_preparation` | 6/6/6 | 20.052/22.653/24.220 | 1.450/2.637/3.948 |
| `value_validation_and_stats` | 6/6/6 | 13.735/15.579/16.819 | 0.997/1.832/2.704 |
| `weighted_accumulation` | 6/6/6 | 24.412/28.618/30.063 | 1.832/3.035/4.807 |
| `result_finalization` | 1/1/1 | 3.072/3.497/3.848 | 0.224/0.375/0.605 |

## 12-indicator stages

| Stage | Calls/sample | Elapsed ms | Pipeline share % |
|---|---:|---:|---:|
| `input_validation` | 1/1/1 | 0.449/1.000/1.374 | 0.031/0.057/0.122 |
| `source_open` | 12/12/12 | 128.757/193.973/299.099 | 9.225/12.526/20.644 |
| `grid_validation` | 1/1/1 | 0.293/0.352/0.829 | 0.017/0.029/0.054 |
| `window_geometry_setup` | 1/1/1 | 4.115/6.481/9.500 | 0.369/0.381/0.681 |
| `raster_read` | 12/12/12 | 754.952/1167.739/1867.267 | 68.194/79.471/80.615 |
| `mask_preparation` | 12/12/12 | 33.937/41.104/46.094 | 1.775/2.755/3.302 |
| `value_validation_and_stats` | 12/12/12 | 23.397/33.663/37.359 | 1.328/2.113/2.677 |
| `weighted_accumulation` | 12/12/12 | 45.227/49.276/54.412 | 1.953/3.576/4.451 |
| `result_finalization` | 1/1/1 | 2.488/3.269/4.065 | 0.122/0.215/0.367 |

Per-indicator stage timings, all raw samples, environment metadata and TIF SHA-256 values are retained in JSON.

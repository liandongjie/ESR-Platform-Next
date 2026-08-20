# Risk Raster Read Attribution

- Production candidate: `8f85c420dcc07edbcbf03674478b973c108e6746`
- Diagnostic subject: `c08b0875472c5544287f1c81cf0ec9602fad9c89`
- Repository HEAD: `c08b0875472c5544287f1c81cf0ec9602fad9c89`
- Source tree and diagnostic lineage verified: `true`
- Benchmark elapsed: `31.876s`
- Repetition: warm-up 1 + measured 5 per TIF/mode

## Cache and timing semantics

- Cache state: `warm_process_and_os_cache_not_explicitly_flushed`.
- Windows OS cache is not flushed; these are not physical cold-disk timings.
- Open/close are outside read timings except for `open_only`, which times open only.
- Result equivalence checks run outside timed regions.

## Raster layout

| TIF | Compression | Tiled | Block | Blocks touched | Amplification | File bytes |
|---|---|---|---:|---:|---:|---:|
| PM25 | Compression.lzw | true | 128×128 | 81 | 1.266 | 17352556 |
| AQI | Compression.lzw | true | 128×128 | 81 | 1.266 | 17234085 |
| NDVI | None | true | 64×128 | 153 | 1.195 | 218801213 |
| hwmd | Compression.lzw | true | 128×128 | 81 | 1.266 | 4547003 |
| rkmd | Compression.lzw | true | 128×128 | 81 | 1.266 | 37044792 |
| xxmd | Compression.lzw | true | 128×128 | 81 | 1.266 | 3852526 |
| jmdmd | Compression.lzw | true | 128×128 | 81 | 1.266 | 3423442 |
| xspb | Compression.lzw | true | 128×128 | 81 | 1.266 | 3187569 |
| xsqs | Compression.lzw | true | 128×128 | 81 | 1.266 | 3187431 |
| gyfb | None | true | 128×128 | 81 | 1.266 | 218747821 |
| fmyl | Compression.lzw | true | 128×128 | 81 | 1.266 | 3187382 |
| fmts | Compression.lzw | true | 128×128 | 81 | 1.266 | 3187779 |

## Median timing by TIF

All values are milliseconds after one warm-up per mode.

| TIF | Open | Masked/new | Masked/same | Data | Mask | Data+mask |
|---|---:|---:|---:|---:|---:|---:|
| PM25 | 14.369 | 169.869 | 3.353 | 109.160 | 136.720 | 233.206 |
| AQI | 21.563 | 119.171 | 3.957 | 180.605 | 180.278 | 282.231 |
| NDVI | 14.013 | 154.287 | 3.393 | 243.994 | 282.592 | 214.849 |
| hwmd | 8.283 | 71.450 | 3.504 | 15.506 | 28.971 | 76.576 |
| rkmd | 10.816 | 66.642 | 3.710 | 163.387 | 114.418 | 78.851 |
| xxmd | 5.652 | 68.537 | 3.474 | 89.712 | 77.563 | 66.962 |
| jmdmd | 2.082 | 20.259 | 3.391 | 14.285 | 12.688 | 13.308 |
| xspb | 6.328 | 28.884 | 3.780 | 12.411 | 10.605 | 14.969 |
| xsqs | 2.685 | 17.200 | 3.728 | 26.560 | 12.591 | 13.282 |
| gyfb | 2.805 | 39.282 | 3.372 | 34.625 | 43.997 | 33.790 |
| fmyl | 3.572 | 31.561 | 4.989 | 21.778 | 25.324 | 20.318 |
| fmts | 3.148 | 17.756 | 3.598 | 14.277 | 12.782 | 17.702 |

## Median ratios

| TIF | Masked/data | Masked/(data+mask) | Same/new handle |
|---|---:|---:|---:|
| PM25 | 1.556 | 0.728 | 0.020 |
| AQI | 0.660 | 0.422 | 0.033 |
| NDVI | 0.632 | 0.718 | 0.022 |
| hwmd | 4.608 | 0.933 | 0.049 |
| rkmd | 0.408 | 0.845 | 0.056 |
| xxmd | 0.764 | 1.024 | 0.051 |
| jmdmd | 1.418 | 1.522 | 0.167 |
| xspb | 2.327 | 1.930 | 0.131 |
| xsqs | 0.648 | 1.295 | 0.217 |
| gyfb | 1.135 | 1.163 | 0.086 |
| fmyl | 1.449 | 1.553 | 0.158 |
| fmts | 1.244 | 1.003 | 0.203 |

Raw nanosecond samples, min/median/max summaries, GDAL configuration, environment metadata and TIF SHA-256 values are retained in JSON/CSV.

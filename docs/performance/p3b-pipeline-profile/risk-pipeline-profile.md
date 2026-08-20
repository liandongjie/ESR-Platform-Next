# Risk Analysis Pipeline cProfile

- Subject production candidate: `8f85c420dcc07edbcbf03674478b973c108e6746`
- Repository HEAD: `62213098b0568c751da4cc727732c77f02d96191`
- Source-tree verification: `host_git_diff_and_untracked_allowlist_v1`
- Source tree verified: `true`
- Profile elapsed: `17.137s`
- Repetition: warm-up 1 + profiled 5 per scenario

## Profiling semantics

- `cProfile` wraps only `RiskAnalysisPipeline.run()`.
- Profiled wall time includes cProfile overhead and must not be compared with baseline latency.
- Function rankings use aggregate self/cumulative time across all measured runs.

## Scenarios

Profiled wall time is min/median/max milliseconds and is diagnostic only.

| Indicators | Rows×Cols | Cells | Valid cells | Profiled wall time | Profile file |
|---:|---:|---:|---:|---:|---|
| 3 | 1024×1024 | 1048576 | 736372/736372/736372 | 313.559/397.487/535.806 | `risk-pipeline-3.prof` |
| 6 | 1024×1024 | 1048576 | 724106/724106/724106 | 648.007/750.913/1388.221 | `risk-pipeline-6.prof` |
| 12 | 1024×1024 | 1048576 | 723902/723902/723902 | 1076.156/1629.859/2311.283 | `risk-pipeline-12.prof` |

## 3-indicator hotspots

### Top cumulative time

| Function | Calls | Self s | Cumulative s |
|---|---:|---:|---:|
| `app/gis/risk_pipeline.py:199:run` | 5 | 1.644108 | 1.971037 |
| `/usr/local/lib/python3.12/site-packages/rasterio/env.py:443:wrapper` | 15 | 0.000372 | 0.173209 |
| `/usr/local/lib/python3.12/site-packages/rasterio/__init__.py:100:open` | 15 | 0.167978 | 0.169793 |
| `~:0:<built-in method posix.stat>` | 70 | 0.029071 | 0.029616 |
| `/usr/local/lib/python3.12/pathlib.py:835:stat` | 20 | 0.000039 | 0.029204 |
| `/usr/local/lib/python3.12/pathlib.py:886:is_file` | 15 | 0.000092 | 0.027153 |
| `/usr/local/lib/python3.12/site-packages/rasterio/env.py:408:wrapper` | 10 | 0.000068 | 0.024798 |
| `/usr/local/lib/python3.12/site-packages/rasterio/features.py:40:geometry_mask` | 5 | 0.000028 | 0.024776 |
| `/usr/local/lib/python3.12/site-packages/rasterio/features.py:205:rasterize` | 5 | 0.022694 | 0.024661 |
| `~:0:<method 'reduce' of 'numpy.ufunc' objects>` | 170 | 0.023091 | 0.023091 |

### Top self time

| Function | Calls | Self s | Cumulative s |
|---|---:|---:|---:|
| `app/gis/risk_pipeline.py:199:run` | 5 | 1.644108 | 1.971037 |
| `/usr/local/lib/python3.12/site-packages/rasterio/__init__.py:100:open` | 15 | 0.167978 | 0.169793 |
| `~:0:<built-in method posix.stat>` | 70 | 0.029071 | 0.029616 |
| `~:0:<method 'reduce' of 'numpy.ufunc' objects>` | 170 | 0.023091 | 0.023091 |
| `~:0:<built-in method numpy.asarray>` | 85 | 0.023071 | 0.023071 |
| `/usr/local/lib/python3.12/site-packages/rasterio/features.py:205:rasterize` | 5 | 0.022694 | 0.024661 |
| `/usr/local/lib/python3.12/contextlib.py:567:__exit__` | 30 | 0.015002 | 0.015427 |
| `~:0:<method 'copy' of 'numpy.ndarray' objects>` | 20 | 0.010439 | 0.010439 |
| `/usr/local/lib/python3.12/site-packages/numpy/ma/core.py:3857:filled` | 15 | 0.004646 | 0.014636 |
| `~:0:<built-in method numpy.zeros>` | 10 | 0.003471 | 0.003471 |

## 6-indicator hotspots

### Top cumulative time

| Function | Calls | Self s | Cumulative s |
|---|---:|---:|---:|
| `app/gis/risk_pipeline.py:199:run` | 5 | 3.705751 | 4.330340 |
| `/usr/local/lib/python3.12/site-packages/rasterio/env.py:443:wrapper` | 30 | 0.000668 | 0.358361 |
| `/usr/local/lib/python3.12/site-packages/rasterio/__init__.py:100:open` | 30 | 0.349111 | 0.352329 |
| `~:0:<built-in method posix.stat>` | 115 | 0.062417 | 0.063349 |
| `/usr/local/lib/python3.12/pathlib.py:835:stat` | 35 | 0.000055 | 0.062702 |
| `/usr/local/lib/python3.12/pathlib.py:886:is_file` | 30 | 0.000141 | 0.060247 |
| `~:0:<built-in method numpy.asarray>` | 145 | 0.041973 | 0.041973 |
| `/usr/local/lib/python3.12/contextlib.py:567:__exit__` | 45 | 0.035018 | 0.035523 |
| `~:0:<method 'reduce' of 'numpy.ufunc' objects>` | 320 | 0.033097 | 0.033097 |
| `/usr/local/lib/python3.12/site-packages/numpy/ma/core.py:3857:filled` | 30 | 0.010279 | 0.032637 |

### Top self time

| Function | Calls | Self s | Cumulative s |
|---|---:|---:|---:|
| `app/gis/risk_pipeline.py:199:run` | 5 | 3.705751 | 4.330340 |
| `/usr/local/lib/python3.12/site-packages/rasterio/__init__.py:100:open` | 30 | 0.349111 | 0.352329 |
| `~:0:<built-in method posix.stat>` | 115 | 0.062417 | 0.063349 |
| `~:0:<built-in method numpy.asarray>` | 145 | 0.041973 | 0.041973 |
| `/usr/local/lib/python3.12/contextlib.py:567:__exit__` | 45 | 0.035018 | 0.035523 |
| `~:0:<method 'reduce' of 'numpy.ufunc' objects>` | 320 | 0.033097 | 0.033097 |
| `/usr/local/lib/python3.12/site-packages/rasterio/features.py:205:rasterize` | 5 | 0.023817 | 0.026189 |
| `~:0:<method 'copy' of 'numpy.ndarray' objects>` | 35 | 0.022500 | 0.022500 |
| `/usr/local/lib/python3.12/site-packages/numpy/ma/core.py:3857:filled` | 30 | 0.010279 | 0.032637 |
| `~:0:<built-in method numpy.zeros>` | 10 | 0.003736 | 0.003736 |

## 12-indicator hotspots

### Top cumulative time

| Function | Calls | Self s | Cumulative s |
|---|---:|---:|---:|
| `app/gis/risk_pipeline.py:199:run` | 5 | 6.925434 | 8.052506 |
| `/usr/local/lib/python3.12/site-packages/rasterio/env.py:443:wrapper` | 60 | 0.001437 | 0.683264 |
| `/usr/local/lib/python3.12/site-packages/rasterio/__init__.py:100:open` | 60 | 0.662806 | 0.669631 |
| `~:0:<built-in method posix.stat>` | 205 | 0.126286 | 0.128658 |
| `/usr/local/lib/python3.12/pathlib.py:835:stat` | 65 | 0.000121 | 0.127490 |
| `/usr/local/lib/python3.12/pathlib.py:886:is_file` | 60 | 0.000326 | 0.123346 |
| `/usr/local/lib/python3.12/contextlib.py:567:__exit__` | 75 | 0.066552 | 0.067153 |
| `~:0:<built-in method numpy.asarray>` | 265 | 0.063185 | 0.063185 |
| `/usr/local/lib/python3.12/site-packages/numpy/ma/core.py:3857:filled` | 60 | 0.020414 | 0.057669 |
| `~:0:<method 'reduce' of 'numpy.ufunc' objects>` | 620 | 0.052590 | 0.052590 |

### Top self time

| Function | Calls | Self s | Cumulative s |
|---|---:|---:|---:|
| `app/gis/risk_pipeline.py:199:run` | 5 | 6.925434 | 8.052506 |
| `/usr/local/lib/python3.12/site-packages/rasterio/__init__.py:100:open` | 60 | 0.662806 | 0.669631 |
| `~:0:<built-in method posix.stat>` | 205 | 0.126286 | 0.128658 |
| `/usr/local/lib/python3.12/contextlib.py:567:__exit__` | 75 | 0.066552 | 0.067153 |
| `~:0:<built-in method numpy.asarray>` | 265 | 0.063185 | 0.063185 |
| `~:0:<method 'reduce' of 'numpy.ufunc' objects>` | 620 | 0.052590 | 0.052590 |
| `~:0:<method 'copy' of 'numpy.ndarray' objects>` | 65 | 0.036720 | 0.036720 |
| `/usr/local/lib/python3.12/site-packages/rasterio/features.py:205:rasterize` | 5 | 0.027050 | 0.029008 |
| `/usr/local/lib/python3.12/site-packages/numpy/ma/core.py:3857:filled` | 60 | 0.020414 | 0.057669 |
| `~:0:<built-in method numpy.zeros>` | 10 | 0.003188 | 0.003188 |

Full call graphs are retained in the `.prof` files; raw samples and metadata are in JSON.

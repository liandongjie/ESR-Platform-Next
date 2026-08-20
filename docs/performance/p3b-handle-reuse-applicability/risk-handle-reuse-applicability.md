# Risk DatasetReader Handle Reuse Applicability

- Production candidate: `8f85c420dcc07edbcbf03674478b973c108e6746`
- Diagnostic subject: `ecd1d22c9946ef0b483a713e40a264e7469bd3bd`
- Repository HEAD: `ecd1d22c9946ef0b483a713e40a264e7469bd3bd`
- Source tree and diagnostic lineage verified: `true`
- Benchmark elapsed: `62.693s`
- Repetition: warm-up 1 + measured 5 per relationship/mode

## Timing semantics

- Cache state: `warm_process_and_os_cache_not_explicitly_flushed`.
- Windows OS cache is not flushed; these are not physical cold-disk timings.
- Only target `read(masked=True)` calls are timed.
- Open, close, base-window priming and result equivalence run outside timing.
- This is a single-process, single-thread diagnostic, not full Pipeline latency.

## Window relationships

| Relationship | Column shift | Pixel overlap | Block cache coverage |
|---|---:|---:|---:|
| `same_window` | 0 | 100.0% | 100.0% |
| `half_overlap` | 512 | 50.0% | 55.6% |
| `zero_block_overlap` | 1152 | 0.0% | 0.0% |

## 12-TIF sequence timing

All values are min/median/max milliseconds.

| Relationship | Reopen | Reuse | Median speedup | Reuse median < reopen min | Gate |
|---|---:|---:|---:|---|---|
| `same_window` | 807.145/1251.802/1401.158 | 27.868/37.086/61.181 | 33.75× | true | true |
| `half_overlap` | 594.970/691.540/811.215 | 102.413/191.584/382.862 | 3.61× | true | true |
| `zero_block_overlap` | 435.391/475.156/691.744 | 279.356/557.262/704.397 | 0.85× | false | false |

The quantitative gate requires at least 1.5× median speedup and reuse median below reopen minimum. Variability and semantic equivalence still require manual review.

All sequence samples, per-TIF nanosecond events, environment metadata, GDAL configuration and TIF SHA-256 values are retained in JSON/CSV.

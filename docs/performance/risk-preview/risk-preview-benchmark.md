# Risk preview benchmark

本报告由 `scripts/benchmark-risk-preview.ps1` 生成。旧值来自仓库已记录基线，
新值来自按相同 shape/有效像元数构造的确定性代表矩阵。

- 旧基线来源：`docs/performance/risk-analysis-baseline.json`。
- Subject SHA：`5810240e14d1d5a86562d73d6b85f2cdd2083cc4`。
- 来源文件 SHA256：`f0554ed2f62d4d7474ece2ce1550c1de714fe731253873b1dd21eec0955e275c`。
- 传输口径：`flask_test_client_no_network`，样本数 `5`。

| 指标 | 旧 GeoJSON | 新 PNG |
|---|---:|---:|
| 有效像元 / Polygon | 16,139 | 16,139 |
| 响应体 | 4,966,037 bytes | 15,111 bytes |
| 地图覆盖物 | 16,139 | 1 |
| 服务端 PNG 生成 p95 | 不适用 | 5.348 ms |

- 响应体压缩比：328.637x。
- 指示性响应体减少：99.696%。
- 地图覆盖物减少：99.994%。
- 色带版本：`risk-viridis-5-v1`。
- p95 统计口径：`nearest-rank`（第 `ceil(0.95*n)` 个有序样本）。

> 范围说明：这是服务端确定性 PNG 编码微基准，不是浏览器首次显示 p95；
> 网络、浏览器解码、ImageLayer 首次显示与交互帧率尚未测量。

> 该百分比是“已记录旧基线 vs 确定性代表矩阵 PNG”的跨运行指示性对比，
> 不是同一 artifact 的受控 A/B；最终真实 A/B 留待 Compose 集成环境执行。

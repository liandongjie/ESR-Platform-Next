# 50 用户隔离 RC 负载报告

## 结论

2026-08-20 在本机隔离 Production Compose 上完成两类 50 用户场景和 1 VU 幂等探针：

- 场景 A 的 50 个独立用户持续执行登录、本人任务列表、状态和 manifest 下载，HTTP 错误率
  0%，列表 p95 441.34 ms、状态 p95 382.99 ms，均低于 500 ms；
- 场景 B 的 50 个独立用户各提交一个三指标任务并轮询，50/50 进入明确终态，HTTP 错误率
  0%；状态 p95 8.41 ms、服务端排队 p95 2,641.10 ms、执行 p95 139.20 ms；
- 同一 Idempotency-Key 连续提交返回同一 task ID，4/4 checks 通过；
- PostgreSQL 应用连接采样峰值为 10，Redis broker 队列采样峰值为 36，应用日志没有
  QueuePool timeout、死锁或状态倒退；
- 基于连接峰值和固定进程模型，将 `max_overflow` 从 5 收紧到 0。调优后复测仍为 0% HTTP
  错误，列表 p95 449.77 ms、状态 p95 405.80 ms，继续满足 500 ms 门槛。

这些数字证明当前本机 RC 通过了既定 50 用户验收，不等同于火山引擎线上容量或公网 HTTPS
延迟。上线前必须在目标服务器以同一脚本复测。

## 被测版本与环境

| 项目 | 值 |
|---|---|
| Git 基线 | `d621094dfa55ab6c17d14e0eee9aea7197acaabe` |
| 工作树 | 包含本周未提交 diff；因此以镜像 ID作为本次固定运行物，不冒充已提交 SHA |
| Backend image | `sha256:3d9b9f1574ee49c14bee1e8a278ae33c56e9614bfb56e52bd6424ae555121f24` |
| Frontend image | `sha256:d55ff87a24204300cd28bc59a60e3f002921de39a9df740e0f8b421125477b71` |
| Docker / Compose | Engine 28.0.1 / Compose 2.33.1 |
| Docker VM | 24 vCPU，8,186,773,504 bytes memory，Docker Desktop |
| k6 | `grafana/k6:0.54.0`，image digest `sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755` |
| Compose project | `esr-platform-next-rc`，与已有默认 project、network、volumes 隔离 |
| 数据库 | PostgreSQL 16 + PostGIS 3.4，migration head `20260820_03` |
| 测试输入 | `scenario.example.json` SHA-256 `E283CC3DE8699E35D0F002FFDF4CD58DE0FCF0AF01E8A86FB6E46417BCC52F5B` |
| 源栅格 | 12 个只读文件；逐文件 SHA-256 见 `source-raster-sha256.txt` |

Backend 镜像构建时工作树中的连接池默认仍为 overflow 5；调优复测由 Production Compose 显式
注入 `ESR_DB_MAX_OVERFLOW=0`，与最终仓库默认语义一致。最终提交后 CI 会重新构建镜像并运行
PostGIS release gate。

## 场景 A：读链与小成果下载

配置：50 VUs、30 秒、每次迭代执行登录 → 分页任务列表 → 本人任务状态 → manifest 下载，
迭代间隔 0.2 秒。每个 VU 使用独立账号。

| 指标 | 结果 |
|---|---:|
| 完整迭代 | 1,619 |
| HTTP 请求 | 6,476 |
| Checks | 8,095 / 8,095 |
| HTTP 错误率 | 0% |
| Artifact candidate 成功率 | 100% |
| 列表 p50 / p95 / p99 | 229.11 / 441.34 / 531.18 ms |
| 状态 p50 / p95 / p99 | 133.05 / 382.99 / 499.53 ms |
| PostgreSQL 应用连接采样峰值 | 10 |
| Redis broker 队列采样峰值 | 0 |

资源瞬时样本中 Backend CPU 最高 616.43%（Docker 多核口径），内存最高约 396.4 MiB；Worker
约 243.4 MiB、PostgreSQL 约 78.88 MiB、Redis 约 9.87 MiB。该资源数据只有 4 个瞬时点，
不能替代完整时间序列。

## 场景 B：提交、排队与终态

配置：50 VUs、每 VU 一次迭代、独立账号和幂等键；提交同一小型三指标研究区并轮询终态。

| 指标 | 结果 |
|---|---:|
| HTTP 请求 | 468 |
| Checks | 618 / 618 |
| HTTP 错误率 | 0% |
| 已入队任务明确终态 | 50 / 50 |
| 提交 p50 / p95 / p99 | 474.22 / 665.92 / 695.11 ms |
| 状态 p50 / p95 / p99 | 6.18 / 8.41 / 93.60 ms |
| 服务端排队 p50 / p95 / p99 | 1,340 / 2,641.10 / 2,752.59 ms |
| 服务端执行 p50 / p95 / p99 | 118.50 / 139.20 / 167.57 ms |
| PostgreSQL 应用连接采样峰值 | 10 |
| Redis broker 队列采样峰值 | 36 |

服务端样本约每 0.7 秒一次，共 12 个点；因此 Redis 36 是观测下界，不应声称为毫秒级精确
峰值。数据库任务表最终核对为 151 个 `SUCCEEDED`，对应一次业务 smoke 和三轮各 50 个负载
任务，无 FAILED/CANCELED/EXPIRED；本表中的正式报告数字取第三轮同步采样场景。

## 连接池调优复测

调优前配置为 `pool_size=5, max_overflow=5`。实测连接峰值 10 与 2×4 Gunicorn 线程加
2 个 Celery 槽吻合，且没有 pool timeout。`max_overflow` 不会提高当前执行槽吞吐，只会扩大
全局连接预算，因此收紧为 0。

调优后使用相同 50 用户读链执行 20 秒：3,952 请求、4,940/4,940 checks、0% HTTP 错误；
列表 p95 449.77 ms、状态 p95 405.80 ms，无 QueuePool timeout。两轮持续时间不同，因此复测
只用于验证验收门和错误回归，不作为吞吐性能 A/B 百分比。

## 原始证据与限制

本目录保存 k6 JSON summary、控制台输出、PostgreSQL/Redis 采样 CSV 和 Docker stats 原始文本。
账号、密码、Token、Cookie 和宿主机绝对数据路径均未归档。

本次未包含：

- 火山引擎公网 HTTPS 压测；
- 浏览器首次风险图显示 p95；
- 生产备份恢复和真实 RTO；
- 长时间 soak test。

这些指标在实际执行前不能进入简历数字。

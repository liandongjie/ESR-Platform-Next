# 数据库连接池与 50 用户容量模型

## 口径与边界

本文件记录当前发布配置的连接预算和调优依据。2026-08-20 已完成本机隔离 RC 的 50 用户
实测；结果不代表火山引擎线上容量，完整原始证据见
`docs/performance/load-test/2026-08-20-rc-local/`。
SQLAlchemy 使用原生 QueuePool 参数：`pool_size=5`、`max_overflow=0`、
`pool_timeout=10s`、`pool_recycle=1800s`、`pool_pre_ping=true`。
连接按进程持有，Gunicorn 线程共享所在进程的池；连接按需创建，因此实际连接数通常低于上限。

当前进程模型来自 `backend/Dockerfile` 与 Compose。下表的连接数是 QueuePool 配置容量上界，
不是执行槽在当前并发模型下能够同时占用的连接数：

| 组件 | 数据库进程数 | 单进程 Pool 配置容量 | Pool 配置容量合计 |
|---|---:|---:|---:|
| Gunicorn（2 workers、每 worker 4 threads） | 2 | 5 | 10 |
| Celery worker（concurrency=2） | 2 | 5 | 10 |
| Celery Beat | 1 | 5 | 5 |
| 常驻服务合计 | 5 | 5 | 25 |

配置容量公式为 `(2 + 2 + 1) × 5 = 25`。一次性 migration、Flask CLI 或诊断进程按
额外一个进程估算，短时配置容量最多再增加 5，因此发布操作期间的配置容量上界为 30。
以 PostgreSQL 默认 `max_connections=100` 计算，仍保留 70 条连接给数据库维护、人工诊断和
异常恢复。生产配置会拒绝单进程 `pool_size + max_overflow > 10`；如需改变该上限，必须先同步
调整进程模型、PostgreSQL 连接上限和本容量预算。CLI 使用完毕后应退出，不能作为常驻第六类进程。

按当前执行槽估算，同时借出连接的可达上界远低于 50：Gunicorn 为 `2 workers × 4 threads = 8`，
Celery 为 2 个任务槽，Beat 只发布定时消息而不执行数据库维护查询，因此常驻服务约为 10 条；
发布期 CLI 再增加约 1 条。QueuePool 按需创建连接，配置容量不会在启动时全部建立。这个估算仍需
通过负载期间的 `pg_stat_activity` 验证，不能当作实测峰值。

## 50 用户验收结果

本机隔离 Production Compose 实测满足：

- 50 个独立用户场景 API 错误率低于 1%；
- 任务列表和状态查询 p95 低于 500 ms；
- 数据库连接池 timeout 为 0，PostgreSQL 无死锁；
- 已成功入队的任务最终全部进入明确终态；
- 记录 API p50/p95/p99、入队/排队/执行耗时、队列峰值和 Worker 吞吐；
- 记录同一时间轴上的数据库连接、Redis 队列和容器资源瞬时样本。

读链 30 秒共 6,476 请求，错误率 0%，列表/状态 p95 分别为 441.34/382.99 ms；异步场景
50/50 任务进入终态，排队/执行 p95 分别为 2,641.10/139.20 ms。PostgreSQL 应用连接采样
峰值 10、Redis 队列采样峰值 36，未发现 pool timeout。基于该结果将 `max_overflow` 从 5
收紧为 0，复测仍通过 500 ms 门槛。简历引用时必须带“本机隔离 RC”边界；正式发布前还需用
最终 Git SHA 重建并复跑发布门。

## 负载期间只读采样

以下命令不修改业务数据。压测前、峰值期间和压测结束后各保留带时间戳的原始输出。

```powershell
# PostgreSQL 当前连接分布与上限
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT application_name, state, count(*) FROM pg_stat_activity GROUP BY application_name, state ORDER BY application_name, state;"'
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SHOW max_connections;"'

# Redis 默认 Celery 队列长度
docker compose exec -T redis redis-cli -n 0 LLEN celery

# Celery 正在执行与已经预留的任务
docker compose exec -T worker celery -A app.celery_app:celery_app inspect active
docker compose exec -T worker celery -A app.celery_app:celery_app inspect reserved

# Web、Worker、Beat、PostgreSQL、Redis 的瞬时资源占用
docker stats --no-stream

# SQLAlchemy QueuePool 等待超时证据
docker compose logs --no-color backend worker beat | Select-String -Pattern 'QueuePool|pool timeout|TimeoutError'
```

`pg_stat_activity` 是服务端事实源；Redis `LLEN` 只表示等待领取的 broker 队列，必须与
Celery active/reserved 一起解释。`docker stats --no-stream` 是瞬时样本，不能替代完整时间序列。

## 调优判据

- 出现 pool timeout 时，先对齐 PostgreSQL 活跃连接、慢请求和进程数；只增加
  `pool_timeout` 会延长等待，不会增加吞吐。
- 常驻池持续饱和、PostgreSQL 仍有充足余量且容器内存稳定时，才考虑小步增加
  `pool_size`；每次调整后重新计算全局上限。
- 只有短峰值经实测出现 pool timeout、且 PostgreSQL 仍有余量时才从 0 小步调整
  `max_overflow`；若 PostgreSQL 连接逼近 30 条，禁止继续
  增池，应先定位长事务、连接泄漏或不合理并发。
- GIS Worker 是 CPU、内存和磁盘 I/O 混合负载。数据库仍有余量不代表可以提高 Celery
  concurrency；Worker 吞吐下降或内存争用时应维持或降低并发。
- `pool_recycle` 用于回收长寿命连接，`pool_pre_ping` 用于复用前探活；两者不能替代事务边界、
  rollback 和数据库可用性治理。

当前参数来自 50 用户本机 RC 实测；仍不能外推为线上公网容量或更高并发能力。

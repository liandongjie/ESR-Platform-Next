# ESR API 可复现负载测试

本资产定义可重复执行的测试方法；2026-08-20 本机隔离 RC 的 50 用户实测结果见
[负载报告](load-test/2026-08-20-rc-local/report.md)。运行前应使用与报告一致的 Git SHA、
主机规格、数据库规模和源栅格版本；本机结果不能外推为火山引擎线上容量。

## 数据与安全

- 安装 [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/)；脚本不会自动注册用户。
- 将 `scripts/load-test/users.example.json` 复制为 `users.local.json`，准备与 VU 数相同的独立测试账号。`*.local.json` 和 `results/` 已被 Git 忽略。
- 不要将生产密码、真实域名、Cookie 或 Token 写入仓库和测试报告。
- `BASE_URL` 只提供协议、主机和端口，不包含 `/api/v1`。
- 研究区和三项指标默认来自 `scenario.example.json`；可通过 `SCENARIO_DATA_FILE`、`GEOMETRY_JSON` 或 `INDICATOR_CODES=code1,code2,code3` 替换。

## 场景与运行

场景 A 持续执行“登录 → 分页任务列表 → 状态 → 可选 artifact”。设置 `ARTIFACT_KIND` 后只从列表选择首个 `SUCCEEDED + result_available` 任务；也可用 `TASK_ID` 显式指定任务。建议仅下载小型 `manifest`。

```powershell
$env:SCENARIO = "A"
$env:BASE_URL = "http://127.0.0.1:8080"
$env:USERS_FILE = "./users.local.json"
$env:VUS = "50"
$env:DURATION = "1m"
$env:ARTIFACT_KIND = "manifest"
New-Item -ItemType Directory -Force scripts/load-test/results | Out-Null
k6 run --summary-export scripts/load-test/results/scenario-a-summary.json scripts/load-test/esr-load-test.js
```

场景 B 使用每 VU 一次迭代，执行“登录 → 提交同一个小型三指标研究区 → 轮询到 SUCCEEDED/FAILED/CANCELED/EXPIRED”。每次运行自动生成幂等键；正式对比时应显式设置唯一 `RUN_ID`。

```powershell
$env:SCENARIO = "B"
$env:BASE_URL = "http://127.0.0.1:8080"
$env:USERS_FILE = "./users.local.json"
$env:SCENARIO_DATA_FILE = "./scenario.example.json"
$env:RUN_ID = "rc1-20260820-01"
$env:VUS = "50"
$env:POLL_TIMEOUT_SECONDS = "180"
New-Item -ItemType Directory -Force scripts/load-test/results | Out-Null
k6 run --summary-export scripts/load-test/results/scenario-b-summary.json scripts/load-test/esr-load-test.js
```

幂等性只用独立的 1 VU 探针验证，不混入 50 用户吞吐场景。探针会用同一个 `Idempotency-Key` 连续提交两次，并要求返回相同 `task_id`：

```powershell
$env:SCENARIO = "IDEMPOTENCY_PROBE"
$env:BASE_URL = "http://127.0.0.1:8080"
$env:ESR_USERNAME = "load-user-001"
$env:ESR_PASSWORD = "在当前终端临时填写"
$env:VUS = "1"
$env:RUN_ID = "rc1-idempotency-01"
k6 run scripts/load-test/esr-load-test.js
```

单账号 dry-run 只验证脚本和接口链路，不是并发证据：

```powershell
$env:SCENARIO = "A"
$env:BASE_URL = "http://127.0.0.1:8080"
$env:ESR_USERNAME = "load-user-001"
$env:ESR_PASSWORD = "在当前终端临时填写"
$env:VUS = "1"
$env:DURATION = "10s"
k6 run scripts/load-test/esr-load-test.js
```

## 指标语义与验收

- 全部 HTTP 请求输出 `min/p(50)/p(95)/p(99)/max`。
- 阈值：`http_req_failed < 1%`、业务 checks 通过率 `> 99%`、任务列表和状态查询 p95 `< 500 ms`。
- 场景 B 另以 `esr_enqueued_jobs_terminal` 独立 Rate 要求每个服务端已接受的提交都返回 `task_id`，并在超时前进入明确终态（`rate == 1`），避免被其他 checks 稀释。
- `esr_enqueue_request_duration_ms` 是提交 POST 的客户端端到端耗时，不冒充 Redis 入队内部耗时。
- Phase 2 状态响应已经公开持久化的 `queued_at`、`started_at`、`completed_at` 和 `timing`。k6 的 `esr_server_queue_wait_ms` 仅由 `queued_at/submitted_at → started_at` 计算，`esr_server_execution_ms` 仅由 `started_at → completed_at` 计算，以服务端时间戳为准，不使用客户端轮询间隔估算。
- 时间戳 Contract 可用不等于已经取得压测结果；仍需针对固定 Git SHA 和环境实际运行 k6。旧版本或缺少完整终态时间戳时，脚本只增加 `esr_missing_server_timing_fields`，不会补造 queue/execution 数据。
- 队列峰值和数据库连接池等待不能由 HTTP 客户端推导。本脚本不生成这两个数字；应分别从 Redis/Celery 和 PostgreSQL/应用连接池的服务端观测数据采集并与同一 RUN_ID 对齐。

报告至少记录：Git SHA、运行命令（脱敏）、数据文件哈希、机器/容器规格、数据库任务量、每项阈值结果、p50/p95/p99、终态分布、服务端 timing 覆盖情况及原始 summary 文件。

# ESR-Platform-Next

面向环境社会风险分析场景的多用户 WebGIS。系统基于真实的 12 项标准化栅格数据，打通
研究区选择、米制缓冲、POI、异步风险计算、任务恢复、地图预览和成果下载，并提供可复现的
PostGIS migration、50 用户负载测试与单机部署/恢复证据。

## 当前已实现

- Vue 3 + TypeScript + Vite WebGIS 工作台
- Vue Router、Pinia、Element Plus、Axios、ECharts
- 高德地图绘制、坐标输入、地址/POI 搜索、行政区和 Shapefile 研究区输入
- Flask Application Factory 与版本化 Blueprint
- WGS84/GCJ-02 地图边界转换与米制缓冲区
- 12 项标准化风险指标配置、窗口化栅格读取、共同有效掩膜与加权叠加
- JWT access token + HttpOnly refresh cookie、生产关闭注册、演示账号 CLI 和跨用户资源隔离
- PostgreSQL/PostGIS 用户/任务事实源、Alembic 01-03 migration、数据库分页历史任务
- Celery + Redis 异步队列、幂等提交、每用户限流、活动任务上限和条件状态迁移
- 失败任务派生重试、排队取消、Worker 丢失重投、Beat 待分发补偿和成果 TTL 清理
- POI 分析与 CSV 导出、风险 GeoTIFF 和结果清单下载
- 透明风险 PNG、受保护 Blob 下载和单个高德 ImageLayer；旧 GeoJSON 只作兼容 fallback
- SQLAlchemy QueuePool 容量预算、PostgreSQL/PostGIS、Redis、Web、Worker、Beat 的 Compose
- Caddy/HTTPS 单机边界、生产 readiness migration head 检查、备份/恢复和发布门脚本
- Pytest、Vitest、Ruff、ESLint、Prettier 基础检查
- GitHub Actions 中的生产镜像和 PostGIS upgrade→downgrade→upgrade gate

## 已验证结果

| 闭环 | 结果 | 证据 |
|---|---|---|
| 风险预览 | 指示性响应体 4,966,037 → 15,111 bytes（-99.696%）；地图覆盖物 16,139 → 1 | [预览基准](docs/performance/risk-preview/risk-preview-benchmark.md) |
| 50 用户读链 | 6,476 请求、0% HTTP 错误；列表/状态 p95 441.34/382.99 ms | [负载报告](docs/performance/load-test/2026-08-20-rc-local/report.md) |
| 50 用户异步链 | 50/50 任务明确终态；排队/执行 p95 2,641.10/139.20 ms | [负载报告](docs/performance/load-test/2026-08-20-rc-local/report.md) |
| 连接池调优 | 实测连接峰值 10；`max_overflow` 5→0，配置容量 50→25，复测仍低于 500 ms | [容量模型](docs/performance/capacity-model.md) |
| 浏览器 E2E | 登录、失败终态、全 UI 成功分析、刷新恢复、PNG 默认链和跨用户 404 通过 | [E2E 报告](docs/performance/e2e/2026-08-20-rc-local/report.md) |
| 发布恢复 | PostGIS 三版迁移往返通过；52 用户/154 任务与 460 个 runtime 文件恢复一致 | [演练报告](docs/deployment/drills/2026-08-20-rc-local.md) |

负载和故障时间来自本机隔离 RC，不外推为火山引擎公网容量或生产 RTO。正式发布前仍需用
最终 Git SHA 重建镜像，并在现有域名/HTTPS 环境执行生产 smoke 与回滚。

本项目不通过堆叠 TiTiler、GeoServer、微服务、Kafka 或 Kubernetes 代替真实业务问题的解决。

## 目录

```text
frontend/               Vue 3 + TypeScript 前端
backend/                Flask 后端与 Celery Worker
infra/nginx/            Nginx 反向代理配置
docs/                   架构决策与实施范围
scripts/                本地初始化和检查脚本
data/source/            本地栅格挂载占位目录，不提交数据
data/runtime/           任务结果目录，不提交生成物
```

Production 单 Linux 主机部署见
[`docs/deployment/single-host-runbook.md`](docs/deployment/single-host-runbook.md)。
系统边界见 [`docs/architecture/overview.md`](docs/architecture/overview.md)。

## 数据边界

真实栅格不进入 Git。开发机上的源数据目录：

```text
D:\ESR-Platform\static\tif
```

在 `.env` 中设置：

```env
ESR_SOURCE_RASTER_HOST_DIR=D:/ESR-Platform/static/tif
```

Docker Compose 会把该目录只读挂载到容器的 `/data/source`。任务输出写入独立运行目录。

## 本地启动

### 1. 创建环境变量

PowerShell：

```powershell
Copy-Item .env.example .env
```

至少填写：

- `SECRET_KEY`
- `JWT_SECRET_KEY`
- `ESR_SOURCE_RASTER_HOST_DIR`
- `VITE_AMAP_JS_API_KEY`
- `VITE_AMAP_SECURITY_JS_CODE`

### 2. Docker Compose

```powershell
docker compose up --build
```

首次启动先执行 migration，再创建本地演示账号：

```powershell
docker compose run --rm backend flask --app wsgi:app db upgrade
$env:ESR_DEMO_USER_PASSWORD = "请在本地终端临时填写至少 8 位密码"
docker compose run --rm -e ESR_DEMO_USER_PASSWORD backend `
  flask --app wsgi:app create-demo-user --username demo
Remove-Item Env:ESR_DEMO_USER_PASSWORD
```

默认访问：

- 前端：http://localhost:5173
- 后端存活检查：http://localhost:5000/api/v1/health/live
- 后端就绪检查：http://localhost:5000/api/v1/health/ready

### 3. 不使用 Docker 的后端开发

建议 Python 3.12：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:DATABASE_URL = "sqlite:///esr_dev.sqlite3"
python -m flask --app wsgi:app run --debug
```

GIS 依赖按需安装：

```powershell
python -m pip install -e ".[dev,gis]"
```

### 4. 不使用 Docker 的前端开发

```powershell
cd frontend
npm install
npm run dev
```

## 检查

后端：

```powershell
cd backend
ruff check .
pytest
```

前端：

```powershell
cd frontend
npm run type-check
npm run lint
npm run test:run
npm run build
```

## 坐标系原则

- 后端、数据库、GeoJSON 和栅格分析统一使用 WGS84 / EPSG:4326。
- 高德地图展示使用 GCJ-02。
- 坐标转换集中在前端地图适配层。
- 高德绘制结果必须转换为 WGS84 后才能提交给分析接口。
- 米制缓冲区不得直接在经纬度坐标上按“度”计算。

详见 `docs/architecture/adr-001-coordinate-systems.md`。

## STAR / 简历素材

以下表述只使用仓库中的实测数据；投递前可按岗位限制压缩字数：

- **主导** 12 指标 GIS 风险计算链路，使用 Rasterio window、NumPy 共同有效掩膜和向量化校验
  替代逐像元 Python 扫描，使 12 指标大范围结果校验中位耗时由 973.797 ms 降至 6.449 ms，
  降低 99.3%。
- **设计** JWT + PostgreSQL/PostGIS 多用户任务中心，将用户、WGS84 Geometry、状态、进度、
  幂等关系和成果元数据纳入数据库事实源；在真实浏览器与 API 中验证用户切换任务清零、跨用户
  task/下载返回 404，并完成 52 用户、154 任务的备份恢复核对。
- **引入** Redis/Celery 可靠异步治理，通过用户级幂等/限流、延迟确认、条件状态迁移、受控重试
  和 Beat 补偿支撑 50 用户同时提交，50/50 已入队任务进入明确终态，HTTP 错误率 0%，执行
  p95 139.20 ms；Worker 停止后任务保持 QUEUED，恢复后 4.164 秒完成。
- **重构** 风险空间预览，将 16,139 个逐像元 Polygon 替换为透明 RGBA PNG + 单 ImageLayer，
  指示性响应体由 4.97 MB 降至 15.11 KB（-99.696%），覆盖物降至 1 个，服务端 PNG 生成
  p95 5.348 ms，同时保留 GeoTIFF 精度成果和旧任务 fallback。
- **完成** 50 用户端到端负载与 SQLAlchemy QueuePool 调优，30 秒处理 6,476 个认证/列表/状态/
  下载请求且错误率 0%，列表/状态 p95 441.34/382.99 ms；依据连接峰值 10 将 overflow 从 5
  收紧到 0，把常驻 Pool 配置容量从 50 降至 25，复测仍通过 500 ms 门槛。
- **搭建** 火山引擎单机部署约束下的 Caddy/HTTPS、Compose、Alembic readiness 和恢复流程，
  在隔离 PostGIS 中验证 upgrade→downgrade→upgrade，并将 52 用户、154 任务及 460 个成果文件
  恢复到新卷且内容哈希一致；实际生产 RTO 待目标服务器演练后填写。

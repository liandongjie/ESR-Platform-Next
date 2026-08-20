# 一周升级 Contract 与验收基线

- 基线：`d621094dfa55ab6c17d14e0eee9aea7197acaabe`
- 目标：在保留现有 GIS 计算与文件成果边界的前提下，补齐多用户、可靠任务、轻量风险预览和可复现容量证据。
- 历史策略：现有文件型任务和成果不删除、不回填；升级后的任务只从 PostgreSQL 列表展示。

## 认证 Contract

- `POST /api/v1/auth/register`：`{ username, password }`；注册关闭时返回 `403`。
- `POST /api/v1/auth/login`：`{ username, password }`；返回 `{ access_token, user: { id, username } }`，并设置 HttpOnly refresh cookie。
- `POST /api/v1/auth/refresh`：使用 refresh cookie 和 Flask-JWT CSRF header 换取新的 access token。
- `POST /api/v1/auth/logout`：使用 refresh cookie 和 CSRF header 注销当前 refresh token。
- `GET /api/v1/auth/me`：返回 `{ user: { id, username } }`。
- 风险任务、提交上下文、结果、空间预览和下载接口全部要求 Bearer access token，并按 owner 隔离。

## 任务 Contract

- `POST /api/v1/risk-analysis/jobs` 接受 `Idempotency-Key`；同一用户重复使用相同 key 时返回同一任务。
- PostgreSQL 保存 owner、请求、Geometry、状态、进度、错误、时间戳和成果元数据；GeoTIFF/PNG/JSON 继续保存到 runtime 文件系统。
- 任务状态增加 `EXPIRED`；过期成果返回 `410`，审计元数据保留。
- 失败任务重试创建新任务并记录父任务；本期只允许取消尚未开始的排队任务。
- 超过服务端 `max_analysis_area_km2` 的 Geometry 在入队前返回 `422`。

## 风险预览 Contract

- 新任务生成透明 RGBA PNG；NoData 和研究区外像元透明。
- 结果清单增加 preview artifact、WGS84 栅格 bounds 和 palette version。
- 前端以认证 Blob 创建 Object URL，并在高德地图适配边界转换 bounds 后使用单个 ImageLayer。
- 现有逐像元 GeoJSON 接口暂时保留，但新任务默认不请求。

## 验收基线

- 当前大空间结果：16,139 个 Polygon，响应体 4,966,037 bytes。
- 当前前端生产主 JS：996.59 kB，gzip 323.33 kB；本期不把 bundle 拆分列为阻塞项。
- 当前前端：34 个测试文件、441 个用例通过。
- 目标：风险覆盖物降为 1、preview 小于 500 kB、首次显示 p95 小于 1.5 s。
- 目标：50 用户场景错误率低于 1%，任务列表/状态查询 p95 小于 500 ms，无连接池超时和状态倒退。

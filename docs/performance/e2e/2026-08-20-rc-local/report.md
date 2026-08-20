# 隔离 RC 浏览器 E2E 报告

## 环境

- 日期：2026-08-20；
- URL：本机隔离 Production Compose loopback upstream；不记录测试密码或地图 key；
- 浏览器：Playwright CLI + 本机 Edge 通道，`Edg/151.0.0.0`；
- Backend/Frontend 运行物和数据版本与
  `docs/performance/load-test/2026-08-20-rc-local/report.md` 相同；
- 状态 Contract 修复通过单测后，为节省重复下载 GIS wheel，仅将该 route 文件复制到隔离
  backend 容器并重启复验；最终镜像仍需由 CI 从工作树完整重建。

## 验收结果

| 链路 | 结果 | 证据 |
|---|---|---|
| 登录与生产注册策略 | PASS | 演示账号登录成功；Capabilities 显示 registration disabled；注册请求 403 |
| 历史任务恢复 | PASS | 演示账号只显示本人 1 个完成任务；刷新后仍显示同一 task ID |
| 用户切换隔离 | PASS | 切到 `other` 后任务列表为 0；访问演示账号 task ID 返回 404 `JOB_NOT_FOUND` |
| 已有结果预览 | PASS | 结果 API 200、受保护 PNG 200；Resource Timing 60.2 ms / 372 bytes；旧 spatial 请求 0 次 |
| 失败终态呈现 | PASS（修复后） | 500 m 研究区确定性失败后，页面显示 FAILED、100% 与明确错误消息 |
| 全 UI 成功分析 | PASS | 坐标输入 → 3000 m Buffer → 默认三指标 → 异步任务 → SUCCEEDED |
| 成功结果 | PASS | task `5ae0e861-27d4-4b5d-bb30-084895f88e91`，28 个有效像元，6×8，EPSG:4326 |
| 新任务 PNG 默认链 | PASS | Preview Resource Timing 13 ms / 427 bytes；旧 spatial 请求 0 次；页面 1 个 canvas |
| 页面刷新恢复 | PASS | 刷新后恢复任务、实际分析范围、三项权重、结果状态和地图图层 |

两次 Resource Timing 是单次 smoke 数据，不能写成浏览器首次显示 p95。地图通过真实高德 API
加载；控制台只剩高德 Canvas `willReadFrequently` 性能提示，没有应用错误。

## E2E 发现并修复的问题

500 m 研究区没有覆盖任何源栅格像元中心，Worker 按 Contract 将任务置为 FAILED。浏览器随后
发现 `GET /risk-analysis/jobs/{id}` 对 FAILED 也返回 409，前端因此无法读取服务端终态，持续显示
“查询任务状态失败”。

修复后：

- 通用任务状态端点对 FAILED/CANCELED 返回 200 和结构化状态/错误；
- `/result`、artifact 和 spatial 对没有结果的 FAILED/CANCELED 仍返回 409；
- 失败和取消状态的后端定向测试通过；
- 原失败任务无需重建即可在浏览器正确显示终态，证明修复作用在读取 Contract，而不是掩盖
  Worker 错误。

## 截图

- `result-preview.png`：演示账号历史结果和地图预览；
- `ui-analysis-success.png`：从 UI 提交后完成的 3000 m 风险任务；
- `reload-recovery.png`：刷新后恢复的结果图层与提交上下文。

截图可能包含非敏感的本地 task ID 和业务指标，不包含账号密码、Token 或 Cookie。

## 未覆盖

- 浏览器首次风险图显示 p95（需要可重复的浏览器性能采样协议）；
- 火山引擎域名/HTTPS 环境；
- 移动端与多浏览器矩阵；
- 长时间登录刷新和 7 天 refresh 到期。

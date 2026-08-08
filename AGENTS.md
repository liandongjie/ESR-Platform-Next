# AGENTS.md

本文件定义 Codex 在 ESR-Platform-Next 中长期遵循的工程规则。  
只记录稳定约束；阶段进度、当前 SHA、临时问题和具体任务方案放在 handoff 或当次 prompt。

## 1. Project

ESR-Platform-Next 是环境社会风险分析 WebGIS 项目。

主要技术栈：

- Frontend：Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus、Axios、ECharts、高德地图 JS API。
- Backend：Python 3.12、Flask、Pydantic、SQLAlchemy、Alembic。
- Async：Celery + Redis。
- GIS：GeoPandas、Rasterio、Shapely、PyProj、NumPy。
- Infra：PostgreSQL/PostGIS、Docker Compose。
- Quality：Pytest、Vitest、Ruff、ESLint、vue-tsc。

真实源码、测试、已接受 ADR 和当前 Git 状态优先于 README、旧文档和历史会话。发现冲突时先报告，不自行猜测。

## 2. Before Coding

### Source First

任何非微小修改前：

1. 确认 branch、HEAD、working tree。
2. 搜索相关 API、Store、Service、组件、测试和 helper。
3. 阅读真实调用链。
4. 新建实现前确认是否已有可复用能力。

不要只凭文件名、旧文档或 prompt 推断代码结构。

### Short Plan First

先给简短 plan，等待确认后再实施。Plan 只需包含：

- 目标。
- 从源码确认的关键事实。
- 预计修改文件。
- 核心实现。
- 风险。
- 测试与人工验收。

不要重复本文件已有规则，不写教程式长计划。

### Stop on Surprise

出现以下情况时先停下来汇报：

- 实际代码与已确认 plan 明显不同。
- 需要扩大到计划外的重要文件。
- 需要新增依赖、migration、全局配置或破坏兼容性。
- 发现 Contract 冲突或与当前任务不同的历史缺陷。
- 需要删除文件、大段删除代码或清理持久化数据。

不要为了完成任务静默扩大 scope。

## 3. Change Discipline

### Single Writer

同一批代码只由一个 writer 修改。Codex 执行时，以本地真实工作树为唯一代码基线，不假设其他 AI 的旧 patch 或脚本仍适用。

### Reuse Before Create

新增 API、Store、Service、组件、状态机、轮询器、GIS helper 或测试工具前先搜索已有实现。

优先级：

1. 复用现有项目代码。
2. 扩展现有抽象。
3. 使用适用的已安装 skill（如 Ponytail）。
4. 确认现有能力不足后再新增。

不要创建功能等价的第二套 HTTP client、Store、polling、Result parser、坐标转换、错误映射或分页组件。

### Small Semantic Commits

较大任务拆成多个可独立解释、测试和回滚的小 commit。

按“完整行为变化”拆，不按文件拆。例如：

- `feat: restore workspace task after reload`
- `feat: restore workspace submission context`

每一批完成后先测试、review、commit，再进入下一批。

### No Silent Cleanup

当前任务之外不要顺手：

- 大规模重构或全仓格式化。
- 升级依赖或替换库。
- 改不相关命名/UI。
- 清理历史 TODO。
- 修复无关缺陷。

可以记录，但不要混入当前 diff。

### Git Safety

除非用户明确要求：

- 不自动 commit。
- 不自动 push。
- 不自动 merge。
- 不 force push。
- 不修改 main 历史。

Commit 前必须 review staged diff；PR 默认等待 CI 和人工确认。

以下操作必须先说明影响并获得确认：

- 新增/删除依赖。
- 数据库 migration。
- 修改 `.env` 语义。
- 修改 Docker / CI / Nginx 等全局配置。
- 删除文件或持久化/runtime 数据。
- 破坏性 Git 操作。

## 4. Architecture Boundaries

### Frontend

保持现有职责：

- View / Component：交互和展示。
- Store：业务状态和生命周期。
- API：HTTP Contract 与请求封装。
- 地图 adapter / composable：高德 SDK 和坐标边界。

约束：

- View 不重复实现已有 API 请求逻辑。
- 不把高德 SDK 对象放入 Pinia。
- 浏览器持久化只保存必要的最小状态；服务端业务状态仍以服务端为准。
- 异步任务防止 stale response 覆盖新状态，优先复用已有 revision / polling。
- TypeScript 类型不是运行时 JSON 校验；关键外部 Contract 在边界做运行时校验。

### Backend

沿用现有分层：

- API / Blueprint：HTTP 输入输出。
- Pydantic Schema：Contract / validation。
- Service：业务编排。
- Store / repository：持久化。
- GIS module：空间算法。

不要把业务逻辑堆进 route。

API Contract 变化时同步检查：

- Backend schema。
- API response/status code。
- Frontend TypeScript type。
- API client。
- 自动测试。
- 历史数据兼容性。

### Server as Source of Truth

异步任务的 status、progress、result 和持久化业务数据以服务端为准。浏览器缓存只能保存恢复所需的最小指针或 UI 状态。

## 5. GIS Invariants

除非新的 ADR 明确修改，否则：

### Coordinates

- 后端 API、GeoJSON、PostGIS、研究区、栅格分析统一 WGS84 / EPSG:4326。
- 高德地图展示使用 GCJ-02。
- WGS84 ↔ GCJ-02 只在前端地图适配边界转换。
- 高德产生的 geometry 提交后端前必须转回 WGS84。
- GCJ-02 geometry 禁止直接裁剪 WGS84 栅格。
- 米制 Buffer 先投影到合适的米制 CRS，再转回 WGS84；禁止直接对经纬度按“度”缓冲。

### Raster

- 不隐式 reprojection / resampling。
- 对齐条件不满足时显式失败或按已确认方案处理。
- NoData 不等于 0。
- 多指标叠加使用共同有效 mask。
- 避免整幅读取大栅格，优先按 geometry/window 读取。
- 显式检查 CRS、transform、shape、NoData 等空间元数据。
- 算法口径变化必须用测试锁定。

## 6. Comments

使用适量中文注释，主要解释“为什么”，尤其是：

- GIS 坐标边界。
- 异步竞态 / revision guard。
- 数据 Contract。
- 历史兼容。
- 特殊 fallback。
- 容易被误删或错误简化的规则。

不要给普通赋值写翻译式注释。

## 7. Testing

“代码写完”不等于“功能完成”。

### Static

Backend：

```powershell
cd backend
ruff check app tests
```

Frontend：

```powershell
cd frontend
npm run type-check
npm run lint
```

### Automated

Backend：

```powershell
cd backend
pytest
```

Frontend：

```powershell
cd frontend
npm run test:run
npm run build
```

优先跑定向测试，再跑完整回归。

### Manual E2E

涉及浏览器、地图、异步任务、Celery、Docker 或文件产物时，自动测试后仍需给人工验收步骤。

至少覆盖：

- 正常路径。
- 边界条件。
- 异常路径。
- 负面验收：明确哪些事情绝对不能发生。

### Evidence over Claim

不要只说“已修复/测试通过”。完成时给出实际证据：

- 执行命令。
- 测试数量和结果。
- HTTP status / 关键字段（如适用）。
- 浏览器观察结果（如适用）。
- `git diff --check`。
- warning / 已知限制及是否阻塞。

## 8. Code Review

Commit 前自审：

1. 是否满足当前目标且没有扩大 scope。
2. 是否重复造轮子。
3. 是否存在计划外文件。
4. API / Schema / Type 是否一致。
5. 异步是否存在竞态、重复请求或重复任务。
6. GIS 不变量是否保持。
7. loading / empty / error 是否完整。
8. 测试是否覆盖真正风险。
9. 是否混入无关 cleanup。
10. Diff 是否可解释、可回滚。

## 9. Reporting

### Plan

优先用短表格：

| 项目 | 内容 |
|---|---|
| 目标 | 最终状态 |
| 当前事实 | 源码确认的关键事实 |
| 修改 | 文件和动作 |
| 原因 | 为什么这样设计 |
| 风险 | 最可能出错的位置 |
| 验证 | 自动测试 + 手动验收 |

### After Implementation

每批修改后提供：

| 文件 / 模块 | 修改 | 为什么 |
|---|---|---|

同时报告：

- `git status --short`
- `git diff --stat`
- 测试结果
- 未运行测试及原因
- 风险 / 非阻塞项
- 是否建议 commit 及 commit message

不要自动宣布可以 merge；质量门、人工验收和 CI 满足后再建议。

## 10. Token / Context Economy

- 不重复解释 AGENTS.md 已规定内容。
- 不在每次 plan 重述整个项目。
- 先搜索目标符号和调用链，再读取必要文件。
- 不为局部任务读取大量无关目录。
- 长日志先定位失败点，再展开相关上下文。
- 同一任务中已确认的事实不要反复调研。
- Handoff 负责阶段背景；task prompt 只提供当前增量。
- 能通过源码或测试确认的问题优先取证，不长篇猜测。
- Plan 以“足够做对”为目标，不追求篇幅。

## 11. Default Workflow

```text
确认 Git 基线
→ 阅读真实源码
→ 搜索复用能力
→ 简短 Plan
→ 用户确认
→ 实施一个小批次
→ 定向测试
→ 完整质量门
→ Code Review
→ 人工验收
→ Commit
→ 下一小批次
→ Push / PR
→ CI / Review
→ Merge
```

优先保证：可审计、可验证、可回滚。

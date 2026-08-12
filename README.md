# ESR-Platform-Next

面向环境社会风险分析场景的 WebGIS 工程化重构项目。当前仓库处于“工程骨架”阶段，目标是在真实的 12 项标准化栅格数据基础上，逐步实现研究区选择、缓冲区、POI 分析、异步风险计算、结果展示和成果导出。

## 当前已搭建

- Vue 3 + TypeScript + Vite 前端骨架
- Vue Router、Pinia、Element Plus、Axios、ECharts
- 高德地图加载适配层和无密钥占位状态
- Flask Application Factory 与版本化 Blueprint
- SQLAlchemy、Alembic、JWT、CORS 扩展入口
- Celery + Redis 工厂与示例健康任务
- PostgreSQL/PostGIS、Redis、前后端和 Worker 的 Docker Compose
- Pytest、Vitest、Ruff、ESLint、Prettier 基础检查
- GitHub Actions CI 基线

## 当前没有实现

- 注册登录业务接口
- 地图绘制和坐标转换
- 预置风险点接口
- POI 分析
- 12 项栅格裁剪与加权叠加
- 任务进度、取消、重试和结果清理
- 空间数据上传与成果导出
- TiTiler、GeoServer、Three.js

这些内容将按纵向业务链路逐阶段实现，不在骨架阶段伪造。

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

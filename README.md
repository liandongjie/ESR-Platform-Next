



# ESR Platform

**Environmental and Social Risk Analysis Platform · 环境社会风险分析平台**

ESR Platform是一个面向环境与社会风险分析场景的 WebGIS 应用。

它把研究区域定义、空间缓冲、POI 检索、栅格指标计算和结果查看放在同一套地图工作流中。用户不需要在多个 GIS 软件、脚本和中间文件之间来回切换，可以直接从一个研究区域开始，完成一次完整的空间分析并保存结果。

## 在线体验

项目已经部署，可直接访问：

**https://14.103.34.41:8081/**

出于演示环境的数据安全考虑，仓库中不公开固定账号和密码。

如需体验完整功能，可以通过邮件联系：

**[502022270071@smail.nju.edu.cn](mailto:502022270071@smail.nju.edu.cn)**

邮件主题注明 `ESR Platform Demo` 即可。

------

## 这个项目解决什么问题

环境与社会风险分析通常不是一次简单的地图查询。

实际工作中，一次分析往往需要先确定研究区域，再构造一定范围的缓冲区，随后查询区域内的兴趣点、读取不同来源的栅格指标，对空间数据进行统一处理，最后才能得到可供判断和进一步使用的结果。

如果这些步骤分别依赖 GIS 软件、Python 脚本和人工文件管理，分析过程会比较零散，也很难完整保留一次任务的上下文。

本项目希望把这件事情整理成一条清晰的工作流：

```text
研究区域
   ↓
缓冲区
   ↓
POI / 风险指标
   ↓
空间分析任务
   ↓
地图预览
   ↓
结果与成果文件
```



------

## 使用方式

### 1. 定义研究区域

分析从研究区域开始。

目前可以通过多种方式确定空间范围，包括地图交互、坐标输入、地址或 POI 搜索、行政区选择以及 Shapefile 数据。

不同来源的区域最终都会整理成统一的空间对象，再进入后续分析流程。

![image-20260823163144488](./README.assets/image-20260823163144488.png) 

### 2. 创建缓冲区

确定研究区域以后，可以按照实际分析需求设置缓冲距离。

缓冲距离按真实的米制距离计算。

![image-20260823165013339](./README.assets/image-20260823165013339.png) 

### 3. 查看区域内的 POI

对于需要了解周边设施或社会活动分布的场景，可以进一步执行 POI 分析。

结果可以直接在地图中查看，同时支持以结构化数据形式导出，便于后续统计或独立分析。

![image-20260823165059559](./README.assets/image-20260823165059559.png) 

### 4. 配置风险指标

风险分析以栅格指标为基础。

当前系统配置了 12 项标准化环境、人口和社会相关指标。用户可以根据分析目的选择指标并设置权重，然后提交分析任务。

![image-20260823165144683](./README.assets/image-20260823165144683.png) 

### 5. 查看分析结果

风险计算在后台执行。

任务完成以后，结果可以重新加载到地图中查看，而不是要求用户一直停留在当前页面等待。历史任务及其状态也会被保存，刷新页面或者重新进入系统后仍然能够找到之前的分析。

地图中的风险图层主要承担快速预览作用；需要进一步处理时，可以下载对应的分析成果文件。

------

## 系统是怎么组织的

本项目采用一个比较直接的 WebGIS 架构：

```text
                         ┌─────────────────────┐
                         │   Vue 3 Web Client  │
                         │   Map / Workspace   │
                         └──────────┬──────────┘
                                    │
                               REST / JSON
                                    │
                         ┌──────────▼──────────┐
                         │      Flask API      │
                         └───────┬──────┬──────┘
                                 │      │
                    ┌────────────┘      └────────────┐
                    │                                │
          ┌─────────▼──────────┐          ┌──────────▼─────────┐
          │ PostgreSQL/PostGIS │          │   Redis / Celery   │
          │ users / tasks /    │          │   async jobs       │
          │ geometry / metadata│          └──────────┬─────────┘
          └────────────────────┘                     │
                                          ┌──────────▼─────────┐
                                          │    GIS Worker      │
                                          │ Raster / Vector    │
                                          │     Analysis       │
                                          └──────────┬─────────┘
                                                     │
                                      ┌──────────────┴──────────────┐
                                      │                             │
                               Source Rasters               Runtime Results
```

Web API 负责用户、任务和分析请求，PostgreSQL/PostGIS 保存需要长期存在的业务和空间信息；耗时的 GIS 计算交给 Celery Worker 执行，Redis 用于任务队列；源栅格和计算结果则作为独立的数据文件管理。

更完整的架构说明见：

```text
docs/architecture/
```

------

## 技术栈

项目主要使用以下技术：

| 层次       | 技术                                                     |
| ---------- | -------------------------------------------------------- |
| Web        | Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus |
| Map        | 高德地图 JavaScript API                                  |
| API        | Flask、SQLAlchemy                                        |
| Spatial    | PostGIS、Rasterio、GeoPandas、Shapely、NumPy             |
| Async      | Celery、Redis                                            |
| Database   | PostgreSQL / PostGIS                                     |
| Migration  | Alembic                                                  |
| Deployment | Docker Compose                                           |
| Testing    | Pytest、Vitest、Ruff、ESLint                             |



------

## 坐标与空间数据

项目对地图展示和空间分析使用的坐标进行了明确区分：

后台 API、GeoJSON、数据库以及栅格分析统一使用：

```text
WGS84 / EPSG:4326
```

高德地图展示使用：

```text
GCJ-02
```

地图交互产生的坐标会在进入后台分析之前完成转换。

对于缓冲分析，同样不会直接在经纬度坐标上把“度”当作“米”使用。

相关设计记录见：

```text
docs/architecture/adr-001-coordinate-systems.md
```

------

## 项目目录

```text
ESR-Platform-Next/
├─ frontend/                # Vue 3 Web 客户端
├─ backend/                 # Flask API 与 GIS / Celery Worker
├─ data/
│  ├─ source/               # 本地源栅格挂载位置
│  └─ runtime/              # 运行时分析结果
├─ docs/
│  ├─ architecture/         # 架构与设计记录
│  └─ deployment/           # 部署说明
├─ infra/                   # 基础设施相关配置
├─ scripts/                 # 初始化、检查与辅助脚本
├─ docker-compose.yml
└─ README.md
```

源栅格数据和运行过程中生成的结果文件不提交到 Git 仓库。

------

## 本地运行

### 1. 准备配置

从示例配置创建本地环境文件：

```powershell
Copy-Item .env.example .env
```

根据本机环境补充必要配置，包括：

```text
SECRET_KEY
JWT_SECRET_KEY
ESR_SOURCE_RASTER_HOST_DIR
VITE_AMAP_JS_API_KEY
VITE_AMAP_SECURITY_JS_CODE
```

其中：

```text
ESR_SOURCE_RASTER_HOST_DIR
```

需要指向本机实际存放源栅格数据的目录。

### 2. 启动服务

推荐直接使用 Docker Compose：

```bash
docker compose up --build
```

首次运行需要执行数据库 migration：

```bash
docker compose run --rm backend flask --app wsgi:app db upgrade
```

随后即可访问：

```text
Frontend
http://localhost:5173

Backend health
http://localhost:5000/api/v1/health/live
http://localhost:5000/api/v1/health/ready
```

更完整的单机部署流程见：

```text
docs/deployment/single-host-runbook.md
```

------

## 分开启动前后端

如果只是进行本地开发，也可以不通过完整 Compose 环境启动 Web 服务。

### Backend

建议使用 Python 3.12：

```bash
cd backend

python -m venv .venv
```

PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,gis]"
python -m flask --app wsgi:app run --debug
```

### Frontend

```bash
cd frontend

npm install
npm run dev
```

------

## 测试与检查

Backend：

```bash
cd backend

ruff check .
pytest
```

Frontend：

```bash
cd frontend

npm run type-check
npm run lint
npm run test:run
npm run build
```

------

## Contact

如果你在运行项目或阅读代码时遇到问题，可以通过以下方式联系：

**Email:** [502022270071@smail.nju.edu.cn](mailto:502022270071@smail.nju.edu.cn)

**GitHub:** https://github.com/liandongjie

------

## License

本仓库暂未单独声明开源许可证。

如需复用项目中的代码或数据，请先联系作者确认使用范围。
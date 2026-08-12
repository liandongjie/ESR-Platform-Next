# 单 Linux 主机部署 Runbook

本文说明如何用 `compose.production.yml` 在一台 Linux 主机上运行
ESR-Platform-Next。所有命令均在仓库根目录执行，并使用独立 Compose project name，
避免与同机其他环境共享容器、网络或 named volumes。

```bash
export COMPOSE_PROJECT_NAME=esr-platform-next-prod
```

## 1. 前置条件

- Linux 主机已安装 Docker Engine 和 Docker Compose plugin，且当前用户可以运行
  `docker compose`。
- 主机已取得待部署的、经过审核的仓库版本。
- 12 个 Contract 要求的 source raster 文件已放在主机的独立目录中；该目录会以只读
  方式挂载到 Backend 和 Worker。
- Frontend 发布端口（默认 `80`）未被占用。

## 2. 配置

从模板创建本机私有配置：

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

编辑 `.env.production`，至少替换以下 placeholder：

- `SECRET_KEY`、`JWT_SECRET_KEY`：使用不同的随机 production secret。
- `POSTGRES_PASSWORD`，以及 `DATABASE_URL` 中对应的 URL-encoded 密码。
- `ESR_SOURCE_RASTER_HOST_DIR`：source raster 的绝对宿主机路径。
- `VITE_AMAP_JS_API_KEY`、`VITE_AMAP_SECURITY_JS_CODE`：Frontend build-time
  公开配置。

不要提交 `.env.production`。模板中的 `replace-with-*` 值不能用于启动 production。
如需修改发布端口，设置 `HTTP_PORT`。

先确认 source raster 目录存在且文件对部署用户可读，再静态校验 Compose 配置：

```bash
test -d "$(grep '^ESR_SOURCE_RASTER_HOST_DIR=' .env.production | cut -d= -f2-)"
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" config --quiet
```

## 3. 构建和启动

```bash
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" build
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" up -d
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" ps
```

Production Compose 只向宿主机发布 Frontend 端口。Backend、Worker、PostgreSQL 和
Redis 只在 Compose 网络中访问；Frontend Nginx 将 `/api/` 转发给 Backend。

## 4. 日常操作

查看全部服务日志，或只跟踪指定服务：

```bash
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" logs --tail=200
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" logs -f backend worker
```

重启服务：

```bash
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" restart
```

停止服务但保留容器：

```bash
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" stop
```

停止并移除容器和网络，同时保留 named volumes：

```bash
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" down
```

不要附加 `--volumes`，否则会删除本 project 的 runtime、PostgreSQL 和 Redis
持久化数据。

## 5. 更新

将主机上的仓库切换到已审核的新版本，并检查 `.env.production` 是否需要补充新配置，
然后执行：

```bash
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" config --quiet
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" build
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" up -d --remove-orphans
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" ps
```

本流程不执行数据库 migration；部署前应根据目标版本的 release notes 单独确认是否有
额外升级步骤。

## 6. Health 与最小 smoke

- `/api/v1/health/live` 只证明 Flask application/process 存活，不检查外部依赖。
- `/api/v1/health/ready` 检查数据库、Redis/Celery Redis endpoints、source raster
  文件和 runtime 可写性。Production Backend healthcheck 使用此端点。

设 Frontend 的公开地址为 `http://SERVER`；若修改了 `HTTP_PORT`，追加对应端口：

```bash
curl --fail http://SERVER/
curl --fail http://SERVER/api/v1/health/live
curl --fail http://SERVER/api/v1/health/ready
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" ps
```

验收结果应为：Frontend 返回成功响应，两个 health endpoint 返回 HTTP 200，且 `ps`
显示 Backend healthy、其他核心服务正常运行。若 `/live` 成功但 `/ready` 返回 503，
查看响应中的结构化检查状态以及 Backend/DB/Redis 日志，不要把实例加入流量。

## 7. 数据边界

- `ESR_SOURCE_RASTER_HOST_DIR` 是宿主机 bind mount，在 Backend 和 Worker 中均为
  只读 `/data/source`。
- runtime 输出、PostgreSQL 数据和 Redis 数据分别保存在 Compose named volumes 中；
  普通 `down` 和重新构建 image 不会删除它们。
- named volumes 归属 `esr-platform-next-prod` project；操作时必须持续使用同一个
  `-p` 值。

## 8. 当前限制

当前 production artifacts 不包含：

- TLS 和 domain 配置；
- CD 或 registry push；
- 自动备份/恢复；
- runtime artifact 的自动 TTL cleanup。

在补齐对应能力前，需由部署环境在仓库范围外提供这些运维措施。

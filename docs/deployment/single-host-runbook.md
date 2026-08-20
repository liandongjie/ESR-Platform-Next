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
- 现有 Caddy 继续独占公网 `80/443` 并负责域名和 HTTPS；Compose Frontend 默认只绑定
  `127.0.0.1:8080`。

## 2. 配置

从模板创建本机私有配置：

```bash
cp .env.production.example .env.production
chmod 600 .env.production
```

编辑 `.env.production`，至少替换以下 placeholder：

- `SECRET_KEY`、`JWT_SECRET_KEY`：使用不同的随机 production secret。
- `ESR_REGISTRATION_ENABLED=false`：公开演示环境保持关闭注册。
- `POSTGRES_PASSWORD`，以及 `DATABASE_URL` 中对应的 URL-encoded 密码。
- `ESR_SOURCE_RASTER_HOST_DIR`：source raster 的绝对宿主机路径。
- `VITE_AMAP_JS_API_KEY`、`VITE_AMAP_SECURITY_JS_CODE`：Frontend build-time
  公开配置。

不要提交 `.env.production`。模板中的 `replace-with-*` 值不能用于启动 production。
保持 `HTTP_BIND_ADDRESS=127.0.0.1`，只在与现有服务冲突时修改 `HTTP_PORT`。脱敏后的
Caddy 反代示例见 `docs/deployment/Caddyfile.example`；不要用示例覆盖服务器上的真实配置。

先确认 source raster 目录存在且文件对部署用户可读，再静态校验 Compose 配置：

```bash
test -d "$(grep '^ESR_SOURCE_RASTER_HOST_DIR=' .env.production | cut -d= -f2-)"
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" config --quiet
```

## 3. 固定发布版本并构建

发布必须选择明确的、已审核 Git SHA，并记录上一版本 SHA 和 image ID。工作树非空时停止，
不要把服务器上的临时改动混入镜像：

```bash
test -z "$(git status --porcelain)"
export RELEASE_SHA="$(git rev-parse --verify '<reviewed-sha>^{commit}')"
export PREVIOUS_SHA="$(cat .last-successful-sha 2>/dev/null || true)"
export IMAGE_TAG="$RELEASE_SHA"
git switch --detach "$RELEASE_SHA"

docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" build
docker image inspect "esr-platform-backend:${IMAGE_TAG:-local}" \
  --format '{{.Id}}' | tee "release-${RELEASE_SHA}.backend-image-id"
```

仓库当前没有 registry/CD；因此 image ID 是单机重建证据，不是跨主机可复现的 digest。

## 4. 首次启动

先启动数据库和 Redis，执行 migration，再启动应用服务。Readiness 会拒绝未到 Alembic head
的数据库，因此不能跳过 migration：

```bash
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" up -d db redis
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" run --rm backend flask --app wsgi:app db upgrade
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" up -d
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" ps
```

Production Compose 只向宿主机发布 Frontend 端口。Backend、Worker、PostgreSQL 和
Redis 只在 Compose 网络中访问；Frontend Nginx 将 `/api/` 转发给 Backend。

## 5. 演示账号

Production 默认关闭开放注册。密码不得写入仓库或 `.env.production`，由发布终端临时输入：

```bash
read -rsp 'Demo password: ' ESR_DEMO_USER_PASSWORD; echo
export ESR_DEMO_USER_PASSWORD
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" run --rm -e ESR_DEMO_USER_PASSWORD \
  backend flask --app wsgi:app create-demo-user --username demo
unset ESR_DEMO_USER_PASSWORD
```

## 6. 日常操作

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

## 7. 更新前备份

每次升级在切换应用前备份 PostgreSQL 和 runtime volume，并记录恢复命令。以下操作不会停止
当前应用；备份目录应再复制到主机外的受控存储：

```bash
export BACKUP_DIR="backups/$(date -u +%Y%m%dT%H%M%SZ)-${RELEASE_SHA}"
mkdir -p "$BACKUP_DIR"
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" exec -T db \
  pg_dump -U "${POSTGRES_USER:-esr}" -d "${POSTGRES_DB:-esr_platform}" -Fc \
  > "$BACKUP_DIR/postgres.dump"
docker run --rm \
  -v "${COMPOSE_PROJECT_NAME}_runtime_data:/source:ro" \
  -v "$PWD/$BACKUP_DIR:/backup" alpine:3.20 \
  tar -C /source -czf /backup/runtime.tar.gz .
sha256sum "$BACKUP_DIR/postgres.dump" "$BACKUP_DIR/runtime.tar.gz" \
  > "$BACKUP_DIR/SHA256SUMS"
```

备份完成后至少执行 `pg_restore --list "$BACKUP_DIR/postgres.dump"` 和
`tar -tzf "$BACKUP_DIR/runtime.tar.gz" >/dev/null`，不能只凭文件存在判定成功。

## 8. 生产升级

检查 `.env.production` 是否需要补充新配置。构建新 SHA 后，先 migration，再替换应用容器：

```bash
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" config --quiet
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" build
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" run --rm backend flask --app wsgi:app db upgrade
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" up -d --remove-orphans
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" ps
```

首次升级到多用户任务版本时，01-03 三个 migration 会连续执行。原有 runtime 文件保留但
不回填，也不会出现在新版任务列表。

## 9. Health、Worker 与业务 smoke

- `/api/v1/health/live` 只证明 Flask application/process 存活，不检查外部依赖。
- `/api/v1/health/ready` 检查数据库连接及 Alembic head、Redis/Celery Redis endpoints、
  source raster 文件和 runtime 可写性。Production Backend healthcheck 使用此端点。

先检查 loopback upstream，再检查现有 HTTPS 域名和 Worker：

```bash
curl --fail http://127.0.0.1:8080/
curl --fail http://127.0.0.1:8080/api/v1/health/live
curl --fail http://127.0.0.1:8080/api/v1/health/ready
curl --fail https://esr.example.com/api/v1/health/ready
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" exec -T worker \
  celery -A app.celery_app:celery_app inspect ping
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" ps
```

随后用演示账号完成一次真实业务 smoke：登录、提交一个小型三指标任务、轮询至终态、刷新页面
恢复任务、打开 PNG 风险预览并下载 GeoTIFF。再用第二账号访问该 task ID，必须返回 404；
50 km² 以上任务必须在入队前返回 422。任何一项失败都不得写入 `.last-successful-sha`。

全部通过后才记录成功版本：

```bash
printf '%s\n' "$RELEASE_SHA" > .last-successful-sha
```

## 10. 回滚与恢复演练

应用 smoke 失败但 migration 保持向后兼容时，切回上一 SHA、重建并替换应用容器；不要自动执行
Alembic downgrade：

```bash
git switch --detach "$PREVIOUS_SHA"
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" build
docker compose --env-file .env.production -f compose.production.yml \
  -p "$COMPOSE_PROJECT_NAME" up -d --remove-orphans
```

只有 migration 破坏数据或旧应用确实无法读取新 schema，才在停写后从已验证备份恢复到新建的
空数据库/volume；不要覆盖唯一一份现有 volume。恢复步骤必须先在备份副本演练，并记录开始、
恢复服务、业务 smoke 完成三个时间点，以此计算 RTO 和数据影响。

以下命令只创建新的 restore project，不覆盖生产 named volumes；先在该副本完成 smoke，再决定
后续切换方案：

```bash
export RESTORE_PROJECT="${COMPOSE_PROJECT_NAME}-restore-$(date -u +%Y%m%dT%H%M%SZ)"
docker compose --env-file .env.production -f compose.production.yml \
  -p "$RESTORE_PROJECT" up -d db redis
docker compose --env-file .env.production -f compose.production.yml \
  -p "$RESTORE_PROJECT" cp "$BACKUP_DIR/postgres.dump" db:/tmp/postgres.dump
docker compose --env-file .env.production -f compose.production.yml \
  -p "$RESTORE_PROJECT" exec -T db \
  pg_restore -U "${POSTGRES_USER:-esr}" -d "${POSTGRES_DB:-esr_platform}" \
  --clean --if-exists --no-owner --no-privileges /tmp/postgres.dump
docker run --rm \
  -v "${RESTORE_PROJECT}_runtime_data:/restore" \
  -v "$PWD/$BACKUP_DIR:/backup:ro" alpine:3.20 \
  tar -C /restore -xzf /backup/runtime.tar.gz
```

Worker 重启、Redis 短暂不可用和错误版本回滚演练均使用测试任务；记录任务是否恢复、是否重复
发布成果以及明确终态。演练结果未实际执行前，不得在 README 或简历填写 RTO。

## 11. 数据边界

- `ESR_SOURCE_RASTER_HOST_DIR` 是宿主机 bind mount，在 Backend 和 Worker 中均为
  只读 `/data/source`。
- runtime 输出、PostgreSQL 数据和 Redis 数据分别保存在 Compose named volumes 中；
  普通 `down` 和重新构建 image 不会删除它们。
- named volumes 归属 `esr-platform-next-prod` project；操作时必须持续使用同一个
  `-p` 值。

## 12. 当前限制

仓库提供脱敏 Caddy 示例、Compose 和经审核的手动升级/回滚步骤，但仍不包含：

- CD 或 registry push；
- 远端备份调度与保留策略；
- 服务器真实域名、证书、密码或 SSH 自动化。

这些能力由现有火山引擎/Caddy 环境在仓库范围外提供；本 Runbook 不声称已执行生产升级或
恢复演练，实际证据必须另附日期、SHA、命令输出和脱敏 smoke 结果。

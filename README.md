# LCT-predict-agent · 通用 AI Agent 平台（v0.1.0）

内部人机对话智能助手：自然语言查询销售数据 + 销售预测，全链路可追溯，双端 RBAC（用户端/管理员端），Docker 一键部署。

## 技术栈

FastAPI 3.11+ · PostgreSQL 16（JSONB/GIN）· SQLAlchemy 2 async · Alembic · SSE · JWT 双令牌
React 18 + Vite + TypeScript + Tailwind + ECharts · Docker Compose

## 快速开始

### 本地开发

环境要求：Docker Desktop/Engine、Docker Compose v2、Python 3.11+、uv、Node.js 20+、npm。Windows 推荐在 Git Bash 中执行下面的命令。

#### 一键启动

先准备一次本地开发配置和 PostgreSQL 容器：

```bash
cp backend/.env.example backend/.env

docker run -d \
  --name LCT-predict-agent-pg \
  -p 5432:5432 \
  -e POSTGRES_DB=agent_platform \
  -e POSTGRES_USER=app \
  -e POSTGRES_PASSWORD=app \
  -v pg-project-data:/var/lib/postgresql/data \
  postgres:16-alpine
```

首次需要 mock 销售服务时，再创建其镜像和容器（容器已存在则跳过）：

```bash
docker network inspect sandbox-net >/dev/null 2>&1 || \
  docker network create --driver bridge --subnet=10.0.0.0/24 sandbox-net
docker build -t mock-sales-internal:dev services/mock-sales
docker run -d --name mock-sales --network sandbox-net --ip 10.0.0.2 \
  mock-sales-internal:dev
```

然后用脚本启动 PG 以外的本地联调服务：

```bash
bash scripts/start_dev_stack.sh
```

脚本会启动或复用 `icewash-model`，并强制重启后端 `:8000`、前端 `:5173` 和沙箱 daemon `:9000`；模型镜像来自 `services/icewash-model/Dockerfile.build`。浏览器访问 <http://127.0.0.1:5173>。

停止本地联调进程和基础容器：

```bash
bash scripts/stop_dev_stack.sh
```

本地开发种子管理员默认是 `admin@corp.com` / `LctDevAdmin_2026!`，只适用于开发库。修改 `backend/.env` 后，已有数据库用户不会自动改密，需要单独执行开发库密码重置。

#### 手动启动

```bash
# 从 backend/.env 读取配置，执行 Alembic 迁移和幂等种子
bash scripts/dev_db_pg.sh

# 后端（另开终端）
(cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000)

# 前端（另开终端）
(cd frontend && npm install && npm run dev)
```

Vite 开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。如果需要单独启动沙箱 daemon：

```bash
(cd services/sandbox-daemon && \
  API_INTERNAL_TOKEN=dev_internal_token_001 PYTHONPATH=src \
  uv run python -m sd.main)
```

Git Bash 在 Windows 下运行模型容器的手动命令必须保留 `MSYS_NO_PATHCONV=1`；正常情况下直接使用 `scripts/start_dev_stack.sh`，脚本已经处理了 Windows 路径和 `/app` 工作目录转换。

### 生产 Docker Compose 部署

Compose 会在同一个网络中编排 `db`、`icewash-model`、`api`、`sandbox-daemon` 和 `nginx`；只有 Nginx 对宿主机发布端口，模型、API、PG 和沙箱均使用内部网络。生产 Compose 不启动 `mock-sales`，该服务只用于本地联调。

#### 首次部署

```bash
cp .env.example .env
# 编辑 .env，至少替换 POSTGRES_PASSWORD、JWT_SECRET、API_INTERNAL_TOKEN、ADMIN_INITIAL_PASSWORD

# 先做 Compose 静态校验，再构建并启动
docker compose --env-file .env config -q
docker compose --env-file .env up -d --build
docker compose --env-file .env ps
```

`POSTGRES_PASSWORD` 会被拼进 API 和 icewash 的 PostgreSQL 连接串，请使用 URL-safe 字符；需要公网访问时，建议在前置负载均衡器终止 TLS，并将 `NGINX_PORT` 设置为实际监听端口。

启动检查：

```bash
curl -fsS http://127.0.0.1/readyz
curl -fsS http://127.0.0.1/healthz
docker compose --env-file .env ps
```

`api` 启动时会依次执行迁移、v1/v2 幂等种子，再启动 Uvicorn；`WORKBENCH_SYNC_ON_STARTUP=true` 会通过 icewash 的内部参考数据接口初始化工作台数据。

#### 日常运维

```bash
# 查看启动失败原因或实时日志
docker compose --env-file .env logs --tail=200 api icewash-model nginx sandbox-daemon
docker compose --env-file .env logs -f api icewash-model nginx

# 发布新版本：拉取代码后重建并滚动替换容器
git pull
docker compose --env-file .env build --pull
docker compose --env-file .env up -d

# 停止服务但保留 PG 数据卷
docker compose --env-file .env down

# 仅在明确要删除数据库数据时执行；会删除 pgdata 和 icewash-log
docker compose --env-file .env down -v
```

数据库默认保存在 Compose named volume `pgdata`，生产环境应另外配置定期备份。例如：

```bash
docker compose --env-file .env exec -T db \
  pg_dump -U app -d agent_platform > backups/agent_platform_$(date +%Y%m%d_%H%M%S).sql
```

#### Docker 文件核验

| 文件 | 用途 | 结论 |
|---|---|---|
| `docker-compose.yml` | 生产编排、健康检查、迁移/种子顺序 | 已接入 icewash；API 使用 `icewash-model:8000`，不再使用容器内回环地址 |
| `frontend/Dockerfile` + `frontend/nginx.conf` | React/Vite 构建、SPA 回退、API 反代 | 已补齐；`/api/chat/stream` 关闭 Nginx buffering |
| `backend/Dockerfile` | 后端依赖和应用镜像 | 构建失败会直接退出，不再用 `|| true` 掩盖依赖问题 |
| `services/icewash-model/Dockerfile.build` | 可移植的模型生产镜像 | Compose 使用此文件；构建上下文是 `services/icewash-model` |
| `services/icewash-model/cbg_fcst_month/Dockerfile` | 内部基础镜像变体 | 依赖企业内部基础镜像，不作为默认 Compose 入口 |
| `services/sandbox-daemon/Dockerfile` | 生产沙箱 daemon | Compose 通过只读 Docker socket 运行，端口仅在内部网络暴露 |
| `services/mock-sales/Dockerfile` | 本地 mock 销售服务 | 仅首次本地联调手动创建，不进入生产 Compose |
| `tools/*/Dockerfile` | 沙箱工具运行时镜像 | 由 daemon 按工具配置使用，不是 Compose 常驻服务 |

根目录 `.env.example` 只服务生产 Compose；`backend/.env.example` 只服务源码本地开发。仓库没有 `scripts/verify_up.sh`，部署验收以 `config -q`、`/readyz`、`/healthz` 和 `docker compose ps` 为准。


## 目录
```
backend/            FastAPI 应用（api/auth/rbac/chat/engine/tools/sandbox/datasource/llm/tracing/sse/…）
services/           独立运行的服务（sandbox-daemon / mock-sales / icewash-model）
  sandbox-daemon/   沙箱服务（/run /warm /healthz；受限容器 + 白名单出网 + tool_runtime）
  mock-sales/       联调 mock 销售数据/预测服务
  icewash-model/    冰洗预测模型（真实预测服务）
tools/              默认业务工具（query_sales_data / predict_sales，沙箱内执行）
frontend/           单一 SPA（用户端工作台 + 管理员端六页）
docs/               PRD / tech_design / todo / plans / progress
```

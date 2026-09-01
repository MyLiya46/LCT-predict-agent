# LCT-predict-agent · 通用 AI Agent 平台（P0）

内部人机对话智能助手：自然语言查询销售数据 + 销售预测，全链路可追溯，双端 RBAC（用户端/管理员端），Docker 一键部署。

## 技术栈

FastAPI 3.11+ · PostgreSQL 16（JSONB/GIN）· SQLAlchemy 2 async · Alembic · SSE · JWT 双令牌
Vue 3 + Vite + TS + Element Plus + ECharts · Docker Compose

## 快速开始

### 本地开发

**环境要求**

```plain text
docker
```

**环境变量**

```bash
cd backend
cp .env.example .env
```

**数据库**

```bash
docker run -d \
  --name LCT-predict-agent-pg \
  -p 5432:5432 \
  -e POSTGRES_DB=agent_platform \
  -e POSTGRES_USER=app \
  -e POSTGRES_PASSWORD=app \
  -v pg-project-data:/var/lib/postgresql/data \
  postgres:16-alpine
```

**后端**

```bash
# 数据库迁移(可选)              # 在连好的 postgres:16 上执行Alembic 迁移 + 幂等种子（可重复运行）
bash scripts/dev_db_pg.sh 
# 启动后端
cd backend && uv run uvicorn app.main:app --port 8000
```

**前端**

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173，/api 反代到 :8000
```

**联调组件（工具执行依赖）**

```bash
# 1. 起容器（数据库 + mock 数据服务 + 冰洗模型）
docker start LCT-predict-agent-pg mock-sales icewash-model

# 2. 起沙箱 daemon（:9000，后台常驻）
cd services/sandbox-daemon
PYTHONPATH=src API_INTERNAL_TOKEN=dev_internal_token_001 nohup uv run python -m sd.main > /tmp/lct_sd_daemon.log 2>&1 &

```

首次搭建（容器/镜像不存在时）：

```bash
docker network create --driver bridge --subnet=10.0.0.0/24 sandbox-net
docker build -t mock-sales-internal:dev services/mock-sales
docker build -f services/icewash-model/Dockerfile.build -t icewash-model:dev services/icewash-model
docker run -d --name mock-sales --network sandbox-net --ip 10.0.0.2 mock-sales-internal:dev
docker run -d --name icewash-model --network sandbox-net --ip 10.0.0.3 -p 8002:8000 icewash-model:dev
```

### Docker Compose 一键部署
```bash
cp .env.example .env  # 填 JWT_SECRET / API_INTERNAL_TOKEN / POSTGRES_PASSWORD
docker compose up -d --build   # db → api(迁移+种子) → sandbox-daemon → nginx
curl http://localhost/api/v1/healthz
./scripts/verify_up.sh docker
```
- `db` 服务与本地开发用同一镜像 `postgres:16-alpine`，默认用户/库名与 `.env.example` 一致；数据持久化在 named volume `pgdata`（默认开启）。compose 内 `db` 不暴露 5432 端口（避免与本地 dev PG 冲突）；prod 如需直连，`docker exec -it <container> psql -U app -d agent_platform`。


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

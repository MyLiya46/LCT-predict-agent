# LCT-predict-agent 后端

通用 AI Agent 平台后端（FastAPI + SQLAlchemy 2 async + PostgreSQL 15）。

结构（tech_design §8）：
- `src/app/` 应用代码（api / auth / rbac / chat / engine / tools / sandbox / datasource / llm / tracing / sse / config / models / background / middleware / utils）
- `alembic/` 数据库迁移
- `seed/` 幂等种子脚本
- `tests/` pytest 测试

开发运行：
```bash
uv sync
uv run uvicorn app.main:app --port 8000        # 从 backend 目录，需 src 在 path
```
（骨架期仅 `/healthz`；完整装配 T18。）
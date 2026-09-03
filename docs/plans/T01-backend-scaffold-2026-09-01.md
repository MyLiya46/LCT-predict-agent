# T01 · 后端壳就位（backend-scaffold）

- 任务 ID：T01
- **标题与目标**：把 `reference_repo/predict-agent/backend-backup` 原样复制为根目录 `backend/`，清理构建/运行产物，确认 PG + alembic 建表 + 25 个快速测试基线全绿，作为后续所有后端任务的唯一工作区。
- **关联文档章节**：feat-icewash.md §10.2（后端以 backup 为壳）；
- 前置依赖 blockedBy：无

## 问题
- 任务 T01 当前需要完成本计划标题对应的交付；旧版计划结构无法被 plan-generator v1.2.0 的结构化校验直接读取。

## 决策
- 保留本计划既有技术边界、参数、实施内容和验收命令；仅补齐 v1.2.0 要求的元数据、章节与结构化执行入口。

## 范围
- 包含：本计划既有实施要点、涉及路径、接口、数据约束和验收项。
- 不包含：改变任务目标、blockedBy 依赖、代码实现或项目业务口径。

## 风险与回滚
- 风险：旧计划正文中的命令或外部服务依赖可能在执行环境中不可用，导致该任务验收失败。
- 回滚：执行前保存本任务涉及文件的补丁；失败时使用 `git apply -R /tmp/T01-plan.patch` 反向应用补丁并恢复前一阶段。

## 实施步骤

### 步骤 1：执行原计划实施内容
- 对象：T01 对应的目标模块、接口和验收对象。
- 动作：按下方保留的原实施内容执行，并使用其中的命令完成验证。
- 参数：严格使用正文中给出的路径、端口、字段、超时、权限和命令参数。
- 文件：docs/plans/T01-backend-scaffold-2026-09-01.md
- 命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T01-backend-scaffold-2026-09-01.md
  ```
#### 1. 复制壳目录（排除运行时产物）
- 复制 `reference_repo/predict-agent/backend-backup/` → `backend/`，排除：`.venv/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.pytest_tmp/`、`*.pyc`、`trace_dump.json`、`check_all.txt`、`check_msg.txt`、`msg_test.txt`、`uv.lock`（由 `uv sync` 重新生成）。
- 在 Windows Git Bash 执行（本机）：
  ```bash
  mkdir -p backend && rsync -a --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
    --exclude '.ruff_cache' --exclude '.pytest_tmp' --exclude 'trace_dump.json' \
    --exclude 'check_all.txt' --exclude 'check_msg.txt' --exclude 'msg_test.txt' \
    reference_repo/predict-agent/backend-backup/ backend/
  ```
  （无 rsync 则 `cp -r` 后手动 `find backend -name __pycache__ -type d -exec rm -rf`。）

#### 2. 环境文件
- `backend-ref` 没有 `.env` 或 `.env.example` 文件，因此以它的 `app/config.py` `Settings` 字段作为环境变量来源；`backend-backup/.env` 与 `backend-backup/.env.example` 作为 backup 环境文件来源。
- 以 `backend-backup/.env.example` 为模板，在 `backend/.env.example` 中补齐 backend-ref 配置字段对应的全部键；已存在的同名键保留 backup 的名称、默认值和语义。未使用、兼容旧版或已废弃字段也保留并注明来源，不删除键。
- 合并范围至少覆盖：backup 的 PG/JWT/RBAC/沙箱/LLM/内部服务键，以及 ref 的 `AGENT_*`、`OAUTH_*`、`TURING_*`、`ANALYSIS_AGENT_ENABLED`、`PLANNER_*`、`MEMORY_*`、`MCP_*`、`FORECAST_MODEL_*`、`CORS_ORIGINS` 和 `OAUTH_DEVICE_ID/OAUTH_PASSWORD`。
- 同名冲突以 backup 为准；特别是 `DATABASE_URL` 使用 `postgresql+asyncpg://app:app@127.0.0.1:5432/agent_platform`，不得采用 backend-ref 的 `sqlite+aiosqlite`。所有预测模型与 LLM/OAuth 地址、超时和开关字段均在同一份 `.env.example` 中出现。
- 从合并后的 `backend/.env.example` 复制生成唯一的 `backend/.env`，填入本地开发值：`JWT_SECRET`（≥32 字节随机串）、`API_INTERNAL_TOKEN=dev_internal_token_001`、`ADMIN_INITIAL_EMAIL` 和 `ADMIN_INITIAL_PASSWORD`；空密钥字段保持为空，不把真实密钥写入计划或版本库。
- `backend/` 内最终只允许存在根级 `backend/.env` 与 `backend/.env.example` 两个环境文件，不保留嵌套或重复环境文件。

#### 3. 起 PG + 迁移 + 种子
- 若 PG 未起：`docker run -d --name LCT-predict-agent-pg -p 5432:5432 -e POSTGRES_DB=agent_platform -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -v pg-data:/var/lib/postgresql/data postgres:16-alpine`
- `cd backend && uv sync`（生成 `.venv` 与 `uv.lock`）。
- 回到仓库根目录执行 `bash scripts/dev_db_pg.sh`；脚本负责等待 PostgreSQL 就绪、执行当前 Alembic head 迁移并运行幂等种子（T03 增加 0003 前应落到 0002）。

#### 4. 基线测试
- 在 `backend/` 内执行快速壳测试：`uv run pytest -q tests/test_config.py tests/test_errors.py tests/test_dashboard_spec.py tests/test_llm.py tests/test_sse.py`；这 5 个文件只验证配置、统一异常、看板 spec、LLM OpenAI 兼容流解析和 SSE hub，不触发 `db_session_factory` 的 PG schema 重建。
- 完整后端测试不纳入 T01；后续新增能力测试与最终全量回归在对应计划和 T15 执行。

## 完成标准
- 验收命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T01-backend-scaffold-2026-09-01.md
  ```
- 通过条件：命令退出码为 0，且本节保留的原验收项全部满足。
- [ ] `bash scripts/start_dev_stack.sh` 后端部分不报缺 `backend/` 目录；`curl -s http://127.0.0.1:8000/healthz` 返回 200。
- [ ] `cd backend && uv run pytest -q tests/test_config.py tests/test_errors.py tests/test_dashboard_spec.py tests/test_llm.py tests/test_sse.py` 成功退出（预期 25 个快速测试通过），且无缺文件或依赖导入失败。
- [ ] Git Bash 执行 `find backend -type f \( -name .env -o -name .env.example \) | sort` 只输出 `backend/.env` 与 `backend/.env.example`；`grep -E '^DATABASE_URL=' backend/.env.example` 返回 PostgreSQL asyncpg 地址。
- [ ] `grep -rn "__pycache__\|\.pytest_cache" backend/src` 无构建产物残留；`backend/.venv` 由 `uv sync` 生成。
- [ ] `uv run alembic current` 显示 `0002_conversation_pin`（head），与 backup 迁移一致。

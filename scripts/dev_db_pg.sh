#!/usr/bin/env bash
# =====================================================================
# 本地开发：PostgreSQL 开发库初始化（建库 + Alembic 迁移 + 幂等种子）
#
# 前提：已按 README「本地开发 → 数据库」用 docker run 拉起 postgres:16-alpine。
# 本脚本只面向后端源码（backend/），不经 Docker：挨个重试两次 = 给容器冷启动留缓冲。
# 只需 .env 已就位（DATABASE_URL 等），不需要设 POSTGRES_* 环境变量。
#
# 用法：bash scripts/dev_db_pg.sh
# =====================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

# 1) 迁移前多试几次：上面那条 docker run 的 PG 首次冷启动可能要几秒
MIGRATE_OK=0
for i in 1 2 3 4 5; do
  if uv run alembic upgrade head 2>/dev/null; then
    MIGRATE_OK=1
    break
  fi
  echo "[dev-db] PG 未就绪，${i}/5 重试（等待 2s）…"
  sleep 2
done
if [ "$MIGRATE_OK" -ne 1 ]; then
  echo "[dev-db] 首次运行请先执行：docker run -d --name LCT-predict-agent-pg -p 5432:5432 ..." >&2
  echo "[dev-db] （或检查 .env 的 DATABASE_URL）" >&2
  exit 1
fi

# 2) 幂等种子（角色/权限/默认场景/system_config/管理员）= tech_design §4.3
uv run python -m seed.v1__base_seed
echo "[dev-db] postgres dev db ready: migration + seed done"
#!/usr/bin/env bash
# LCT-predict-agent 本地联调栈一键启动（dev，Windows git-bash / Linux 通用）
#
# 解决的问题：沙箱 daemon 是独立进程，Claude Code / 终端会话结束会被杀掉，
# 导致工具执行全部失败（后端 /healthz 显示 sandbox_daemon: unreachable）。
# 跑这个脚本即可全部恢复。
#
# 用法：bash scripts/start_dev_stack.sh
# 启动后：后端 :8000、前端 :5173、daemon :9000、PG/mock/冰洗容器
#
# 语义：
#   - Docker 容器（PG/mock/冰洗）：检已有运行就不动，没运行才拉起；PG 就绪后自动补迁移 + 种子
#   - 后端 / 前端 / 沙箱 daemon：每次强制重启（杀旧进程 → 重新拉起）
set -e
cd "$(dirname "$0")/.."

LOG_DIR="${TMPDIR:-/tmp}"

# 杀掉占用某端口的进程（Windows git-bash / Linux 通用），供「重启」使用
kill_port() {
  local port="$1" pid
  if uname -s | grep -qiE 'MINGW|MSYS|CYGWIN'; then
    # Windows：netstat 找监听该端口的 PID → taskkill 整棵进程树
    pid=$(netstat -ano | grep -E ":$port\b" | grep -i LISTENING | awk '{print $NF}' | head -n1)
    if [ -n "$pid" ]; then
      taskkill //PID "$pid" //F //T >/dev/null 2>&1
    fi
  else
    # Linux：lsof / fuser 找 PID → kill
    pid=$(lsof -ti tcp:"$port" 2>/dev/null | head -n1)
    [ -z "$pid" ] && pid=$(fuser "$port"/tcp 2>/dev/null | grep -oE '[0-9]+' | head -n1)
    if [ -n "$pid" ]; then
      kill -9 $pid >/dev/null 2>&1
    fi
  fi
}

echo "==> [1/6] Docker 引擎"
docker info >/dev/null 2>&1 || { echo "   Docker 未启动，请先打开 Docker Desktop 再重试"; exit 1; }
echo "   OK"

echo "==> [2/6] 基础容器（PG / mock 销售服务 / 冰洗模型）"
for c in LCT-predict-agent-pg mock-sales icewash-model; do
  if docker ps --format '{{.Names}}' | grep -qx "$c"; then
    echo "   $c 运行中"
  elif docker ps -a --format '{{.Names}}' | grep -qx "$c"; then
    docker start "$c" >/dev/null
    echo "   $c 已启动"
  else
    echo "   !! $c 容器不存在（首次需手动执行 bash scripts/dev_db_pg.sh 里 docker run 创建，见 README「首次搭建」）"
  fi
done

# PG 就绪后自动补迁移 + 种子（幂等；空库/换库后由 backend/.env 的 DATABASE_URL 决定目标）
if grep -q "^DATABASE_URL" backend/.env 2>/dev/null; then
  echo "   → 补 Alembic 迁移 + 种子（幂等）"
  bash scripts/dev_db_pg.sh
else
  echo "   !! 未找到 backend/.env 的 DATABASE_URL，跳过迁移 + 种子（后端将因缺库而失败）"
fi

echo "==> [3/6] 后端（:8000，重启）"
kill_port 8000
sleep 1
(cd backend && nohup uv run uvicorn app.main:app --port 8000 \
  > "$LOG_DIR/lct_backend.log" 2>&1 &)
echo "   已重启（日志 $LOG_DIR/lct_backend.log）"
sleep 5

echo "==> [4/6] 前端（:5173，重启）"
kill_port 5173
sleep 1
(cd frontend && nohup npm run dev \
  > "$LOG_DIR/lct_frontend.log" 2>&1 &)
echo "   已重启（日志 $LOG_DIR/lct_frontend.log）"
sleep 5

echo "==> [5/6] 沙箱 daemon（:9000，重启）"
kill_port 9000
sleep 1
cd services/sandbox-daemon
MSYS_NO_PATHCONV=1 PYTHONPATH=src \
  API_INTERNAL_TOKEN=dev_internal_token_001 \
  TOOL_BASE_IMAGE=agent-tools/tool-runtime-base:latest \
  WHITELIST_CIDRS=10.0.0.0/8,192.168.0.0/16 \
  SANDBOX_TIMEOUT_S=30 \
  nohup uv run python -m sd.main > "$LOG_DIR/lct_sd_daemon.log" 2>&1 &
DAEMON_PID=$!
cd ..
echo "   已重启（PID $DAEMON_PID，日志 $LOG_DIR/lct_sd_daemon.log）"
sleep 5

echo "==> [6/6] 健康检查"
BACKEND=$(curl -s --max-time 5 http://127.0.0.1:8000/healthz 2>/dev/null || echo "")
if [ -n "$BACKEND" ]; then
  echo "   后端 :8000 → $BACKEND"
else
  echo "   后端未运行 → 见 $LOG_DIR/lct_backend.log"
fi
FRONTEND=$(curl -s --max-time 5 http://127.0.0.1:5173 2>/dev/null && echo "OK" || echo "")
[ -n "$FRONTEND" ] && echo "   前端 :5173 → $FRONTEND" || echo "   前端未运行 → 见 $LOG_DIR/lct_frontend.log"
DAEMON=$(curl -s --max-time 5 http://127.0.0.1:9000/healthz 2>/dev/null || echo "")
echo "   daemon :9000 → $DAEMON"

echo "==> 完成。浏览器打开 http://127.0.0.1:5173，聊天里输入「帮我看下最近数据」即可验证。"
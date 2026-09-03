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

if command -v uv >/dev/null 2>&1; then
  UV_BIN="uv"
elif command -v uv.exe >/dev/null 2>&1; then
  UV_BIN="uv.exe"
else
  echo "uv/uv.exe 未找到，请先安装 uv"
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  DOCKER_BIN="docker"
elif command -v docker.exe >/dev/null 2>&1 && docker.exe info >/dev/null 2>&1; then
  DOCKER_BIN="docker.exe"
else
  echo "docker/docker.exe 未找到或 Docker Desktop 未启动"
  exit 1
fi

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
"$DOCKER_BIN" info >/dev/null 2>&1 || { echo "   Docker 未启动，请先打开 Docker Desktop 再重试"; exit 1; }
echo "   OK"

echo "==> [2/6] 基础容器（PG / mock 销售服务 / 冰洗模型）"
ICEWASH_MODEL_MOUNT="$(pwd)/services/icewash-model:/app"
for c in LCT-predict-agent-pg mock-sales; do
  if "$DOCKER_BIN" ps --format '{{.Names}}' | grep -qx "$c"; then
    echo "   $c 运行中"
  elif "$DOCKER_BIN" ps -a --format '{{.Names}}' | grep -qx "$c"; then
    "$DOCKER_BIN" start "$c" >/dev/null
    echo "   $c 已启动"
  else
    echo "   !! $c 容器不存在（首次需手动执行 bash scripts/dev_db_pg.sh 里 docker run 创建，见 README「首次搭建」）"
  fi
done

# icewash-model must be rebuilt from the checked-in requirements and must
# reach the host PG used by the local backend.  A stale container can have
# psycopg2 only because it came from an unrelated base image, or can point at
# 127.0.0.1 inside its own network namespace; both cases make the real relay
# acceptance silently fail.  The container is disposable: generated files and
# task_store.sqlite3 live on the host mount and are therefore preserved.
MODEL_IMAGE="icewash-model:dev"
MODEL_PG_URL="${BACKEND_PG_URL:-postgresql+psycopg2://app:app@host.docker.internal:5432/agent_platform}"
if ! "$DOCKER_BIN" image inspect "$MODEL_IMAGE" >/dev/null 2>&1; then
  echo "   构建 $MODEL_IMAGE（含 psycopg2-binary）"
  "$DOCKER_BIN" build -f services/icewash-model/Dockerfile.build -t "$MODEL_IMAGE" services/icewash-model
fi

MODEL_RECREATE=0
if ! "$DOCKER_BIN" inspect icewash-model >/dev/null 2>&1; then
  MODEL_RECREATE=1
else
  if ! "$DOCKER_BIN" inspect icewash-model --format '{{range .Mounts}}{{if eq .Destination "/app"}}ok{{end}}{{end}}' | grep -q '^ok$'; then
    MODEL_RECREATE=1
  fi
  if ! "$DOCKER_BIN" inspect icewash-model --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -q '^BACKEND_PG_URL='; then
    MODEL_RECREATE=1
  fi
  if ! "$DOCKER_BIN" exec icewash-model python -c 'import psycopg2' >/dev/null 2>&1; then
    MODEL_RECREATE=1
  fi
fi

if [ "$MODEL_RECREATE" -eq 1 ]; then
  if "$DOCKER_BIN" inspect icewash-model >/dev/null 2>&1; then
    "$DOCKER_BIN" rm -f icewash-model >/dev/null
    echo "   已移除旧 icewash-model 容器"
  fi
  "$DOCKER_BIN" run -d --name icewash-model \
    --add-host host.docker.internal:host-gateway \
    -e "BACKEND_PG_URL=$MODEL_PG_URL" \
    -p 8001:8001 \
    -v "$ICEWASH_MODEL_MOUNT" \
    -w /app/cbg_fcst_month \
    "$MODEL_IMAGE" \
    uvicorn server:app --host 0.0.0.0 --port 8001 >/dev/null
  echo "   icewash-model 已按新镜像重建并启动"
else
  if ! "$DOCKER_BIN" ps --format '{{.Names}}' | grep -qx icewash-model; then
    "$DOCKER_BIN" start icewash-model >/dev/null
    echo "   icewash-model 已启动"
  else
    echo "   icewash-model 运行中（依赖/PG/挂载检查通过）"
  fi
fi

# PG 就绪后自动补迁移 + 种子（幂等；空库/换库后由 backend/.env 的 DATABASE_URL 决定目标）
if grep -q "^DATABASE_URL" backend/.env 2>/dev/null; then
  echo "   → 补 Alembic 迁移 + 种子（幂等）"
  bash scripts/dev_db_pg.sh
else
  echo "   !! 未找到 backend/.env 的 DATABASE_URL，跳过迁移 + 种子（后端将因缺库而失败）"
fi

echo "==> [3/7] 冰洗模型健康检查（:8001）"
MODEL_HEALTH=""
MODEL_READY=0
for i in $(seq 1 30); do
  MODEL_HEALTH=$(curl -s --max-time 5 http://127.0.0.1:8001/health 2>/dev/null || echo "")
  if echo "$MODEL_HEALTH" | grep -q 'status.*healthy'; then
    MODEL_READY=1
    echo "   OK（第 $i 次检查）"
    break
  fi
  sleep 2
done
if [ "$MODEL_READY" -ne 1 ]; then
  echo "   冰洗模型未达到 health.status=healthy，未启动 backend"
  echo "   请检查 Docker 容器 icewash-model 或 $LOG_DIR/lct_icewash_model.log"
  exit 1
fi

echo "==> [4/7] 后端（:8000，重启）"
kill_port 8000
sleep 1
(cd backend && WORKBENCH_SYNC_ON_STARTUP=1 FORECAST_MODEL_BASE_URL=http://127.0.0.1:8001 nohup "$UV_BIN" run uvicorn app.main:app --port 8000 \
  > "$LOG_DIR/lct_backend.log" 2>&1 &)
echo "   已重启（日志 $LOG_DIR/lct_backend.log）"
sleep 5

echo "==> [5/7] 前端（:5173，重启）"
kill_port 5173
sleep 1
(cd frontend && nohup npm run dev \
  > "$LOG_DIR/lct_frontend.log" 2>&1 &)
echo "   已重启（日志 $LOG_DIR/lct_frontend.log）"
sleep 5

echo "==> [6/7] 沙箱 daemon（:9000，重启）"
kill_port 9000
sleep 1
cd services/sandbox-daemon
MSYS_NO_PATHCONV=1 PYTHONPATH=src \
  API_INTERNAL_TOKEN=dev_internal_token_001 \
  TOOL_BASE_IMAGE=agent-tools/tool-runtime-base:latest \
  WHITELIST_CIDRS=10.0.0.0/8,192.168.0.0/16 \
  SANDBOX_TIMEOUT_S=30 \
  nohup "$UV_BIN" run python -m sd.main > "$LOG_DIR/lct_sd_daemon.log" 2>&1 &
DAEMON_PID=$!
cd ..
echo "   已重启（PID $DAEMON_PID，日志 $LOG_DIR/lct_sd_daemon.log）"
sleep 5

echo "==> [7/7] 健康检查"
BACKEND=""
for i in $(seq 1 15); do
  BACKEND=$(curl -s --max-time 5 http://127.0.0.1:8000/healthz 2>/dev/null || echo "")
  if echo "$BACKEND" | grep -q '"status":"ok"'; then break; fi
  sleep 1
done
if [ -n "$BACKEND" ]; then
  echo "   后端 :8000 → $BACKEND"
else
  echo "   后端未运行 → 见 $LOG_DIR/lct_backend.log"
fi

FRONTEND=""
for i in $(seq 1 15); do
  FRONTEND=$(curl -s --max-time 5 http://127.0.0.1:5173 2>/dev/null || echo "")
  if [ -n "$FRONTEND" ]; then break; fi
  sleep 1
done
[ -n "$FRONTEND" ] && echo "   前端 :5173 → OK" || echo "   前端未运行 → 见 $LOG_DIR/lct_frontend.log"

DAEMON=""
for i in $(seq 1 15); do
  DAEMON=$(curl -s --max-time 5 http://127.0.0.1:9000/healthz 2>/dev/null || echo "")
  if echo "$DAEMON" | grep -q '"status":"ok"'; then break; fi
  sleep 1
done
echo "   daemon :9000 → $DAEMON"

echo "==> 完成。浏览器打开 http://127.0.0.1:5173，聊天里输入「帮我看下最近数据」即可验证。"

#!/usr/bin/env bash
# LCT-predict-agent 本地联调栈一键停止（dev，Windows git-bash / Linux 通用）
#
# 与 scripts/start_dev_stack.sh 一一对应：停掉后端 :8000、前端 :5173、
# 沙箱 daemon :9000，并停止 Docker 基础容器（PG / mock / 冰洗）。
#
# 用法：bash scripts/stop_dev_stack.sh
#
# 语义：
#   - 后端 / 前端 / 沙箱 daemon：按端口杀掉监听进程（整棵进程树）
#   - Docker 容器（PG/mock/冰洗）：已运行则 docker stop，未运行则跳过
set -e
cd "$(dirname "$0")/.."

# 杀掉占用某端口的进程（与 start 脚本的 kill_port 一致）
kill_port() {
  local port="$1" pid
  if uname -s | grep -qiE 'MINGW|MSYS|CYGWIN'; then
    pid=$(netstat -ano | grep -E ":$port\b" | grep -i LISTENING | awk '{print $NF}' | head -n1)
    if [ -n "$pid" ]; then
      taskkill //PID "$pid" //F //T >/dev/null 2>&1
    fi
  else
    pid=$(lsof -ti tcp:"$port" 2>/dev/null | head -n1)
    [ -z "$pid" ] && pid=$(fuser "$port"/tcp 2>/dev/null | grep -oE '[0-9]+' | head -n1)
    if [ -n "$pid" ]; then
      kill -9 $pid >/dev/null 2>&1
    fi
  fi
}

# 探测服务是否还活着（返回 0 = 仍在运行）
alive() {
  curl -s --max-time 3 "$1" >/dev/null 2>&1
}

echo "==> [1/4] 后端（:8000）"
kill_port 8000
sleep 1
alive http://127.0.0.1:8000/healthz && echo "   !! 仍在运行" || echo "   已停止"

echo "==> [2/4] 前端（:5173）"
kill_port 5173
sleep 1
alive http://127.0.0.1:5173 && echo "   !! 仍在运行" || echo "   已停止"

echo "==> [3/4] 沙箱 daemon（:9000）"
kill_port 9000
sleep 1
alive http://127.0.0.1:9000/healthz && echo "   !! 仍在运行" || echo "   已停止"

echo "==> [4/4] 基础容器（PG / mock 销售服务 / 冰洗模型）"
for c in LCT-predict-agent-pg mock-sales icewash-model; do
  if docker ps --format '{{.Names}}' | grep -qx "$c"; then
    docker stop "$c" >/dev/null
    echo "   $c 已停止"
  else
    echo "   $c 未在运行"
  fi
done

echo "==> 完成。需恢复时运行 bash scripts/start_dev_stack.sh"
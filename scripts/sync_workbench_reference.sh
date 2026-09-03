#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v uv >/dev/null 2>&1; then
  UV_BIN="uv"
elif command -v uv.exe >/dev/null 2>&1; then
  UV_BIN="uv.exe"
else
  echo "uv/uv.exe 未找到，请先安装 uv" >&2
  exit 1
fi

cd backend
exec "$UV_BIN" run python -m app.seed_workbench --reference-only

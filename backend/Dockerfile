# LCT-predict-agent 后端镜像（T01 骨架；完整 CMD 装配见 T24）
FROM python:3.11-slim

# uv 安装
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 先拷贝依赖清单以利用构建缓存
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || true

# 拷贝源码
COPY src/ src/
COPY alembic/ alembic/
COPY seed/ seed/
COPY alembic.ini .

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# 真正 entrypoint（迁移+种子+启动）在 T24 与 docker-compose 对齐
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
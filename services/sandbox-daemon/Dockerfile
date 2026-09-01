# sandbox-daemon 镜像（T24 / tech_design §7.1）：Linux host 上运行，持 docker.sock 与 NET_ADMIN
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io iptables curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir . || pip install --no-cache-dir fastapi "uvicorn[standard]" pydantic docker

ENV PYTHONUNBUFFERED=1
EXPOSE 9000
CMD ["python", "-m", "sd.main"]
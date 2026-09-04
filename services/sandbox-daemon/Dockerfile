# sandbox-daemon 镜像：Linux host 上运行，持 docker.sock 与 NET_ADMIN。
# 只复制 Docker CLI，不安装 docker.io（后者会额外拉取 containerd/runc，显著放大
# 构建体积和对 Debian 源的依赖；实际 daemon 通过宿主机 docker.sock 工作）。
ARG DOCKER_CLI_IMAGE=docker:cli
FROM ${DOCKER_CLI_IMAGE} AS docker-cli

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iptables curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
EXPOSE 9000
CMD ["python", "-m", "sd.main"]

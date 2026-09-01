# predict_sales 工具镜像（T12）
FROM agent-tools/tool-runtime-base:latest
WORKDIR /opt/tools
COPY tool.py ./tools/predict_sales.py
COPY schema.json execution.json ./
ENV TOOL_CACHE_DIR=/opt/tools
ENTRYPOINT ["python", "-m", "tool_runtime", "--handler", "predict_sales"]
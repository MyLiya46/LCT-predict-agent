# query_sales_data 工具镜像（T12 / tech_design §3.7 基座 + 工具代码叠加）
FROM agent-tools/tool-runtime-base:latest
WORKDIR /opt/tools
COPY tool.py ./tools/query_sales_data.py
COPY schema.json execution.json ./
ENV TOOL_CACHE_DIR=/opt/tools
ENTRYPOINT ["python", "-m", "tool_runtime", "--handler", "query_sales_data"]
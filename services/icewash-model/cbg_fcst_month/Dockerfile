# 使用官方Python运行时作为基础镜像
FROM tone.tcl.com/devops/docker/release/bigdata-ai/python:3.10

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 安装系统依赖
#RUN apt-get update && apt-get install -y \
#    curl \
#    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install  -r requirements.txt  -i https://pypi.mirrors.ustc.edu.cn/simple/

# 复制应用代码
COPY . .

# 创建非root用户（安全考虑）
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]
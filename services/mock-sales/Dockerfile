# mock 内部业务服务镜像（联调用：销售数据查询 + 预测 mock，sandbox-net 10.0.0.2:8000）
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ fastapi "uvicorn[standard]"
COPY mock_internal.py /app/mock_internal.py
CMD ["uvicorn", "mock_internal:app", "--host", "0.0.0.0", "--port", "8000"]

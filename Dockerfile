# ===== 财通Agent 后端 Dockerfile =====
# 构建上下文：项目根目录（PYTHONPATH 需要 backend.app 可导入）

FROM python:3.11-slim

WORKDIR /app

# 系统依赖（akshare / baostock 编译可能需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目源码
COPY . .

ENV PYTHONPATH=/app
EXPOSE 8001

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8001"]

# ===== 财通Agent 后端 Dockerfile =====
# 构建上下文：项目根目录（PYTHONPATH 需要 backend.app 可导入）

FROM python:3.11-slim

WORKDIR /app

# 国内服务器构建：换 Debian 源，避免 apt 卡在 deb.debian.org
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# 多数 Python 包有预编译 wheel，一般不必装 gcc；若 pip 报编译错误再取消下面注释
# RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ \
#     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

ENV PYTHONPATH=/app
EXPOSE 8001

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8001"]

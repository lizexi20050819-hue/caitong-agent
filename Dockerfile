# ===== 财通Agent 后端 Dockerfile =====
# 不跑 apt-get，避免国内卡在 deb.debian.org；依赖均用 pip 预编译 wheel

FROM python:3.11-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

ENV PYTHONPATH=/app
EXPOSE 8001

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8001"]

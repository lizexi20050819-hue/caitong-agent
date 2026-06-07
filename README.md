# 财通Agent — A 股 LLM 投研助手

自研 **LLM Agent**：用户用自然语言提问，Agent 自主编排工具拉取真实数据，支持多轮追问，输出 Markdown 研报式结论。

投研维度与 fetcher 设计**参考** [UZI-Skill](https://github.com/wbh604/UZI-Skill)，主应用独立实现，**运行时不会调用** `skill/` 目录。

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11 + FastAPI + Function Calling（DeepSeek / OpenAI 兼容） |
| 工具层 | LangChain `@tool`，12 个领域工具 |
| 数据 | akshare、baostock、东方财富（`backend/app/services/fetchers/`） |
| 前端 | **Vue 3 + Vite**（主）；Streamlit（旧版保留） |
| 会话 | SQLite（`data/sessions.db`），按访客 Cookie 隔离 |

> 本项目为研究辅助工具，不构成任何投资建议。

---

## 架构概览

```text
用户浏览器（Vue SPA）
       │  /api/* 同源（开发：Vite proxy；生产：Nginx 反代）
       ▼
  FastAPI 后端 :8001
       │
       ▼
  Agent 循环（首轮最多 6 轮，追问 4 轮）
  ┌──────────────────────────────────┐
  │  📋 计划 → LLM 推理 → 选择工具   │
  │              ↓                   │
  │        执行工具 → 结构化数据      │
  │              ↓                   │
  │        LLM 综合 → 草稿结论        │
  │              ↓                   │
  │        🔍 自检验证 → 修正输出     │
  └──────────────────────────────────┘
       │
       ▼
  SQLite（conversation_id + visitor_id）
```

**Agent 能力：**

- 名称/简称 → 代码解析（个股 / 场内基金）
- 个股：行情、财务、估值分位、行业、北向资金、研报、龙虎榜
- ETF：折溢价、持仓穿透、收益表现
- 投资人评审：巴菲特、格雷厄姆、段永平、彼得林奇、张坤、赵老哥、利弗莫尔、达里奥
- 多轮追问：基于上下文增量回答，不重复整篇报告
- **自检验证**：结论输出前审查数据支撑、内部一致性、评分合理性，修正后再输出

---

## 功能与 API

| 模式 | 接口 | 说明 |
|------|------|------|
| 一次性分析 | `POST /api/analyze` | 单轮完整分析 |
| 多轮（Vue 推荐） | `POST /api/chat/begin` → `POST /api/chat/{id}/run` | 先发问落库，再跑 Agent；侧栏即时显示「生成中…」 |
| 多轮（单请求） | `POST /api/chat/start` | 创建 + 跑 Agent 一步完成（Streamlit 兼容） |
| 追问 | `POST /api/chat/continue` | 传入 `conversation_id` |
| 历史列表 | `GET /api/chat/list` | **仅当前访客**的对话 |
| 加载历史 | `GET /api/chat/{id}` | 含 `status`: `pending` / `ready` |
| 删除 | `DELETE /api/chat/{id}` | |
| 健康检查 | `GET /health` | |

**访客隔离：** 后端通过 `HttpOnly` Cookie `visitor_id` 区分浏览器；列表/读写/删除均带 `visitor_id` 过滤。换浏览器或清 Cookie 后看不到旧对话。

**输入示例：**

- `分析一下贵州茅台`
- `沪深300ETF 值得买吗`
- `600519 北向资金怎么看`（追问）

---

## 本地开发

### 环境要求

- Python 3.10+
- Node.js 18+（Vue 前端）
- **必须配置 LLM API Key**

### 安装

```powershell
git clone https://github.com/lizexi20050819-hue/caitong-agent.git
cd caitong-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

编辑 `.env`（至少一种 LLM）：

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的key
DEEPSEEK_MODEL=deepseek-chat
```

Vue 依赖：

```bash
cd frontend-vue
npm install
```

### 启动

**一键（Windows）：**

```powershell
.\scripts\run_all.ps1
```

**分别启动：**

```powershell
# 终端 1 — 后端
.\scripts\run_backend.ps1

# 终端 2 — Vue
.\scripts\run_frontend_vue.ps1
```

**手动：**

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

```bash
cd frontend-vue && npm run dev
```

| 地址 | 用途 |
|------|------|
| http://localhost:5173 | Vue 前端 |
| http://127.0.0.1:8001/health | 健康检查 |
| http://127.0.0.1:8001/docs | Swagger API 文档 |

Streamlit 旧版：`streamlit run frontend/streamlit_app.py`（通常 http://localhost:8501）

### 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

覆盖 Session、fetcher、LLM 配置、FastAPI 路由（LLM 已 mock）。

---

## 项目结构

```text
backend/app/
  main.py                 # FastAPI 路由、visitor Cookie
  models.py               # Pydantic 模型
  services/
    agent.py              # Agent 主循环、begin/run/start/continue
    session_store.py      # SQLite 持久化、visitor_id 隔离
    tools.py              # 12 个 LangChain 工具
    llm.py                # DeepSeek / OpenAI 配置
    market_data.py        # 行情
    fetchers/             # 财务、估值、行业、资金、研报等

frontend-vue/             # Vue 3 主前端
  src/App.vue             # 多轮对话 UI
  src/components/MarkdownContent.vue
  src/utils/markdown.js   # Markdown 渲染、综合评分置顶
  Dockerfile              # Node 构建 + Nginx
  nginx.conf              # 静态资源 + /api 反代

frontend/
  streamlit_app.py        # Streamlit 旧前端

Dockerfile                # 后端镜像（Python + uvicorn）
docker-compose.yml        # 前后端编排，对外 80 端口
scripts/
  run_all.ps1             # 一键启动后端 + Vue
  run_backend.ps1
  run_frontend_vue.ps1
  run_frontend.ps1        # Streamlit

tests/                    # pytest
data/                     # sessions.db（运行时生成，gitignore）
.github/workflows/deploy.yml
```

---

## Agent 工具列表

| 工具 | 用途 |
|------|------|
| `resolve_stock_code` | 名称/简称 → 代码，区分 stock / fund |
| `get_market_data` | 实时行情、PE、PB |
| `get_financials` | ROE、利润率、负债率、分红 |
| `get_valuation` | PE/PB 5 年历史分位 |
| `get_industry` | 行业分类、景气度 |
| `get_capital_flow` | 北向资金、大宗交易 |
| `get_research` | 券商研报共识 |
| `get_lhb_data` | 龙虎榜 |
| `get_etf_info` | ETF 价、折溢价 |
| `get_etf_holdings` | 持仓穿透 |
| `get_etf_performance` | 收益、波动 |
| `role_play_investor` | 投资人 persona 评审 |

---

## 上线部署（Docker）

两个 Dockerfile 分工：

| 文件 | 构建 |
|------|------|
| 根目录 `Dockerfile` | 后端 `caitong-backend`（pip 清华源，无 apt） |
| `frontend-vue/Dockerfile` | 前端 `caitong-frontend`（npm 构建 + Nginx） |

`docker-compose.yml` 只对外暴露 **80**；Nginx 托管 Vue 并将 `/api`、`/health` 反代到后端内网。

### 首次部署

```bash
git clone https://github.com/lizexi20050819-hue/caitong-agent.git
cd caitong-agent

cp .env.example .env
nano .env          # 填写 DEEPSEEK_API_KEY 等

mkdir -p data
docker compose up -d --build
```

云厂商安全组放行 **TCP 80**，浏览器访问 `http://公网IP`。

### 环境变量

| 变量 | 说明 |
|------|------|
| `LLM_PROVIDER` | `deepseek` 或 `openai` |
| `DEEPSEEK_API_KEY` | 必填其一 |
| `SESSION_DB_PATH` | compose 已映射 `./data/sessions.db` |

**切勿**将 `.env` 提交 Git。

### 代码更新

```bash
# 本机：git push 后，在服务器
cd ~/caitong-agent
git pull
docker compose up -d --build
```

仅改 `.env`：`docker compose restart backend`

### 运维

```bash
docker compose ps
docker compose logs -f backend
curl -s http://127.0.0.1/health
```

对话数据：`./data/sessions.db`（备份 `data/` 目录即可）。

### 自动部署（可选）

推送 `main` 触发 `.github/workflows/deploy.yml`，需在 GitHub Secrets 配置 `SERVER_HOST`、`SERVER_USER`、`SERVER_SSH_KEY`、`DEEPSEEK_API_KEY` 等；服务器需先 `git clone` 到 `/home/<用户>/caitong-agent`。

### HTTPS（建议）

宿主机 Nginx/Caddy 做 443 终止，或 Cloudflare 代理。

### 常见构建问题

| 现象 | 处理 |
|------|------|
| 卡在 `deb.debian.org` / `apt-get` | 使用当前 Dockerfile（无 apt）；`docker compose build --no-cache` |
| 卡在 `resolving provenance` | compose 已设 `provenance: false`；或 `export BUILDX_NO_DEFAULT_ATTESTATIONS=1` |
| `ENV requires at least one argument` | Dockerfile 粘贴损坏，用 `cat > Dockerfile << 'EOF'` 重写 |
| 外网打不开 | 安全组访问来源填 `0.0.0.0/0`，端口 **80**（勿全开 1-65535） |
| 服务器改了文件与 GitHub 不一致 | 以 GitHub 为准：本地改 → push → 服务器 pull |

---

## 会话与隐私

- 对话存入服务器 `data/sessions.db`，重启容器不丢失（volume 挂载）。
- 每个浏览器通过 `visitor_id` Cookie 隔离历史；**不同访客互不可见**。
- 清 Cookie / 换浏览器 = 新访客，无法找回旧列表。
- 无账号登录；公开商用建议后续加正式用户体系。

---

## 与 UZI-Skill 的关系

| | 财通Agent | UZI-Skill |
|--|-----------|-----------|
| 定位 | Web LLM Agent | IDE 技能包 |
| 架构 | Function Calling + 多轮 | 固定 Pipeline |
| 投资人 | 8 位 persona | 51 位 |
| 输出 | 对话 Markdown | HTML 研报 |
| 集成 | — | **未接入** |

仓库可不包含 `skill/`；需对照时自行 clone [UZI-Skill](https://github.com/wbh604/UZI-Skill)。

---

## 已知限制

- SQLite 适合单机；多实例需 Redis 等共享存储
- 主要覆盖 **A 股个股与场内 ETF**
- akshare / 东方财富受网络环境影响
- 长分析可能数分钟，Nginx `proxy_read_timeout` 已设 300s

## 后续方向

- 正式用户登录与跨设备同步
- 异步任务 + 分析进度推送
- 更多投资人 persona
- 自包含 HTML 研报导出

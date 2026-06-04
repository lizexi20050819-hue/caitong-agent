# 财通Agent — A 股 LLM 投研助手

自研的 **LLM Agent** 项目：用户用自然语言提问，Agent 自主编排工具拉取真实数据，并支持多轮追问。

投研维度与数据 fetcher 设计**参考**开源项目 [UZI-Skill](https://github.com/wbh604/UZI-Skill)，但主应用为独立实现的 Web Agent，**运行时不会调用** `skill/` 目录中的代码。

- **后端**：Python + FastAPI + Function Calling（DeepSeek / OpenAI 兼容）
- **工具层**：LangChain `@tool` + 12 个领域工具
- **数据**：akshare、baostock、东方财富（`backend/app/services/fetchers/` 自研）
- **前端**：Vue 多轮对话 UI（保留 Streamlit 旧版）

> 本项目为研究辅助工具，不构成任何投资建议。

## 与 UZI-Skill 的关系

| | 财通Agent（主应用） | UZI-Skill（`skill/UZI-Skill-3.6.0/`） |
|---|---|---|
| 定位 | Web 版 LLM Agent | Cursor / Claude 等 IDE 用的独立技能包 |
| 架构 | Function Calling + 多轮对话 | 固定 Pipeline + Agent role-play |
| 入口 | FastAPI / Streamlit | `python run.py 600519` |
| 投资人评审 | 8 位 persona | 51 位 persona + 7 大流派 |
| 输出 | 对话文本结论 | 自包含 HTML 研报 |
| 运行时集成 | — | **未接入**，无 import / subprocess 调用 |

**借鉴了什么：** 多维度 A 股数据采集思路、fetcher 维度划分、akshare 数据源选型、投资人 persona 评审概念。

**没有集成什么：** UZI 的 22 维 pipeline、51 评委系统、HTML 报告生成、`run.py` 工作流。

仓库中的 `skill/UZI-Skill-3.6.0/` 是 UZI-Skill v3.6.0 的完整参考拷贝，可单独运行对照，与财通Agent 后端互不依赖。

## 架构概览

```text
用户输入（自然语言）
       │
       ▼
  Vue / Streamlit / REST API
       │
       ▼
  Agent 循环（最多 6 轮）
  ┌────────────────────────────┐
  │  LLM 推理 → 选择工具       │
  │       ↓                    │
  │  执行工具 → 返回结构化数据  │
  │       ↓                    │
  │  LLM 综合 → 输出结论       │
  └────────────────────────────┘
       │
       ▼
  多轮对话（SQLite Session 持久化）
```

**Agent 能力：**

- 名称/简称 → 代码解析（5000+ 个股、26000+ 基金）
- 个股分析：行情、财务、估值分位、行业、北向资金、研报、龙虎榜
- ETF 分析：实时行情、折溢价、持仓穿透、收益表现
- 投资人评审：巴菲特、格雷厄姆、段永平、彼得林奇、张坤、赵老哥、利弗莫尔、达里奥
- 多轮追问：如「北向资金呢？」「估值贵不贵？」，基于上下文增量回答

## 功能

| 模式 | 说明 |
|------|------|
| 一次性分析 | `POST /api/analyze`，输入一句话，Agent 自动找代码、调工具、出报告 |
| 多轮对话 | `POST /api/chat/start` + `/api/chat/continue`，支持追问，Agent 记住上下文 |
| 工具链可视化 | 前端展示调用了哪些工具及思考过程 |

**输入示例：**

- `分析一下贵州茅台`
- `沪深300ETF 值得买吗`
- `600519 北向资金怎么看`（追问）

## 环境要求

- Python 3.10+
- 已创建虚拟环境 `.venv`（启动脚本默认使用）
- **必须配置 LLM API Key**（DeepSeek 或 OpenAI），Agent 核心能力依赖大模型

## 安装

**1. 克隆仓库并进入项目目录**

```powershell
git clone https://github.com/lizexi20050819-hue/caitong-agent.git
cd caitong-agent
```

若已下载 ZIP，解压后在该文件夹内打开终端即可，无需 `git clone`。

**2. 创建虚拟环境并安装依赖（Windows PowerShell）**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

**macOS / Linux：**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，至少配置一种 LLM：

```env
# 推荐：DeepSeek
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的 key
DEEPSEEK_MODEL=deepseek-chat

# 或使用 OpenAI 兼容 API
# LLM_PROVIDER=openai
# OPENAI_API_KEY=你的 key
# OPENAI_MODEL=gpt-4o-mini
```

## 测试

不依赖 DeepSeek API Key 与 akshare 网络，可在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

覆盖：Session 存储、fetcher 工具函数、LLM 配置、FastAPI 路由（LLM 调用已 mock）。

## 启动

以下命令均在**项目根目录**（含 `README.md`、`backend/` 的目录）执行。

**方式一：一键启动前后端（Windows）**

```powershell
.\scripts\run_all.ps1
```

**方式二：分别启动（Windows）**

```powershell
# 终端 1 — 后端
.\scripts\run_backend.ps1

# 终端 2 — Vue 前端
.\scripts\run_frontend_vue.ps1
```

**手动启动（项目根目录，已激活 `.venv`）：**

```powershell
# 终端 1 — 后端（PowerShell）
$env:PYTHONPATH = (Get-Location).Path
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

```bash
# 终端 1 — 后端（bash）
export PYTHONPATH="$PWD"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

```bash
# 终端 2 — Vue 前端
cd frontend-vue
npm install
npm run dev
```

访问地址：

- 后端健康检查：http://127.0.0.1:8001/health
- API 文档：http://127.0.0.1:8001/docs
- Vue 前端：http://localhost:5173
- Streamlit 旧版：`streamlit run frontend/streamlit_app.py` 后终端显示的本地地址（通常 http://localhost:8501）

## API 示例

**一次性分析：**

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8001/api/analyze" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"message":"分析一下贵州茅台"}'
```

**开始多轮对话：**

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8001/api/chat/start" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"message":"分析一下贵州茅台"}'
```

**继续追问（使用上一步返回的 conversation_id）：**

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8001/api/chat/continue" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"conversation_id":"abc12345","message":"北向资金呢？"}'
```

## 项目结构

```text
backend/
  app/
    main.py                   # FastAPI 入口，/api/analyze 与 /api/chat/*
    models.py                 # Pydantic 请求/响应模型
    services/
      agent.py                # Agent 主循环（Function Calling + 多轮记忆）
      session_store.py        # SQLite 多轮对话持久化
      tools.py                # 12 个 LangChain 工具 + OpenAI schema
      llm.py                  # LLM 配置加载（DeepSeek / OpenAI）
      market_data.py          # A 股行情（baostock + 东方财富）
      fetchers/               # 财务、估值、行业、资金、研报、龙虎榜等
frontend/
  streamlit_app.py            # Streamlit 多轮对话前端
scripts/
  run_backend.ps1
  run_frontend.ps1
  run_all.ps1
tests/                        # pytest 单元测试与 API 测试
pytest.ini
data/                         # SQLite sessions.db（运行时生成，已 gitignore）
```

**单独运行 UZI-Skill（可选，与主应用无关）：**

本仓库未包含 `skill/` 目录，需自行克隆 [UZI-Skill](https://github.com/wbh604/UZI-Skill)：

```powershell
git clone https://github.com/wbh604/UZI-Skill.git
cd UZI-Skill
pip install -r requirements.txt
python run.py 600519
```

## Agent 工具列表

| 工具 | 用途 |
|------|------|
| `resolve_stock_code` | 名称/简称 → 6 位代码，区分 stock / fund |
| `get_market_data` | 实时行情、PE、PB |
| `get_financials` | ROE、利润率、负债率、分红等 |
| `get_valuation` | PE/PB 5 年历史分位 |
| `get_industry` | 行业分类、景气度、市值排名 |
| `get_capital_flow` | 北向资金、大宗交易、限售解禁 |
| `get_research` | 券商研报共识、盈利预测 |
| `get_lhb_data` | 龙虎榜、机构 vs 游资 |
| `get_etf_info` | ETF 实时价、折溢价、规模 |
| `get_etf_holdings` | ETF 前十大持仓、行业分布 |
| `get_etf_performance` | ETF 近期收益、波动率 |
| `role_play_investor` | 知名投资人 persona 评审 |

## 上线部署（Docker，推荐）

项目已包含 `Dockerfile`、`frontend-vue/Dockerfile`、`docker-compose.yml`。对外只暴露 **80 端口**（Nginx 托管 Vue + 反向代理 `/api` 到后端）。

### 1. 准备一台 Linux 服务器

- 建议：2 核 4G 内存以上（akshare / pandas 较吃资源）
- 系统：Ubuntu 22.04 / Debian 12 等
- 安装 Docker 与 Docker Compose v2

```bash
# Ubuntu 示例
sudo apt update && sudo apt install -y git docker.io docker-compose-v2
sudo usermod -aG docker $USER
# 重新登录后生效
```

### 2. 首次部署（手动）

```bash
git clone https://github.com/lizexi20050819-hue/caitong-agent.git
cd caitong-agent

cp .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY（或 OPENAI_API_KEY）
nano .env

mkdir -p data   # SQLite 会话库持久化目录

docker compose up -d --build
docker compose ps
```

浏览器访问：`http://你的服务器IP`（或绑定域名后访问域名）。

健康检查：`http://你的服务器IP/health` 应返回 `{"status":"ok"}`。

### 3. 环境变量（`.env`）

| 变量 | 说明 |
|------|------|
| `LLM_PROVIDER` | `deepseek` 或 `openai` |
| `DEEPSEEK_API_KEY` | DeepSeek Key（上线必填其一） |
| `OPENAI_API_KEY` | OpenAI 兼容 Key |
| `SESSION_DB_PATH` | compose 已映射到 `/app/data/sessions.db`，一般不用改 |

**切勿**把 `.env` 提交到 Git；Key 只放在服务器本地。

### 4. 自动部署（GitHub Actions）

推送 `main` 分支可触发 `.github/workflows/deploy.yml`（需先在仓库 Settings → Secrets 配置）：

| Secret | 说明 |
|--------|------|
| `SERVER_HOST` | 服务器 IP 或域名 |
| `SERVER_USER` | SSH 用户名 |
| `SERVER_SSH_KEY` | SSH 私钥 |
| `LLM_PROVIDER` | 同 `.env` |
| `DEEPSEEK_API_KEY` | 同 `.env` |
| `DEEPSEEK_MODEL` | 可选 |

服务器上需**先手动** `git clone` 到 `/home/<用户>/caitong-agent`（路径与 workflow 中一致），之后每次 push `main` 会自动 `git pull` + `docker compose up -d --build`。

### 5. HTTPS（可选，建议）

compose 默认 HTTP 80。生产环境建议：

- 用 **Nginx / Caddy** 在宿主机做 443 终止，反代到 `127.0.0.1:80`；或
- 域名接入 **Cloudflare** 开启 HTTPS

### 6. 运维常用命令

```bash
docker compose logs -f backend    # 看后端日志
docker compose logs -f frontend
docker compose restart backend
docker compose down && docker compose up -d --build   # 更新代码后重建
```

`data/sessions.db` 在宿主机 `./data/` 目录，备份该目录即可保留历史对话。

### 7. 上线前检查清单

- [ ] `.env` 中 LLM Key 已配置且有效
- [ ] 服务器能访问外网（DeepSeek API、akshare 数据源）
- [ ] 安全组 / 防火墙放行 80（若用 HTTPS 再放行 443）
- [ ] 本地 `docker compose up -d --build` 能跑通再推到服务器
- [ ] 跑一遍 `pytest` 确保无回归

## 已知限制

- 多轮对话 Session 存于 SQLite（`data/sessions.db`），重启后端不丢失；多进程部署需改 Redis
- 主要覆盖 **A 股个股与场内 ETF**，暂不支持港股/美股完整分析链路
- 部分数据源（akshare / 东方财富）可能受网络环境影响
- 投资人 persona 目前为 8 位（UZI-Skill 参考包中有 51 位，未接入主应用）

## 后续可扩展方向

- Redis 多实例 Session 共享
- 异步任务队列与长分析进度推送
- 扩展更多投资人 persona 与流派评分
- 生成自包含 HTML 研报
- 单元测试与 CI
- 更严格的数据缺口校验与自查 Gate

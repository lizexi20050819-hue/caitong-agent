# 财通Agent — A 股 LLM 投研助手

自研的 **LLM Agent** 项目：用户用自然语言提问，Agent 自主编排工具拉取真实数据，并支持多轮追问。

投研维度与数据 fetcher 设计**参考**开源项目 [UZI-Skill](https://github.com/wbh604/UZI-Skill)，但主应用为独立实现的 Web Agent，**运行时不会调用** `skill/` 目录中的代码。

- **后端**：Python + FastAPI + Function Calling（DeepSeek / OpenAI 兼容）
- **工具层**：LangChain `@tool` + 12 个领域工具
- **数据**：akshare、baostock、东方财富（`backend/app/services/fetchers/` 自研）
- **前端**：Streamlit 多轮对话 UI

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
  Streamlit / REST API
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
  多轮对话（Session 记忆）
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

# 终端 2 — 前端
.\scripts\run_frontend.ps1
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
# 终端 2 — 前端（PowerShell / bash 相同）
streamlit run frontend/streamlit_app.py
```

访问地址：

- 后端健康检查：http://127.0.0.1:8001/health
- API 文档：http://127.0.0.1:8001/docs
- 前端：Streamlit 启动后终端显示的本地地址（通常 http://localhost:8501）

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
skill/
  UZI-Skill-3.6.0/            # UZI-Skill 参考拷贝，运行时未接入主应用
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

## 已知限制

- 对话 Session 存于内存，后端重启后丢失
- 主要覆盖 **A 股个股与场内 ETF**，暂不支持港股/美股完整分析链路
- 部分数据源（akshare / 东方财富）可能受网络环境影响
- 投资人 persona 目前为 8 位（UZI-Skill 参考包中有 51 位，未接入主应用）

## 后续可扩展方向

- Session 持久化（Redis / SQLite）
- 异步任务队列与长分析进度推送
- 扩展更多投资人 persona 与流派评分
- 生成自包含 HTML 研报
- 单元测试与 CI
- 更严格的数据缺口校验与自查 Gate

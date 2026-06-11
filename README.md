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

## 踩坑日志

| 日期 | 模块 | 现象 | 原因 | 处理 |
|------|------|------|------|------|
| 2026-06-10 | 上下文压缩 | 首诊 4 轮工具拉完后，**第一次追问**就触发压缩；追问「ROE / 股息率具体多少」时数字不准或让 Agent 重复调工具 | ① 保留窗口仅 **3 轮**，典型完整首诊正好 **4 轮**，累计 >3 即压；② 摘要仅 **200 字**，输入节选 **400 字符/条**，财务类 tool JSON（近 2000 字）信息损失大；③ 与 System Prompt「追问优先用已有 tool 结果」冲突 | **方案 B**（`agent.py`）：`MAX_TOOL_ROUNDS_KEPT` **3→5**（首诊 4 轮 + 1 次追问内不压）；`SUMMARY_MAX_CHARS` **200→600**；`TOOL_SNIPPET_CHARS` **400→800**；`MAX_TOOL_SNIPPETS` **8→12**。基准见下文「上下文压缩 → 效果」 |

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
- **上下文压缩**：多轮追问时自动将早期工具结果提炼为摘要，控制 token 消耗（详见下文）

---

## 上下文压缩

多轮追问时，历史 `tool` 返回会快速撑大 LLM 上下文。Agent 在每次进入对话循环前自动压缩早期轮次，在保留关键信息的同时降低 token 成本。

### 机制

实现位于 `backend/app/services/agent.py`（`_compact_context` / `_build_compaction_summary`）：

| 规则 | 说明 |
|------|------|
| 触发条件 | 历史工具轮次 **> 5**（一轮 = 一次带 `tool_calls` 的 assistant 消息） |
| 保留策略 | **最近 5 轮** tool 结果完整保留 |
| 压缩方式 | 更早轮次由 LLM 提炼为 **600 字以内**摘要（输入节选 800 字符/条，最多 12 条），写入 `messages` |
| 单条 tool 上限 | 写入上下文时单条结果最高 **2000 字符**（`_execute_tools` 截断） |
| 持久化 | 压缩后的 `messages` 写回 `data/sessions.db` 的 `messages_json` |
| 有损性 | 早期原始 tool JSON 被替换后不可恢复，仅保留摘要中的关键数字 |

压缩后 LLM 仍能「看到」摘要（作为普通 `user` 消息），无需额外工具调用；前端 thinking 会显示 `📦 上下文压缩：…`。

### 效果（基准测试）

运行 `python scripts/benchmark_context_compaction.py` 实测（2026-06-10，内置 token 估算器；与 `tiktoken/cl100k_base` 趋势一致）。模拟真实 tool 体积（单条最高 2000 字符，与 `_execute_tools` 一致），摘要 LLM 调用在基准中用固定 mock 替代。

**触发压缩的场景平均：全量上下文约省 27.0% token（约 1643 tokens/次）；被压缩的历史片段约省 92.2% token。**

| 场景 | 工具轮次 | 压缩前 tokens | 压缩后 tokens | 节省 tokens | 全量节省 | 被压缩片段节省 |
|------|----------|---------------|---------------|-------------|----------|----------------|
| 阈值内（不触发） | 5 | 3,712 | 3,712 | 0 | 0% | — |
| 轻度 | 6 | 4,670 | 4,304 | 366 | 7.8% | 80.4% |
| 中度 | 7 | 5,481 | 4,157 | 1,324 | 24.2% | 93.7% |
| 重度 | 10 | 7,391 | 4,307 | 3,084 | 41.7% | 97.2% |
| 首诊 4 轮 + 追问 1 轮 | 5 | 3,903 | 3,903 | 0 | 0% | — |
| 首诊 4 轮 + 追问 3 轮 | 7 | 5,008 | 3,716 | 1,292 | 25.8% | 93.6% |
| 首诊 4 轮 + 追问 5 轮 | 9 | 5,946 | 3,126 | 2,820 | 47.4% | 96.9% |
| 首诊 4 轮 + 每轮 3 工具 | 6 | 6,338 | 5,366 | 972 | 15.3% | 91.6% |
两个百分比的含义：

- **全量上下文节省**：整份 `messages`（含 system、最近 5 轮、用户消息）送入 LLM 前后的 token 变化。
- **被压缩片段节省**：仅「第 5 轮以前」那段历史 → 替换成摘要后的缩减比例（通常 90%+）。

对话越长、tool 轮次越多，全量节省越明显；最近 5 轮始终不压，保证首诊 4 轮 + 1 次追问内不触发压缩。

### 如何复现测试

```powershell
# 查看完整基准报告（多场景对比表）
python scripts/benchmark_context_compaction.py

# 可选：精确 token 计数（需能 pip install tiktoken）
pip install tiktoken
python scripts/benchmark_context_compaction.py

# 自动化断言（阈值、压缩率下限等，无需网络）
python -m pytest tests/test_compaction_benchmark.py -v
```

相关文件：

| 文件 | 用途 |
|------|------|
| `scripts/benchmark_context_compaction.py` | 基准测试主程序，输出各场景 token/字符节省百分比 |
| `tests/test_compaction_benchmark.py` | pytest：验证触发阈值、压缩率下限 |
| `tests/test_agent.py` | 验证压缩逻辑（摘要写入 messages、保留最近 N 轮） |

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

覆盖 Session、fetcher、LLM 配置、FastAPI 路由、上下文压缩基准（LLM 已 mock）。

上下文压缩专项：

```powershell
python scripts/benchmark_context_compaction.py
python -m pytest tests/test_compaction_benchmark.py -v
```

---

## 项目结构

```text
backend/app/
  main.py                 # FastAPI 路由、visitor Cookie
  models.py               # Pydantic 模型
  services/
    agent.py              # Agent 主循环、上下文压缩、begin/run/start/continue
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
  benchmark_context_compaction.py  # 上下文压缩 token 基准测试

tests/                    # pytest
  test_compaction_benchmark.py   # 压缩率断言
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

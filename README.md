# AI 出题学习助手（LearnWithAI）

输入一个想学的知识点 → AI 联网检索并出题 → 你答题 → AI 判分并生成学习诊断报告。

一套代码两端运行：**微信小程序 + H5**。没有 DeepSeek API Key 也能用 Mock 模式完整演示。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 小程序端 | Taro 4.3.2 + React 18 + TypeScript |
| 后端 | Python 3.9+ / FastAPI + Uvicorn |
| AI | DeepSeek `deepseek-flash`（JSON Output，默认关闭思考） |
| 检索 | DeepSeek Search API（`/v1/tools/search`） |
| 存储 | SQLite（WAL），仓储层隔离，可迁 PostgreSQL |

选型对比与决策过程见 [方案设计文档.md](./方案设计文档.md) 第 3 章。

## 快速开始

### 1. 启动后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # 可留空，默认走 Mock
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- 接口文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/v1/health （返回 `mode: mock | deepseek`）

**接入真实 AI**：在 `backend/.env` 填入

```bash
DEEPSEEK_API_KEY=sk-xxxxxxxx
LLM_PROVIDER=deepseek
```

### 2. 启动小程序端

```bash
cd miniapp
npm install
npm run build:weapp   # 产物 dist/
npm run dev:weapp     # 开发模式（watch）
npm run build:h5      # 产物 dist-h5/
npm run dev:h5        # H5 调试，默认 http://127.0.0.1:10086
```

用微信开发者工具导入 `miniapp/` 目录（`project.config.json` 已指向 `dist/`，AppID 为测试号占位）。本地联调需勾选「不校验合法域名…」。

API 地址在 `miniapp/src/config.ts`，默认 `http://127.0.0.1:8000`；生产构建时注入：

```bash
TARO_APP_API_BASE=https://api.your-domain.com npm run build:weapp
```

## 测试

```bash
# 后端单测 + 接口测试（8 个用例，Mock 模式）
cd backend && .venv/bin/python -m pytest -q

# H5 端到端（需后端 8000 + 静态服务 10087）
cd miniapp && python3 scripts/serve_h5.py dist-h5 10087 &
node scripts/e2e.js
```

## 目录结构

```
backend/
  app/
    main.py          FastAPI 入口、CORS、异常处理
    config.py        环境变量与 Mock/真实模式判定
    schemas.py       Pydantic 契约
    db.py            SQLite 仓储
    llm.py           DeepSeek / Mock 适配（含计费）
    search.py        Search API / Mock
    prompts.py       Prompt 资产
    api/routes.py    REST 路由
    services/        出题、判分、报告
  tests/
miniapp/
  src/pages/         首页 / 答题页 / 报告页
  src/services/      请求封装、轮询、本地缓存
  src/types.ts       与后端契约对齐
  scripts/           E2E 与截图脚本
shots/               H5 截图（验收产物）
```

## 已实现（MVP 核心链路）

- 输入主题、难度、题量、题型
- 检索 → 提纲 → 出题，四题型（单选/多选/判断/简答）
- 异步任务 + 轮询 + 分步进度
- 客观题规则判分、简答题 rubric 判分（失败降级）
- 报告：分数、分题型统计、逐题解析、知识缺口、下一步、建议主题、来源
- 失败重试、未答确认、重复提交拦截、限流
- Mock 模式、token/成本统计

## 尚未实现（见文档 M4/M5）

登录与跨端同步、用户配额、内容审核、支付、多轮追问、错题本、指定信息源。

## 文档

- [需求分析文档.md](./需求分析文档.md)
- [方案设计文档.md](./方案设计文档.md)（技术选型、架构、接口、数据模型、开发流程、合规、成本）

## 注意

- 生产环境必须使用 HTTPS 已备案域名，并在微信公众平台配置 request 合法域名。
- `backend/.env` 含密钥，不要提交到仓库或前端。
- 内容由 AI 生成，上线前需补充 AI 生成标识、内容审核与免责声明。
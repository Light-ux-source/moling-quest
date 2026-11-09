# 15 · 故障排查与 FAQ

| 项 | 内容 |
| --- | --- |
| 版本 | v1.0（对应 v0.2.0） |
| 适用 | 本地开发、联调、部署、测试 |
| 关联 | [07-技术核实](./07-技术核实.md) · [09-API](./09-API接口手册.md) · [13-测试手册](./13-测试手册.md) · [14-运维](./14-部署与运维手册.md) |

---

## 1. 先做三步

```bash
# 1) 后端活着吗？
curl -s http://127.0.0.1:8000/api/v1/health

# 2) 前端服务活着吗？（H5）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:10087/

# 3) 看日志
tail -50 /tmp/lwa-backend.log
```

`/health` 返回 `mode=mock` 说明没读到 Key 或 `LLM_PROVIDER=mock`；`mode=deepseek` 才是真实调用。

---

## 2. 症状速查

| 症状 | 最可能原因 | 处理 |
| --- | --- | --- |
| 小程序请求失败 | 未勾选“不校验合法域名”；后端没起；URL 不是 HTTPS | 开发者工具设置；`curl /health`；真机配 HTTPS 域名 |
| H5 请求 CORS | 后端 `CORS_ORIGINS` 不含 H5 origin | 开发用 `*`；生产配具体域名 |
| 首页一直白屏 | JS 报错/资源 404 | 看控制台；检查 `/assets/**`、转译错误 |
| 生成一直 queued | 后台任务异常/Key/网络 | 看后端日志；失败会写 `error`；用 S07 重试 |
| 一直 Mock | `.env` Key 为空或 `LLM_PROVIDER=mock` | 填 Key；`LLM_PROVIDER=deepseek`；重启 |
| 401 | Key 无效/有空格 | 检查 `.env`；重新申请；重启 |
| 402 | 余额不足 | 充值；换 Key |
| 429 | 限流/模型限速 | 降低频率；调 `RATE_LIMIT_PER_HOUR` |
| 422 | 主题 <2 字/题量越界/progress 越界 | 前端校验；看 `detail` |
| 409 提交答案 | 生成中/已提交 | 轮询到 ready；已完成后不要重复提交 |
| 409 报告 | 批改未完成 | 先轮询到 completed 再取报告 |
| 409 结算 | 未 completed | 同上 |
| 409 章末综合 | 未完成/未满星/已生成 | 看 `detail`；前 5 关均 3 星 |
| 题目少于请求 | 校验丢弃非法题 | 正常“宁缺毋滥”；看日志/加强 Prompt |
| 报告没有个性化 | report LLM 失败，规则回退 | 看日志；可重试/换 Key |
| 简答判分很松/严 | 无 rubric 或 Mock 规则 | 检查题目 rubric；真实模式看 Prompt |
| SQLite `database is locked` | 并发写 | 单 worker；缩短事务；迁 PG |
| 页面横向滚动 | 固定宽/长文本/负边距 | 用 E2E 三档检查；`overflow-x:hidden` 只兜底 |
| 字体不像原型 | Google Fonts 不可达 | 系统回退；或托管子集字体 |
| 图标/墨团 404 | `copy` 路径错误/资源未生成 | `python3 scripts/gen_assets.py`；确认 `dist/assets` |
| 微信里 SVG 不显示 | SVG 用了 `<style>`/百分比 | 用生成脚本；不要手写 |
| 返回键失效 | H5 直接打开无历史 | `onBack` 兜底 `reLaunch` 首页 |
| 截图超时 | 无限动画/字体等待 | `animations:'disabled'`；拦截 Google Fonts |
| E2E 横向溢出 | Taro 页面切换中旧页仍在 DOM | 等 800ms 再测量；用 `:visible` |
| E2E 404 | 缺图标/资源 | 看 `badResponses`；补资源/改图标名 |
| 测试 DB 串数据 | `get_settings` 缓存/测试库复用 | `cache_clear()`、独立 `SQLITE_PATH`、`db._initialized=False` |
| `langchain` 安装冲突 | Python 3.9 + LangChain 1.x | 锁 0.3.x；见 §4 |

---

## 3. 前端问题

### 3.1 H5 直接打开页面变成首页

**现象**：访问 `http://127.0.0.1:10087/pages/map/index?...` 显示首页。  
**原因**：Taro H5 默认 hash 路由；路径被当作静态文件 → `index.html` → 默认 `#/pages/index/index`。  
**处理**：用 `http://127.0.0.1:10087/#/pages/map/index?...`；或在 `config` 切 browser 路由并配 SPA fallback（不推荐，需服务器配合）。

### 3.2 页面切换瞬间出现横向滚动

Taro 会保留旧页面并做转场；转场期间 `scrollWidth` 可能是 2 倍。E2E 等 800ms 再测；不要在动画中间判定。

### 3.3 图标/墨团 404

```bash
cd miniapp
python3 scripts/gen_assets.py
HOME=$PWD/.home npm run build:weapp
HOME=$PWD/.home npm run build:h5
ls dist/assets/icons | head
```

- `copy.to` 必须是 `${outputRoot}/assets`（Taro 的 `to` 相对项目根解析）。
- 动态图标名（如 `arrow-right-ink3`）必须真实存在；用脚本扫描 `name='...'` 与 `src/assets/icons` 对齐。

### 3.4 字体/换行与原型不一致

- 原型使用 Google Fonts（Ma Shan Zheng / Noto Serif SC）；受限网络会回退系统宋体/楷体，字宽不同导致换行。
- 生产可托管字体子集，或用 `wx.loadFontFace`（需 HTTPS+CORS）。
- 当前布局已按回退字体调过（标题单行、摘要长度），但仍可能有几像素差异。

### 3.5 微信端注意

- `navigationStyle: custom` 时用 `statusBarHeight + getMenuButtonBoundingClientRect()`；header 右侧留 200rpx 给胶囊。
- `<image>` 支持 SVG，但不支持 `<style>`/百分比单位；用 `gen_assets.py`。
- `:active` 在部分基础库不生效；需要按下反馈时加 `hover-class`。
- `gap` 在旧基础库可能不生效；目标基础库 2.x+。
- `env(safe-area-inset-bottom)` 用于底部 fixed 元素。

### 3.6 答题页简答输入

Taro H5 渲染为 `<taro-textarea-core>`，Playwright 填值要用 `.answer-input textarea`（内部原生 textarea），不是 `.answer-input` 本身。

### 3.7 草稿/最近学习

- `ml_client_id`：Taro H5 底层 localStorage 存 `{"data": "..."}`；E2E 预置要写 JSON。
- 草稿 key `ml_quiz_drafts`；提交成功后清。
- 最近学习 key `ml_recent_sessions`；只存摘要。

---

## 4. LangChain / DeepSeek

### 4.1 `pip install langchain` 版本冲突

**现象**：`ResolutionImpossible`，`langchain 1.x` 与 `langchain-deepseek 0.1.4` 冲突。  
**原因**：LangChain 1.x 要求 Python ≥3.10；`langchain-deepseek 0.1.4` 只兼容 `langchain-core 0.3.x`。  
**处理**：按 `requirements.txt` 锁 0.3.x（本项目 Python 3.9）。升级 Python 3.12 后若要 1.x，改用 `ChatOpenAI(base_url="https://api.deepseek.com")`，并重跑请求形状测试。

### 4.2 `ChatDeepSeek` 参数不生效

- JSON mode：`model_kwargs={"response_format":{"type":"json_object"}}`；Prompt 必须含 `JSON`。
- 思考开关：`extra_body={"thinking":{"type":"disabled"}}`；开启时加 `reasoning_effort="high"`。
- 采样参数：用 `model.bind(temperature=..., max_tokens=...)` 按任务覆盖。
- token：`AIMessage.usage_metadata`；若为空，回退 `response_metadata.token_usage`。

### 4.3 空 content / JSON 解析失败

- 官方说明 JSON mode 可能返回空 content；`pipeline.run_chain` 重试一次。
- 仍失败：`LLMError("模型返回空内容")` / “无法解析…”。
- 排查：看 Prompt 是否含 JSON 示例、`max_tokens` 是否太小、模型是否返回 markdown。

### 4.4 检索结果质量差

- 阈值已改为官方推荐的 `rerank_score >= 1.5`；旧 0.6 会收低质来源。
- 检查 `need_content=false`（只用 summary）、`count`、query 构造。
- 真实模式失败会降级模型知识；报告仍可用。

### 4.5 真实 Key 联调

```bash
# backend/.env
DEEPSEEK_API_KEY=...
LLM_PROVIDER=deepseek
```

重启后端 → `/health` 应为 `mode=deepseek` → 跑一组：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"topic":"HTTP 缓存机制","level":"basic","question_count":5}'
```

记录耗时、`report.usage.tokens_in/out/cost_cny`；与估算 0.03–0.06 元/组对比。

---

## 5. 后端/数据库

### 5.1 旧库启动报 `no such column`

- `SCHEMA` 里不要在新列上加 `CREATE INDEX`（旧表还没列）；索引放 `_migrate()`，先 `_ensure_column` 再建索引。
- 当前已把 `idx_sessions_client` 放 `_migrate`。
- 测试库用独立 `SQLITE_PATH`，`get_settings.cache_clear()` + `db._initialized=False`。

### 5.2 测试互相污染

- `tests/conftest.py` 每个测试独立临时库；
- 若自己写脚本，注意 `get_settings` 是 `lru_cache`；改 env 后清缓存。
- `llm._llm`/`search._search`/`routes._rate` 也要清。

### 5.3 SQLite 锁

- 用 WAL（`PRAGMA journal_mode=WAL`）；
- 单 worker；短事务；`busy_timeout=15000`；
- 频繁锁 → 切 PostgreSQL（仓储层已隔离）。

### 5.4 限流误伤

`_rate` 是进程内按 IP 的 deque；重启清零。测试设 `RATE_LIMIT_PER_HOUR=500`；生产多实例需 Redis。

### 5.5 章节/统计看不到

- 请求必须带同一个 `X-Client-Id`；H5 换浏览器/清 localStorage 会换 client。
- `GET /chapters` 按 client 过滤；`GET /chapters/{id}` 不按 client（ID 即凭证）。
- 旧库迁移后旧 session 的 `client_id=anonymous`，新 client 看不到。

---

## 6. 部署

| 问题 | 处理 |
| --- | --- |
| 微信合法域名失败 | 必须 HTTPS、已备案、无端口；不能是 IP |
| 证书续期 | certbot timer；`nginx -t && systemctl reload nginx` |
| CORS 生产失败 | `CORS_ORIGINS=https://h5.example.com`，不要 `*` + credentials |
| 反向代理超时 | `proxy_read_timeout 180s` |
| SQLite 多 worker 锁 | `--workers 1`；或 PG |
| 数据丢失 | 每日 `.backup`；恢复演练 |
| Key 泄露 | 吊销→换 Key→查账单→记录事故 |

---

## 7. 排障命令速查

```bash
# 端口占用（macOS）
lsof -nP -iTCP:8000 -sTCP:LISTEN

# 健康 / 模式
curl -s http://127.0.0.1:8000/api/v1/health

# 最近日志
tail -100 /tmp/lwa-backend.log

# SQLite 表结构
sqlite3 backend/data/app.db '.schema sessions'
sqlite3 backend/data/app.db 'select status,count(*) from sessions group by status;'

# 构建产物资源
find miniapp/dist/assets -type f | wc -l
find miniapp/dist-h5/assets -type f | wc -l

# 测试
cd backend && .venv/bin/python -m pytest -q
cd miniapp && npx tsc --noEmit
```

---

## 8. FAQ

**Q：没有 Key 能演示吗？**  
A：可以。`LLM_PROVIDER=auto` 且 Key 为空 → Mock；全流程可用，题目带“模拟”。

**Q：为什么答题接口看不到答案？**  
A：安全边界。`QuestionPublic` 不含 `correct_answer/explanation`；报告/结算才返回。

**Q：为什么报告分数和星级不是一回事？**  
A：`score` 是 0–100 正确率；星级按 60/80/100 阈值；多选/简答部分分会计入 `score` 但不一定 `is_correct`。

**Q：为什么“错题”入口是灰的？**  
A：S09 不在本次 S01–S08 范围；tab 置灰并提示下一版开放，不伪造页面。

**Q：为什么章节地图没有进度卡？**  
A：按原型 S02 只有地图 + 底部抽屉；进度用节点三态表达。

**Q：为什么 H5 分享是复制链接？**  
A：S12 分享卡片未实现；当前 weapp 用原生分享，H5 复制链接。

**Q：真实模型什么时候联调？**  
A：填 `backend/.env` 的 Key 后重启；`/health` 变 `deepseek` 即可。请求形状已用 MockTransport 测过。

**Q：如何加一个新题型？**  
A：`schemas.QuestionType` → `TYPE_LABELS` → Prompt `TYPE_RULES` → `normalize_question` → `grading` → 前端 `TYPE_META`/选项渲染 → 测试。链路较长，先写 ADR。
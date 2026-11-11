# 09 · API 接口手册

| 项 | 内容 |
| --- | --- |
| 版本 | v1.1（对应后端 v0.3.0） |
| Base URL | `http://127.0.0.1:8000`（本地）；生产为 HTTPS 域名 |
| 前缀 | `/api/v1` |
| 格式 | `application/json`；UTF-8；时间为 ISO 8601 UTC |
| 认证 | 可选 `Authorization: Bearer <token>`；游客用 `X-Client-Id`；登录后资源按 `user_id` 隔离 |
| 存储 | MySQL 8+/9（PyMySQL）；开发实例 3307，生产由 `MYSQL_*` 配置 |
| OpenAPI | 启动后访问 `/docs` 或 `/openapi.json` |

> 字段定义以 `backend/app/schemas.py` 为准；数据表见 [10-数据模型与迁移](./10-数据模型与迁移.md)；时序见 [08-系统架构与代码地图](./08-系统架构与代码地图.md)。

---

## 1. 通用约定

### 1.1 请求头

| 头 | 必填 | 说明 |
| --- | --- | --- |
| `Content-Type` | POST/PATCH 必填 | `application/json` |
| `X-Client-Id` | 推荐 | 匿名设备 ID（`[A-Za-z0-9_-]`，≤64）。缺省为 `anonymous`；用于游客隔离与登录时数据迁移 |
| `Authorization` | 登录后必填 | `Bearer <token>`；由 `/auth/wechat` 或 `/auth/dev` 返回 |
| `X-Forwarded-For` | 反向代理时 | 取首个 IP 做限流 |

> `X-Client-Id` 不是安全凭证。登录用户的会话/报告/章节按 `user_id` 校验，跨用户访问返回 404；游客只能访问本设备且尚未归属账号的数据。

### 1.2 错误体

```json
{ "detail": "中文可读原因" }
```

| HTTP | 场景 | 客户端处理 |
| ---: | --- | --- |
| 400 | 答案里出现无效 `question_id` | 提示并允许重新提交 |
| 401 | 令牌缺失/过期/已撤销，或需要登录的操作 | 清理本地登录态并重新登录 |
| 402 | DeepSeek 上游余额/Key 错误会写入 `session.error`，报告/结算返回 409 | 检查后端 `.env`/余额；换 Key 后重试 |
| 404 | 会话/章节不存在 | 回首页重新开始 |
| 409 | 生成中提交、重复提交、报告未完成、结算未完成、章末未解锁 | 继续轮询或提示已提交 |
| 422 | 参数校验失败（主题过短、题量越界、progress 越界） | 定位到输入框 |
| 429 | IP 限流、登录尝试过多、游客试用/每日额度用尽 | 提示恢复时间；游客引导登录 |
| 500 | 未处理异常 | 通用错误 + 重试 |
| 503/超时 | 生成阶段失败会落为 `session.status=failed`；API 本身不返回 503 | S07 重试/换主题 |

### 1.3 限流与幂等

- 创建会话按 IP **30 次/小时**（`RATE_LIMIT_PER_HOUR`，进程内内存）；登录按 IP **20 次/小时**（`LOGIN_RATE_LIMIT_PER_HOUR`）。多实例部署会失效，后续迁 Redis。
- 创建会话**不幂等**：每次调用创建新 session/chapter；前端按钮需防连点。
- 提交答案：同一 session 重复提交返回 **409**；不会覆盖已完成报告。
- 章末综合：同一章节只生成一次，重复返回 409。

### 1.4 轮询建议

| 场景 | 建议 |
| --- | --- |
| 生成中 | 1.2s 一次；失败指数退避（1.2s → 5s）；总超时 120s |
| 批改中 | 同样轮询 `GET /sessions/{id}`，直到 `completed` 再取报告 |
| 不要 | 用 40s 单请求等生成（`wx.request` 默认 60s 上限，弱网易断） |

---

## 2. 端点总览

| # | 方法 | 路径 | 用途 | 成功码 |
| ---: | --- | --- | --- | ---: |
| 1 | GET | `/health` | 健康检查 + 模式 | 200 |
| 2 | POST | `/sessions` | 创建学习会话并异步出题 | 202 |
| 3 | GET | `/sessions/{id}` | 轮询状态/题目 | 200 |
| 4 | PATCH | `/sessions/{id}/progress` | 记录当前关 | 200 |
| 5 | POST | `/sessions/{id}/answers` | 提交答案并异步判分 | 202 |
| 6 | GET | `/sessions/{id}/report` | 获取报告快照 | 200 |
| 7 | GET | `/sessions/{id}/settlement` | 获取星级/经验/段位 | 200 |
| 8 | POST | `/sessions/{id}/retry` | 失败原位重试 | 202 |
| 8.1 | POST | `/sessions/{id}/regenerate` | 预览页重新生成（复用会话，不扣额度） | 202 |
| 9 | GET | `/chapters` | 当前 client 的章节列表 | 200 |
| 10 | GET | `/chapters/{id}` | 章节详情 + 节点 | 200 |
| 11 | POST | `/chapters/{id}/comprehensive` | 生成章末综合 | 202 |
| 12 | GET | `/profile` | 个人统计/段位/额度 | 200 |
| 13 | GET | `/sessions` | 最近会话（按登录用户/游客） | 200 |
| 14 | POST | `/auth/wechat` | 微信 code 登录/自动注册 | 200 |
| 15 | POST | `/auth/dev` | 开发体验登录（生产禁用） | 200 |
| 16 | GET | `/auth/me` | 当前登录态 | 200/401 |
| 17 | POST | `/auth/logout` | 撤销当前 token | 200 |
| 18 | PATCH | `/profile` | 修改昵称/头像 | 200 |
| 19 | POST | `/profile/avatar` | 上传头像 | 200 |
| 20 | GET | `/profile/settings` | 读取提醒偏好 | 200 |
| 21 | PATCH | `/profile/settings` | 更新提醒偏好 | 200 |
| 22 | DELETE | `/profile` | 注销账号 | 204 |
| 23 | GET | `/records` | 学习记录列表（仅列表） | 200 |

---

## 3. 端点详情

### 3.1 `GET /api/v1/health`

**响应 200**

```json
{
  "status": "ok",
  "version": "0.3.0",
  "mode": "mock",
  "model": "mock-deepseek-flash",
  "web_search": false,
  "database": "mysql",
  "auth": "wechat",
  "wechat_login": false,
  "dev_login": true
}
```

| 字段 | 说明 |
| --- | --- |
| `mode` | `mock` / `deepseek` |
| `model` | Mock 为 `mock-deepseek-flash`；真实为配置的模型 ID（当前网关注入 `deepseek-v4.1-flash-1017`） |
| `web_search` | 真实模式且开启检索时为 `true` |
| `database` | 固定 `mysql` |
| `auth` | 固定 `wechat`；`wechat_login` 表示 AppID+Secret 是否齐全（当前本地已填写并加载，返回 `true`） |
| `dev_login` | 非生产且 `DEV_LOGIN_ENABLED=true` 时为 `true` |

---

### 3.2 `POST /api/v1/sessions`

创建会话 + 章节，202 立即返回，后台执行检索/出题。

**请求**

```json
{
  "topic": "HTTP 缓存机制：强缓存与协商缓存",
  "level": "advanced",
  "question_count": 5,
  "types": ["single_choice", "multiple_choice", "true_false", "short_answer"],
  "kind": "standard"
}
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `topic` | string | 是 | 2–200 字；空白会被折叠 |
| `level` | enum | 否 | `basic` / `advanced` / `challenge`，默认 `basic` |
| `question_count` | int | 否 | 3–10，默认 5 |
| `types` | string[] | 否 | 四种题型；至少一种；缺省全部 |
| `kind` | enum | 否 | `standard` / `daily`；`daily` 强制 3 题、全题型 |

**响应 202（SessionDetail）**

```json
{
  "id": "s_c60b59ee1e0e",
  "chapter_id": "c_9a7f3c21b004",
  "parent_chapter_id": null,
  "topic": "HTTP 缓存机制：强缓存与协商缓存",
  "level": "advanced",
  "question_count": 5,
  "types": ["single_choice", "multiple_choice", "true_false", "short_answer"],
  "kind": "standard",
  "status": "queued",
  "stage": "queued",
  "progress": 2,
  "current_seq": 1,
  "error": null,
  "questions": [],
  "sources": [],
  "answered_count": 0,
  "model": "mock-deepseek-flash",
  "created_at": "2026-11-09T11:30:00+00:00",
  "updated_at": "2026-11-09T11:30:00+00:00"
}
```

**错误**：422（主题/题量非法）、429（限流）。

---

### 3.3 `GET /api/v1/sessions/{id}`

**响应 200（SessionDetail）**：字段同上；`ready` 之后 `questions` 有值。

```json
{
  "id": "s_c60b59ee1e0e",
  "chapter_id": "c_9a7f3c21b004",
  "topic": "HTTP 缓存机制：强缓存与协商缓存",
  "level": "advanced",
  "question_count": 5,
  "types": ["single_choice", "multiple_choice", "true_false", "short_answer"],
  "kind": "standard",
  "status": "ready",
  "stage": "ready",
  "progress": 100,
  "current_seq": 3,
  "error": null,
  "questions": [
    {
      "id": "q_ee1e0e_1_6c0b",
      "seq": 1,
      "type": "single_choice",
      "title": "强缓存与协商缓存",
      "stem": "关于 HTTP 强缓存与协商缓存，下列说法正确的是？",
      "options": [
        { "key": "A", "text": "Cache-Control: max-age 命中时不会发起网络请求" },
        { "key": "B", "text": "ETag 属于强缓存" }
      ],
      "difficulty": "easy"
    }
  ],
  "sources": [
    { "title": "HTTP caching - MDN", "url": "https://...", "site_name": "MDN", "summary": "..." }
  ],
  "answered_count": 0,
  "model": "deepseek-flash"
}
```

> **安全边界**：`questions` 不包含 `correct_answer` / `explanation`。这是设计，不是遗漏。

**错误**：404。

---

### 3.4 `PATCH /api/v1/sessions/{id}/progress`

记录“退出重进定位到当前关”。只允许 `ready` 状态。

**请求**

```json
{ "current_seq": 3 }
```

**响应 200**

```json
{ "session_id": "s_c60b59ee1e0e", "current_seq": 3 }
```

**错误**：404；409（非 ready）；422（`current_seq > question_count`）。

> 该接口只记录位置，不保存答案草稿；草稿在客户端本地（`ml_quiz_drafts`）。

---

### 3.5 `POST /api/v1/sessions/{id}/answers`

提交整组答案（未答题也要传空值或省略；服务端按空答 0 分）。

**请求**

```json
{
  "answers": [
    { "question_id": "q_ee1e0e_1_6c0b", "answer": "A" },
    { "question_id": "q_ee1e0e_2_9f2a", "answer": ["A", "C"] },
    { "question_id": "q_ee1e0e_3_71bd", "answer": "B" },
    { "question_id": "q_ee1e0e_4_88cd", "answer": "先定义……再说明机制……最后举例……" }
  ]
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `answers[].question_id` | string | 必须是该 session 的题目 |
| `answers[].answer` | string \| string[] | 客观题为字母；多选为数组；简答为文本 |

**响应 202**

```json
{ "session_id": "s_c60b59ee1e0e", "status": "grading", "progress": 30 }
```

**错误**：
- 400：未知 `question_id`
- 404：会话不存在
- 409：生成中 / 已提交（grading/reporting/completed）

> 提交后后台执行判分、报告、结算；客户端轮询 `GET /sessions/{id}` 至 `completed`。

---

### 3.6 `GET /api/v1/sessions/{id}/report`

**响应 200（ReportPayload）**

```json
{
  "session_id": "s_c60b59ee1e0e",
  "topic": "HTTP 缓存机制：强缓存与协商缓存",
  "level": "advanced",
  "level_label": "进阶",
  "score": 80,
  "total": 5,
  "correct": 4,
  "accuracy": 0.8,
  "summary": "本次练习正确率 80%，主干概念已建立，但边界条件仍需巩固。",
  "level_tag": "基础达标",
  "by_type": {
    "单选题": { "total": 2, "correct": 2 },
    "多选题": { "total": 1, "correct": 0 },
    "判断题": { "total": 1, "correct": 1 },
    "简答题": { "total": 1, "correct": 1 }
  },
  "items": [
    {
      "question_id": "q_ee1e0e_1_6c0b",
      "seq": 1,
      "type": "single_choice",
      "type_label": "单选题",
      "stem": "关于 HTTP 强缓存与协商缓存，下列说法正确的是？",
      "options": [{ "key": "A", "text": "..." }],
      "user_answer": "A",
      "correct_answer": "A",
      "is_correct": true,
      "score": 1.0,
      "feedback": "回答正确。",
      "explanation": "max-age 命中时浏览器直接使用本地副本……",
      "rubric": [],
      "source_refs": ["https://..."]
    }
  ],
  "knowledge_gaps": ["第 2 题（多选题）涉及的知识点仍需巩固"],
  "next_steps": ["回看错题的解析，用自己的话复述一遍关键概念"],
  "suggested_topics": ["HTTP 缓存进阶", "HTTP 缓存实战案例"],
  "sources": [{ "title": "HTTP caching - MDN", "url": "https://...", "site_name": "MDN", "summary": "..." }],
  "duration_sec": 63,
  "generated_at": "2026-11-09T11:32:10+00:00",
  "model": "deepseek-flash",
  "usage": {
    "tokens_in": 9321,
    "tokens_out": 2874,
    "cost_cny": 0.0416,
    "currency": "CNY",
    "note": "按高峰价保守估算，实际以账单为准"
  },
  "settlement": {
    "session_id": "s_c60b59ee1e0e",
    "chapter_id": "c_9a7f3c21b004",
    "stars": 2,
    "accuracy": 0.8,
    "correct": 4,
    "total": 5,
    "exp": 120,
    "combo": 3,
    "wrong_count": 1,
    "duration_sec": 63,
    "rank_before": { "key": "S2", "label": "苔径旅人", "exp": 160, "next_key": "S3", "next_label": "青苔行者", "exp_to_next": 140, "progress_pct": 30 },
    "rank_after": { "key": "S2", "label": "苔径旅人", "exp": 280, "next_key": "S3", "next_label": "青苔行者", "exp_to_next": 20, "progress_pct": 90 },
    "level_up": false,
    "exp_to_next": 20
  }
}
```

**错误**：404；409（failed / 报告未生成）。

> 报告是**快照**：生成后固定，不随题目后续修改而变化。`settlement` 也在快照里。

---

### 3.7 `GET /api/v1/sessions/{id}/settlement`

**响应 200（SettlementPayload）**

```json
{
  "session_id": "s_c60b59ee1e0e",
  "chapter_id": "c_9a7f3c21b004",
  "stars": 3,
  "accuracy": 1.0,
  "correct": 5,
  "total": 5,
  "exp": 160,
  "combo": 5,
  "wrong_count": 0,
  "duration_sec": 120,
  "rank_before": { "key": "S1", "label": "初入雾林", "exp": 0, "next_key": "S2", "next_label": "苔径旅人", "exp_to_next": 100, "progress_pct": 0 },
  "rank_after": { "key": "S2", "label": "苔径旅人", "exp": 160, "next_key": "S3", "next_label": "青苔行者", "exp_to_next": 140, "progress_pct": 30 },
  "level_up": true,
  "exp_to_next": 140
}
```

**规则**：
- 星级：`accuracy >= 1.0` 3 星；`>=0.8` 2 星；`>=0.6` 1 星；否则 0。
- 经验：`correct*20 + stars*20`；`kind=daily` 且全对再 +30。
- 连击：最长连续答对。
- 段位阈值：S1 0 / S2 100 / S3 300 / S4 500 / S5 800 / S6 1200。

**错误**：404；409（未 completed / 报告未生成）。

---

### 3.8 `POST /api/v1/sessions/{id}/retry`

只允许 `failed` 会话；清空半成品题目/答案/报告，重置状态并重新生成。

**响应 202（SessionDetail，status=queued）**

**错误**：404；409（非 failed）。

---

### 3.8.1 `POST /api/v1/sessions/{id}/regenerate`

预览页“重新生成”专用：只允许 `ready`（已生成、未提交）会话；复用原 `session_id` / `chapter_id`，清空题目、答案、报告和来源后原位重新生成。

- **不创建新会话/章节，不消耗游客试用或每日额度**；失败仍按“整组失败返还”处理。
- 重复点击/并发调用时，第一次会立刻把状态改为 `queued`，后续请求返回 409。
- `failed` 会话请走 `/retry`，已完成/批改中的会话不可重新生成。

**响应 202（SessionDetail，status=queued，id/chapter_id 不变）**

**错误**：404（不存在/越权）；409（非 ready）。

---

### 3.9 `GET /api/v1/chapters?limit=10`

按 `X-Client-Id` 返回章节列表，按创建时间倒序。

**响应 200**

```json
{
  "items": [
    {
      "id": "c_9a7f3c21b004",
      "session_id": "s_c60b59ee1e0e",
      "title": "HTTP 缓存机制：强缓存与协商缓存",
      "topic": "HTTP 缓存机制：强缓存与协商缓存",
      "level": "advanced",
      "question_count": 5,
      "kind": "standard",
      "status": "ready",
      "stars": 0,
      "accuracy": 0.0,
      "exp": 0,
      "progress": { "done": 2, "total": 6 },
      "next_title": "适用条件",
      "created_at": "2026-11-09T11:30:00+00:00",
      "completed_at": null
    }
  ]
}
```

> `progress.total`：standard = 题数 + 1（章末综合）；daily/comprehensive = 题数。

---

### 3.10 `GET /api/v1/chapters/{id}`

**响应 200（ChapterDetail）**

```json
{
  "id": "c_9a7f3c21b004",
  "session_id": "s_c60b59ee1e0e",
  "parent_chapter_id": null,
  "title": "HTTP 缓存机制：强缓存与协商缓存",
  "topic": "HTTP 缓存机制：强缓存与协商缓存",
  "level": "advanced",
  "question_count": 5,
  "kind": "standard",
  "status": "completed",
  "error": null,
  "stars": 3,
  "accuracy": 1.0,
  "exp": 160,
  "progress": { "done": 5, "total": 6 },
  "current_node": 6,
  "nodes": [
    {
      "seq": 1,
      "title": "强缓存与协商缓存",
      "kind": "question",
      "status": "done",
      "stars": 3,
      "score": 1.0,
      "is_correct": true,
      "question_id": "q_ee1e0e_1_6c0b"
    },
    {
      "seq": 6,
      "title": "章末 · 综合",
      "kind": "comprehensive",
      "status": "unlocked",
      "stars": 0,
      "score": 0.0,
      "is_correct": false,
      "question_id": null
    }
  ],
  "comprehensive": { "seq": 6, "title": "章末 · 综合", "kind": "comprehensive", "status": "unlocked", "stars": 0, "score": 0.0, "is_correct": false, "question_id": null },
  "sources": [],
  "created_at": "2026-11-09T11:30:00+00:00",
  "completed_at": "2026-11-09T11:32:10+00:00"
}
```

**节点状态**：`done` / `current` / `locked` / `unlocked`；章末综合需前 5 关均 3 星。

**错误**：404。注意：该接口**不按 client 过滤**，`chapter_id` 即凭证。

---

### 3.11 `POST /api/v1/chapters/{id}/comprehensive`

生成章末综合（3 题，kind=comprehensive）。

**前置**：章节 kind=standard；原 session completed；前 5 关均 3 星；未生成过综合。

**响应 202（SessionDetail，kind=comprehensive，parent_chapter_id=原章节）**

**错误**：404；409（非标准/未完成/未满星/已生成）。

---

### 3.12 `GET /api/v1/profile`

按登录用户（Bearer）或游客设备（`X-Client-Id`）返回个人统计。**v0.3.0 起新增 `user_id/avatar_url/is_guest/is_logged_in/wechat_bound/points/settings/quota`**，完整字段与游客/登录口径见第 7.5 节。

**口径**：
- `chapters_completed`：该账号/设备已完成的 session 数（含 daily/comprehensive）。
- `total_stars` / `total_exp`：已完成 session 的汇总；`points` 等于 `total_exp`。
- `streak_days`：按 Asia/Shanghai 日期连续完成天数；今天没有则从昨天起算。
- `quota`：登录用户 `period=day`、`limit=3`；游客 `period=trial`、`limit=1`；`quota_enforced` 控制是否拦截。
- 游客/登录双态：`is_guest`、`is_logged_in`、`nickname`、`avatar_url`。

---

### 3.13 `GET /api/v1/sessions?limit=10`

最近会话：登录用户按 `user_id`，游客按 `X-Client-Id` 且未归属账号。

```json
{
  "items": [
    { "id": "s_c60b59ee1e0e", "chapter_id": "c_9a7f3c21b004", "topic": "HTTP 缓存", "level": "advanced", "kind": "standard", "status": "completed", "progress": 100, "current_seq": 5, "question_count": 5, "stars": 3, "exp": 160, "accuracy": 1.0, "completed_at": "...", "created_at": "..." }
  ]
}
```

---

## 4. 对象字段速查

### 4.1 SessionDetail

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | `s_` + 12 hex |
| `chapter_id` | string? | `c_` + 12 hex |
| `parent_chapter_id` | string? | 章末综合指向原章节 |
| `topic` | string | 学习主题 |
| `level` | enum | basic/advanced/challenge |
| `question_count` | int | 实际题数 |
| `types` | string[] | 请求题型 |
| `kind` | string | standard/daily/comprehensive |
| `status` | enum | 见状态机 |
| `stage` | string? | 与 status 同步的展示阶段 |
| `progress` | int | 0–100 |
| `current_seq` | int | 1-based 当前关 |
| `error` | string? | failed 原因 |
| `questions` | QuestionPublic[] | 答题阶段无答案 |
| `sources` | SourceItem[] | 检索来源 |
| `answered_count` | int | ready 时为 0，之后为答案数 |
| `model` | string? | 模型名 |
| `created_at/updated_at` | string | UTC |

### 4.2 ReportPayload

| 字段 | 说明 |
| --- | --- |
| `score` | 0–100（正确率 ×100 四舍五入） |
| `total/correct/accuracy` | 统计 |
| `summary` | 100–150 字诊断（LLM 或规则回退） |
| `level_tag` | 4–8 字标签 |
| `by_type` | `{题型: {total, correct}}` |
| `items` | 逐题：用户答案/正确答案/反馈/解析/rubric/来源 |
| `knowledge_gaps` | 2–4 条，来自错题 |
| `next_steps` | 2–4 条 |
| `suggested_topics` | 2–3 个 |
| `sources` | 检索来源 |
| `duration_sec` | 从 submitted_at/created_at 起算 |
| `usage` | tokens_in/out/cost_cny/currency/note |
| `settlement` | 结算快照 |

### 4.3 枚举

| 枚举 | 值 |
| --- | --- |
| `level` | basic / advanced / challenge |
| `types` | single_choice / multiple_choice / true_false / short_answer |
| `status` | queued / searching / digesting / generating / ready / grading / reporting / completed / failed |
| `kind` | standard / daily / comprehensive |
| `difficulty` | easy / medium / hard |
| node status | done / current / locked / unlocked |

---

## 5. cURL 快跑

```bash
BASE=http://127.0.0.1:8000/api/v1
CID=ml_demo_001

# 健康
curl -s $BASE/health

# 创建
curl -s -X POST $BASE/sessions \
  -H 'Content-Type: application/json' -H "X-Client-Id: $CID" \
  -d '{"topic":"HTTP 缓存机制","level":"basic","question_count":5}'

# 轮询（把 SID 换成上一步 id）
curl -s $BASE/sessions/$SID -H "X-Client-Id: $CID"

# 提交（把 QID/答案换成实际值）
curl -s -X POST $BASE/sessions/$SID/answers \
  -H 'Content-Type: application/json' -H "X-Client-Id: $CID" \
  -d '{"answers":[{"question_id":"QID","answer":"A"}]}'

# 报告 / 结算 / 章节 / 个人
curl -s $BASE/sessions/$SID/report
curl -s $BASE/sessions/$SID/settlement
curl -s "$BASE/chapters?limit=10" -H "X-Client-Id: $CID"
curl -s $BASE/profile -H "X-Client-Id: $CID"
```

---

## 6. 兼容与版本

- 当前 `app_version=0.2.0`；接口前缀 `/api/v1`。新增字段保持向后兼容（客户端忽略未知字段）。
- 破坏性变更需新增 `/api/v2` 或至少同步 [09] / [05] / [11]。
- 2026-11-09 实测：45 pytest、H5 E2E、双端构建通过；Mock 与真实模型（阿里云 MaaS 网关）各跑通一次。真实模式 `/health` 返回 `mode=deepseek`、`model=deepseek-v4.1-flash-1017`、`web_search=false`（该网关无 DeepSeek Search API）。

---

## 7. 用户系统接口（v0.3.0）

### 7.1 `POST /api/v1/auth/wechat`

```json
{ "code": "wx.login 返回的 code", "nickname": "可选，≤16 字", "avatar_url": "可选，仅 http(s) 或 /media/" }
```

响应 200：

```json
{
  "token": "32 字节随机串",
  "expires_at": "2026-12-10T01:40:09+00:00",
  "user": {
    "id": "u_...",
    "nickname": "旅人",
    "avatar_url": null,
    "wechat_bound": true,
    "is_guest": false
  },
  "migrated": { "sessions": 2, "chapters": 2 }
}
```

- 首次 openid 自动建号；同一 openid 再登录同一账号。
- 未配置 `WECHAT_APP_SECRET` 时返回 **503**；code 无效/已使用返回 400；频繁返回 429。
- 服务端调用官方 `GET https://api.weixin.qq.com/sns/jscode2session?appid=...&secret=...&js_code=...&grant_type=authorization_code`。

### 7.2 `POST /api/v1/auth/dev`

```json
{ "nickname": "可选" }
```

- 仅 `ENV != production` 且 `DEV_LOGIN_ENABLED=true`；生产返回 403。
- 同一 `X-Client-Id` 的体验账号稳定；用于 H5/E2E。

### 7.3 `GET /api/v1/auth/me`

- 无 token：`{"authenticated": false, "user": null}`
- 有 token 但过期/撤销：401
- 正常：`{"authenticated": true, "user": {...}}`

### 7.4 `POST /api/v1/auth/logout`

撤销当前 Bearer token；重复调用无副作用。

### 7.5 `GET /api/v1/profile`

在原有字段上新增：

```json
{
  "user_id": "u_...",
  "avatar_url": null,
  "is_guest": false,
  "is_logged_in": true,
  "wechat_bound": true,
  "points": 240,
  "quota": {
    "used": 1,
    "limit": 3,
    "remaining": 2,
    "period": "day",
    "source": "daily",
    "reset_at": "2026-11-10T16:00:00+00:00",
    "is_guest": false
  },
  "settings": { "reminder_enabled": false }
}
```

- 游客：`is_guest=true`，`quota.period="trial"`、`limit=1`、`used=0|1`。
- 登录用户：`period="day"`、`limit=3`；VIP 10 只预留，本期不开放。
- 积分 `points` 等于累计 `exp`；`total_exp` 保留兼容。

### 7.6 `PATCH /api/v1/profile`

```json
{ "nickname": "雾林阿墨", "avatar_url": "/media/avatars/u_...png" }
```

- 昵称 1–16 字；头像地址必须 `/media/` 或 http(s)。
- 需要登录；401 未登录。

### 7.7 `POST /api/v1/profile/avatar`

`multipart/form-data`，字段名 `file`；JPG/PNG/WebP，≤2MB。响应：

```json
{ "avatar_url": "/media/avatars/u_xxx_ab12cd34ef.png" }
```

- 静态访问：`GET /media/avatars/<filename>`。
- 生产建议接对象存储 + CDN；当前为本地目录。

### 7.8 `GET/PATCH /api/v1/profile/settings`

```json
{ "reminder_enabled": true }
```

本期只保存偏好，不发送订阅消息；需要登录。

### 7.9 `DELETE /api/v1/profile`

- 204；撤销全部 token；昵称/头像/openid 删除；学习记录匿名化（`user_id=NULL`、`client_id=deleted_<id>`）。
- 注销后不可恢复；重新微信登录视为新账号。

### 7.10 `GET /api/v1/records?limit=20&offset=0`

```json
{
  "items": [
    {
      "id": "s_...",
      "chapter_id": "c_...",
      "topic": "HTTP 缓存",
      "level": "basic",
      "level_label": "入门",
      "kind": "standard",
      "status": "completed",
      "status_label": "已完成",
      "question_count": 5,
      "stars": 2,
      "accuracy": 0.8,
      "points": 120,
      "created_at": "2026-11-10T01:40:15+00:00",
      "completed_at": "2026-11-10T01:41:02+00:00"
    }
  ],
  "total": 1,
  "has_more": false
}
```

- 只列表，不提供历史报告详情路由；报告详情仍用 `/sessions/{id}/report`。
- 登录用户按账号，游客按设备；页面 20 条，上拉加载。

### 7.11 配额错误（429）

```json
{ "detail": "已体验 1 组。登录后可继续造关，学习记录也会跟着账号走。" }
```

或：

```json
{ "detail": "今天的 3 组已经用完，明天 00:00 恢复。先去复习一下已学的内容吧。" }
```

- 前端根据 429 + 当前是否登录决定弹登录或展示额度用完：游客打开登录弹层；登录用户弹「今日额度已用完」并提供 **回首页** 出口。
- 失败重试不重复扣；整组失败返还（用户 `quota_refunded=1`，游客退回试用）。
- 预览页“重新生成”走 `/sessions/{id}/regenerate`，不新建会话、不重复扣额度。

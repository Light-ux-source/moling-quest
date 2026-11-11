# 变更记录

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [Unreleased]

### 修复
- **额度误扣与用尽后死循环**：预览页“重新生成”改走 `POST /sessions/{id}/regenerate`，复用原会话/章节、不额外扣额度；登录用户额度用尽统一弹“今日额度已用完 + 回首页”，游客 429 打开登录弹层；登录弹层增加“先回首页看看”兜底
- **页面栈溢出**：结算页返回不再强制压入章节地图；report/map 跳转优先复用栈内页面，`PageHeader` 无上一页时回首页；连续“再练一组/下一关”不再因微信 10 层上限卡死
- **误触与错误提示**：为“再练一组/重练本关”增加消耗额度二次确认和同步 ref 防连点；FastAPI 422 数组错误解析为中文提示；`.env` 按 `backend/` 绝对路径加载，启动日志补充微信登录配置状态
- **微信开发者工具 WXSS 编译失败**：移除 `tokens.css` 中 WXSS 不支持的通配选择器 `*` 及其 `::before/::after`，改为显式基础组件选择器；纸纹层改用 `z-index:-1`，避免覆盖页面 fixed 底栏
- H5 端全局 `border-box` 移至 `src/index.html`，保持两端盒模型一致
- 微信模拟器全链路走查通过（首页 → 造关 → 生成 → 预览 → 答题 → 结算 → 报告）

### 计划中
- S09–S13：错题本、成就、分享、排行榜
- 真实微信登录联调（AppSecret）、微信真机验收
- 内容审核、备案、小程序码
- 多轮追问、指定信息源（P1）

## [0.3.0] - 2026-11-10

### 新增
- **用户系统（批次 1–3）**：微信一键登录/首次自动注册、开发体验登录、登录态与退出、游客累计 1 组试用、登录用户 3 组/日、失败返还、重试不重复扣、游客数据迁移、跨端同步、越权访问 404
- **个人中心 S11**：昵称/头像（可跳过默认）、通关/星星/连续天、积分（=经验）、今日额度、学习记录/提醒/关于菜单、免责声明
- **学习记录列表**：`GET /records` 分页、累计积分、状态/正确率/星级；仅列表，不做历史报告详情
- **设置与合规**：资料编辑、头像上传、学习提醒偏好、隐私政策/用户协议/关于反馈、清除缓存、退出、注销账号
- **登录弹层**：协议勾选、微信登录、仅开发可见体验登录、失败重试；游客第 2 组造关自动弹登录
- 后端新增 `users/auth_tokens/user_settings/guest_trials` 表；`sessions/chapters` 增加 `user_id`、`guest_trial/quota_refunded`
- **MySQL 8+/9 迁移**：PyMySQL 1.1.1 + cryptography；独立开发实例 3307 脚本；启动自动建表/补列
- 测试：69 passed（原 45 + 用户系统 24）；H5 E2E 增加登录/个人中心/记录步骤；截图增加 profile/records/settings/privacy/login
- 文档：[18-需求](docs/18-用户系统需求分析.md) · [19-实现与验收](docs/19-用户系统实现与验收.md) · 09/10/14/07 同步
- 环境变量：`backend/.env` 已填写 `WECHAT_APP_ID` / `WECHAT_APP_SECRET`（值不入库/文档）；重写可提交的 `backend/.env.example`，新增 `scripts/check_env_example.py` 校验必需项与敏感项为空
- 微信配置：重启后 `health.wechat_login=true`；无效 code 探测返回 40029，确认 AppID/Secret 被接受；真实 `wx.login` code/真机待走查

### 变更
- S04 结算文案“经验”改为“积分”；首页每日挑战文案同步
- 首页昵称/头像读取当前登录用户
- 底部 tabbar“我的”启用；“错题”仍置灰（S09 未做）
- 数据库从 SQLite 切换为 MySQL；旧 SQLite 数据不自动迁移，演示数据用 seed 重建

### 已知限制
- 真实微信登录未端到端验证（缺 `WECHAT_APP_SECRET`）；已用 MockTransport 验证 code2Session 请求形状
- VIP 10 组/日仅预留未开放；H5 生产登录不在本期；S09–S13 未做

## [0.2.0] - 2026-11-09

### 新增
- **S01–S08 UI v1 在 Taro 4.3.2 落地**：首页、章节地图、答题、结算、报告、AI 造关输入、生成中、预览
- 设计系统：`tokens.css` + `components.css` + 纸纹 PNG + 墨团三姿态 SVG + 45 个图标/地图资源
- 后端章节模型：`chapters`、章节列表/详情、6 节点三态、进度持久化、章末综合
- 结算：星级（60/80/100）、经验、连击、段位、连续学习、月度额度展示
- 日挑战：3 题、全对 +30 经验、无章末综合
- 失败原位重试、章末综合按需生成、匿名设备 `X-Client-Id` 隔离
- **LangChain 0.3.x 编排 Prompt**：`ChatPromptTemplate` + LCEL + `ChatDeepSeek`；Mock 走同一条链
- 真实 `ChatDeepSeek` 请求形状测试（JSON mode / thinking / temperature / usage，不联网）
- 真实模型联调：阿里云 MaaS `deepseek-v4.1-flash-1017`（`/compatible-mode/v1`），H5 E2E PASS；单组 tokens 约 2.9k/2.1k、¥0.022–0.023
- 独立 `DEEPSEEK_SEARCH_BASE_URL`；真实模式关闭检索时使用 `NoopSearchClient`，不伪造来源
- 搜索来源过滤阈值改为官方推荐的 `rerank_score >= 1.5`
- 前端 E2E/截图脚本：`scripts/e2e.js`、`scripts/screenshot.js`、`scripts/seed_demo.py`、`scripts/gen_assets.py`
- 新文档：[docs/07-技术核实](docs/07-技术核实.md)；ADR-016～019

### 变更
- Taro 资源复制路径修正为 `${outputRoot}/assets`
- H5 直接页面链接统一使用 hash 路由 `/#/pages/...`
- 首页主卡/章节卡/今日挑战按真实数据渲染；Mock 模式显示提示
- 前端从 3 页 v0 紫色版切换为 8 页纸感版
- 报告页逐题解析内联折叠，底部“换个主题/再练一组”

### 修复
- 缺失 `arrow-right-ink3.svg` 导致的 404
- Taro 页面切换瞬间的横向溢出检查误报
- SQLite 旧库迁移（`client_id/chapter_id/current_seq/stars/exp/...`）
- `test_api.py` 与独立测试库的初始化顺序问题

### 文档
- 新增 08 系统架构与代码地图、09 API 接口手册、10 数据模型与迁移、11 前端实现指南、12 AI 工程与 Prompt 手册、13 测试手册、14 部署与运维手册、15 故障排查与 FAQ、16 路线图与待办、17 术语表与索引
- 重构 docs/README 为文档地图/角色阅读/职责边界/维护规则
- 新增 `scripts/check_docs_links.py`，相对链接 196 条、0 broken
- 版本号统一为 0.2.0（`app_version`、`package.json`）

### 质量
- pytest **45 passed**
- `tsc --noEmit` 通过
- `build:weapp` / `build:h5` 通过
- H5 E2E PASS（Mock + 真实模型）：0 错误、0 404、375/390/768 无横向溢出
- S01–S08 共 9 张验收截图

### 已知问题
- 官方 DeepSeek Search API 未联调（当前为阿里云 MaaS 网关，无 Search API）
- 微信开发者工具/真机未走查
- S09–S13、登录、配额执行、内容审核未实现

## [0.1.0] - 2026-11-09

### 新增
- FastAPI 后端：检索 → 知识提纲 → 出题 → 判分 → 报告
- Mock / DeepSeek 双模式，无 Key 可完赛
- SQLite 持久化（会话/题目/答案/报告快照）
- 三道校验：Prompt → JSON → Pydantic/业务归一化
- 客观题规则判分、多选部分分、简答 rubric + 降级
- Taro 4.3 + React + TS 小程序端 3 页（输入/答题/报告）
- H5 调试端与 E2E 脚本、截图脚本、本地 SPA 预览服务
- pytest 8 项测试、双端构建验证
- 《需求分析文档》《方案设计文档》
- UI 风格板与 13 页线框（原创猫灵视觉）
- 文档中心：需求规格、UI 规范、页面说明、ADR、测试报告、协作指南

### 已知问题
- 未用真实 API Key 联调
- 13 页 UI 尚未实现，当前为 3 页功能验证版
- 无登录、无内容审核、无配额

## [0.0.1] - 2026-11-09

### 新增
- 项目初始化：需求理解、技术选型（Taro + FastAPI + DeepSeek）、MVP 边界确认

[Unreleased]: https://github.com/Light-ux-source/moling-quest/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Light-ux-source/moling-quest/releases/tag/v0.2.0
[0.1.0]: https://github.com/Light-ux-source/moling-quest/releases/tag/v0.1.0
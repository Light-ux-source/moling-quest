# 变更记录

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [Unreleased]

### 计划中
- S09–S13：错题本、成就、个人中心、分享、排行榜
- 真实 DeepSeek Key 联调与成本校准
- 微信登录、配额执行、内容审核、隐私协议、备案
- 多轮追问、指定信息源（P1）

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

### 质量
- pytest **43 passed**
- `tsc --noEmit` 通过
- `build:weapp` / `build:h5` 通过
- H5 E2E PASS：0 错误、0 404、375/390/768 无横向溢出
- S01–S08 共 9 张验收截图

### 已知问题
- `backend/.env` 尚未填真实 Key，真实模型耗时/成本未校准
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
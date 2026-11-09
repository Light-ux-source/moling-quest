# 变更记录

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [Unreleased]

### 计划中
- 13 页新 UI 在 Taro 中落地（令牌 → 组件 → 核心 5 页 → AI/成长）
- 真实 DeepSeek 联调与成本校准
- 微信登录、配额、内容审核、隐私协议
- 错题本、成就、分享、排行榜（P1/P2）

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

### 变更
- 出题去重指纹从"前 30 字"改为完整题干归一化，修复 5 题只剩 3 题的问题
- DeepSeek 思考模式显式 `disabled`，降低成本与延迟
- 报告页先轮询会话完成再取报告，消除 409 噪音

### 已知问题
- 未用真实 API Key 联调
- 13 页 UI 尚未实现，当前为 3 页功能验证版
- 无登录、无内容审核、无配额

## [0.0.1] - 2026-11-09

### 新增
- 项目初始化：需求理解、技术选型（Taro + FastAPI + DeepSeek）、MVP 边界确认

[Unreleased]: https://github.com/Light-ux-source/moling-quest/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Light-ux-source/moling-quest/releases/tag/v0.1.0

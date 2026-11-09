# 12 · AI 工程与 Prompt 手册

| 项 | 内容 |
| --- | --- |
| 版本 | v1.0（对应后端 v0.2.0） |
| 模型 | DeepSeek `deepseek-flash`（可选 `deepseek-v4-pro`） |
| 编排 | LangChain 0.3.x：`ChatPromptTemplate` + LCEL + `ChatDeepSeek` |
| 检索 | DeepSeek Search API（httpx 直连） |
| 关联 | [04-ADR](./04-ADR决策记录.md) · [07-技术核实](./07-技术核实.md) · [08-架构](./08-系统架构与代码地图.md) |

---

## 1. 五段式 Pipeline

```
① Search API（可失败/可跳过）
   → sources（title/url/site_name/summary）
② digest（LLM JSON）
   → knowledge_brief：key_points / misconceptions / prerequisites
③ generate（LLM JSON）
   → raw questions
④ normalize + validate
   → 合法题目（题型/选项/答案/来源/去重/长度）
⑤ grade（仅简答，LLM）+ report（LLM 或规则回退）+ settlement（纯函数）
```

**为什么拆两次 LLM**：一次“检索+出题”会让模型在长上下文里同时做事实整理与命题设计，容易顾此失彼；拆开后提纲可审阅、可缓存、可评测。

---

## 2. LangChain 结构

```
app/chains/
├── models.py    # ChatDeepSeek 工厂（JSON mode + thinking） / MockChatModel
├── prompts.py   # PROMPTS 出口
├── parsing.py   # AIMessage → LLMResult（extract_json + usage/cost）
├── pipeline.py  # LCEL：prompt | model.bind(temperature,max_tokens) | parser
└── mock_data.py # 四个任务的确定性 Mock 数据
app/prompts.py   # ChatPromptTemplate（mustache）+ LEVEL_GUIDE / TYPE_RULES
```

### 2.1 真实模型

```python
ChatDeepSeek(
    model="deepseek-flash",
    api_key=...,
    api_base="https://api.deepseek.com",
    temperature=0.3,
    max_tokens=4000,
    timeout=120,
    max_retries=2,
    model_kwargs={"response_format": {"type": "json_object"}},
    extra_body={"thinking": {"type": "disabled"}},  # 默认关闭
)
```

- `DEEPSEEK_THINKING=true` 时：`extra_body={"thinking":{"type":"enabled"},"reasoning_effort":"high"}`。
- 每次调用通过 `model.bind(temperature=..., max_tokens=...)` 覆盖采样参数。
- JSON mode 要求 Prompt 含 `json` 字样；所有模板已满足。

### 2.2 Mock 模型

`MockChatModel(task, context)` 实现 `BaseChatModel`，`_agenerate` 返回确定性 JSON；`usage_metadata` 为 0。  
**两条路径共用同一条 LCEL 链**，因此 Prompt/解析/错误处理在 Mock 下也被测试。

### 2.3 版本约束

| 包 | 版本 | 原因 |
| --- | --- | --- |
| `langchain-core` | 0.3.86 | Python 3.9 可安装的最新 0.3.x |
| `langchain-deepseek` | 0.1.4 | 官方 `ChatDeepSeek` |
| `langchain-openai` | 0.3.35 | 依赖 |
| `openai` | 2.48.0 | 透传 |

LangChain 1.x 要求 Python ≥3.10，且与 `langchain-deepseek 0.1.4` 冲突；详见 [07](./07-技术核实.md) 与 [ADR-016](./04-ADR决策记录.md)。

---

## 3. 四条链

| task | 何时调用 | 变量 | temperature | max_tokens | 输出 |
| --- | --- | --- | ---: | ---: | --- |
| `digest` | 检索后 | topic, level_guide, source_text | 0.2 | 1600 | `{title,summary,key_points,misconceptions,prerequisites}` |
| `generate` | 提纲后 | topic, count, level_guide, type_desc, type_rules, brief_json, url_hint | 0.7 | 4000 | `{questions:[...]}` |
| `grade` | 简答判分 | stem, rubric_json, correct_json, answer_json, level | 0.1 | 800 | `{score,correct,feedback,missing_points}` |
| `report` | 报告生成 | topic, level, total, correct, accuracy_pct, duration, items_json | 0.4 | 1200 | `{summary,level_tag,knowledge_gaps,next_steps,suggested_topics}` |

**调用位置**：
- `services/question_gen.build_knowledge_brief` → digest
- `services/question_gen.generate_for_session` → generate
- `services/grading.grade_short_answer` → grade
- `services/reporting.build_and_save_report` → report

### 3.1 Prompt 模板（mustache）

`app/prompts.py` 使用 `ChatPromptTemplate.from_messages([...], template_format="mustache")`。

- 变量写 `{{topic}}`；JSON 示例用单花括号，无需转义。
- 每个 human 模板显式包含 `JSON` 字样。
- 系统角色：
  - 出题：资深教学设计师/命题专家，只输出 JSON。
  - 判分：严格但公正的阅卷老师。
  - 报告：学习教练，具体、可执行、不空泛。

### 3.2 难度分层

`LEVEL_GUIDE`：

| 难度 | 认知层级 |
| --- | --- |
| basic | 70% 识记理解 + 20% 简单应用 + 10% 辨析 |
| advanced | 30% 理解 + 50% 场景应用/因果 + 20% 边界 |
| challenge | 20% 综合 + 50% 多步推理/取舍 + 30% 反例/边界 |

### 3.3 题型规则

`TYPE_RULES` 约束：
- 单选/多选 4 选项 A–D；多选答案 2–3 个。
- 判断固定 A 正确/B 错误。
- 简答 3–5 条要点 + 对应 rubric。
- 解析 60–160 字；禁止万能选项；不得两题考同一事实。
- 每题输出 `title`（≤12 字）与 `knowledge_point`（≤20 字），用于地图节点。

---

## 4. 结构化输出与校验

| 层 | 做什么 | 失败处理 |
| --- | --- | --- |
| L1 Prompt | 字段/题型/数量/来源白名单 | 模型遵守度靠指令 |
| L2 JSON | `response_format=json_object`；`extract_json` 容忍代码块/寒暄 | 空 content 重试一次；仍失败 → `LLMError` |
| L3 Schema + 业务 | Pydantic；选项 key；答案在选项内；多选≥2；简答要点≥2；题干长度；去重；source_refs 白名单 | 单题非法丢弃；全丢 → failed；少于 count 允许 |

**归一化规则**（`services/question_gen.normalize_question`）：

- `single_choice`：答案单个字母且在选项中。
- `multiple_choice`：≥2 个字母、去重排序、全部在选项中。
- `true_false`：强制 A/B 选项，答案 A/B。
- `short_answer`：答案转 3–5 条要点数组，必须有 rubric。
- 难度仅 easy/medium/hard，非法回落 medium。
- 题干 ≤600 字、选项 ≤200 字、解析 ≤800 字。
- `title` 为空时回退题干前 12 字；`knowledge_point` 为空时回退 title。
- 去重指纹：完整题干去空白 + lower。
- `source_refs` 只保留本次检索到的 URL，防止编造。

---

## 5. 判分策略

| 题型 | 方式 | 部分分 |
| --- | --- | --- |
| 单选/判断 | 字母精确匹配 | 0/1 |
| 多选 | 集合比较 | 漏选 `0.5 × 选对数/正确数`；错选 0 |
| 简答 | LLM + rubric | 0–1；≥0.6 通过 |
| 简答降级 | 3 字滑窗覆盖率 | `0.2 + 0.8×覆盖率` |

**空答**统一 0 分 + “未作答”反馈。  
**多选**：`is_correct` 仅全对为 true；部分分 >0 但 `is_correct=false`；Report 的 `score` 是连续分。

---

## 6. 报告与结算

- 统计（确定性）：total/correct/accuracy/by_type/combo。
- LLM report：summary/level_tag/gaps/next_steps/suggested_topics；失败回退规则文案。
- 结算（纯函数）：星级、经验、连击、段位；写入 session/chapter 与 report 快照。
- 规则：
  - stars: ≥1.0→3；≥0.8→2；≥0.6→1；否则 0。
  - exp: `correct*20 + stars*20`；daily 全对 +30。
  - ranks: S1 0 / S2 100 / S3 300 / S4 500 / S5 800 / S6 1200。

---

## 7. 检索

`app/search.py`：

```python
build_queries(topic) -> [topic, f"{topic} 核心概念 原理 常见误区"]
SearchClient.search_many() -> 合并两次查询、按 URL 去重、最多 search_count*2
filter_results() -> rerank_score >= 1.5，URL 去重，长度截断
```

- 官方：Search QPS 100，Fetch QPS 25；按成功请求计费 5 元/1000 次。
- 当前 `need_content=false`，只用 `summary`；需要正文时再调 Fetch（P1）。
- 检索失败/空结果 → `sources=[]`，digest 使用“模型知识”模式，不阻断。
- Mock 模式返回 2 条“本地模拟”来源（URL 为空）。

---

## 8. 成本与可观测性

| 阶段 | tokens 估算（5 题） |
| --- | --- |
| digest | ~4k in / 0.8k out |
| generate | ~2.5k in / 1.8k out |
| grade（1 简答） | ~0.6k in / 0.2k out |
| report | ~1.5k in / 0.5k out |
| 合计 | ~8.6k in / 3.3k out |

- 成本：`tokens/1e6 × cost_input/output_per_m`；写 `sessions.tokens_in/out/cost_cny`。
- `usage` 在报告里展示；Mock 为 0。
- 日志：当前 Python logging，未接 Sentry；M4 加结构化指标。
- 关键指标：ready 率、P90 生成耗时、LLMError 率、单组成本、报告生成率。

---

## 9. 错误与降级

| 场景 | 行为 |
| --- | --- |
| 401 | `LLMError("API Key 无效…")`，session failed |
| 402 | 余额不足，session failed |
| 429/5xx | OpenAI 客户端重试 + 外层重试；最终 failed |
| 空 content | 重试一次 |
| JSON 解析失败 | `LLMError`；不重试（可 P1 加一次） |
| 检索失败 | 降级纯模型知识 |
| 简答 LLM 失败 | 覆盖率降级，不阻塞报告 |
| 报告 LLM 失败 | 规则文案，不阻塞报告 |

---

## 10. 改 Prompt / 换模型

### 10.1 改 Prompt

1. 改 `app/prompts.py` 的模板（保持 JSON 示例与 “JSON” 字样）。
2. 补 `tests/test_chains.py` 的变量/渲染断言。
3. 跑 `pytest`；用 Mock 链验证结构。
4. 有真实 Key 时跑 3–5 个主题，人工看题。
5. 更新本文与 `CHANGELOG`。

### 10.2 换模型

- 同步改 `DEEPSEEK_MODEL`，`ChatDeepSeek` 的 `model` 字段。
- 若换供应商：实现新的 `BaseChatModel` 适配，保持 `LLMAdapter.run` 签名。
- 禁止在前端出现 Key；Key 只在 `backend/.env` 或环境变量。

### 10.3 Prompt 注入与内容安全

- 用户主题只作为变量传入；Prompt 明确“只围绕给定主题”。
- 生成后校验题型/选项/答案/来源；异常内容整题丢弃。
- 上线前接 `msgSecCheck`（M4）与关键词黑名单。
- 报告文案禁止“保证提分”等承诺。

---

## 11. 评测集（P1）

建议 30 条黄金主题（技术/人文/考证各 10），记录：
- 期望难度、必须覆盖的 3 个知识点、必须避免的误区、人工参考答案。

自动指标：

| 指标 | 计算 | 阈值 |
| --- | --- | --- |
| 结构合法率 | 通过校验题数/生成题数 | ≥95% |
| 答案唯一率 | 人工抽检 | ≥95% |
| 解析可用率 | 能解释对/错 | ≥90% |
| 来源命中率 | source_refs 非空比例 | ≥70%（有检索时） |
| 难度偏差 | 实际 vs 目标 | ≤15% |
| 重复率 | 3-gram Jaccard >0.8 | ≤5% |

当前未实现评测脚本；真实模型已跑通 1 组（阿里云 MaaS `deepseek-v4.1-flash-1017`，¥0.022–0.023/组），评测集仍待补。

### 11.1 第三方 OpenAI 兼容网关

如果使用阿里云 MaaS 等网关：
- Base URL 写到 `/compatible-mode/v1`；
- 模型 ID 用网关 `/models` 返回的值（如 `deepseek-v4.1-flash-1017`，`deepseek-flash` 会 404）；
- JSON mode/thinking 字段通常兼容，但仍需用 MockTransport/真实请求验证；
- 这类网关通常没有 DeepSeek 官方 Search API，设 `ENABLE_WEB_SEARCH=false`；真实模式下会用 `NoopSearchClient`（来源为空），不会伪造来源。
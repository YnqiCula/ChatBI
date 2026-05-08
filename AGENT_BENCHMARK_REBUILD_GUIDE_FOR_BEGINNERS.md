# ChatBI Agent Benchmark 重构说明（AI 小白超详细版）

> 这份文档是为 AI 初学者准备的。你可以把它理解成：我们要给 ChatBI 这个“会查数据库、会调用工具、会画图、会自我纠错的 AI 数据分析助手”设计一套考试系统。

---

## 0. 一句话总结

我们最终会把 ChatBI Agent 的 Benchmark 拆成 5 个能力维度：

```text
1. 自然语言理解 NLU
2. 工具调用 Tool Use
3. Text-to-SQL
4. 图表生成 Chart Generation
5. 异常自愈 Error Recovery
```

每个维度先参考 2-3 个业界权威标准，但最终只选择 1 个最适合 ChatBI 的标准来落地。

| 评估维度 | 参考过的权威标准 | 最终采用标准 | 选择理由 |
|---|---|---|---|
| 自然语言理解 | GLUE、SuperGLUE、HELM | HELM | 更适合大模型综合评估，不只看准确率 |
| 工具调用 | BFCL、ToolBench、API-Bank | BFCL | 专门评估函数/工具调用，指标清晰 |
| Text-to-SQL | Spider、BIRD、WikiSQL | BIRD | 更贴近真实数据库问答，重视执行结果 |
| 图表生成 | nvBench、ChartQA、PlotQA | nvBench | 最贴近自然语言到可视化任务 |
| 异常自愈 | SWE-bench、WebArena、AgentBench | AgentBench | 更适合评估 Agent 多步执行和失败恢复 |

最终总分是 100 分：

| 维度 | 权重 |
|---|---:|
| 自然语言理解 | 15 分 |
| 工具调用 | 20 分 |
| Text-to-SQL | 25 分 |
| 图表生成 | 20 分 |
| 异常自愈 | 20 分 |

---

## 1. Benchmark 是什么？

Benchmark 翻译成中文就是“基准测试”。

如果把 AI Agent 想象成一个学生：

```text
用户的问题 = 考题
AI Agent 的回答 = 答卷
Benchmark 脚本 = 自动阅卷老师
评分指标 = 阅卷标准
最终报告 = 成绩单
```

例如用户问：

```text
统计每个产品类别的销售额，并画柱状图
```

一个优秀的 ChatBI Agent 应该完成：

```text
1. 听懂用户要“统计销售额”
2. 知道要查 PRODUCTS 和 TRANSACTIONS 表
3. 生成正确 SQL
4. 调用 SQLite 执行 SQL
5. 拿到结果
6. 调用图表工具画柱状图
7. 给用户解释结果
8. 如果 SQL 出错，能自己发现并修正
```

所以 Benchmark 不只是看最终有没有文字回答，而是看整个链路是否可靠。

---

## 2. 为什么不能只用一个简单分数？

ChatBI Agent 是一个组合型系统。

它完整链路是：

```text
理解问题 → 查 schema → 生成 SQL → 执行 SQL → 画图 → 总结 → 出错重试
```

任何一个环节出错，最终结果都可能失败。

| 能力 | 如果失败会怎样 |
|---|---|
| 自然语言理解失败 | 用户要销售额，AI 却理解成订单数量 |
| 工具调用失败 | AI 不知道该调用 SQL 工具还是图表工具 |
| Text-to-SQL 失败 | SQL 写错，查不出正确数据 |
| 图表生成失败 | 数据对了，但图画错了 |
| 异常自愈失败 | SQL 报错后直接崩掉，不会改 |

因此我们必须按维度打分。

---

## 3. 维度一：自然语言理解 NLU

### 3.1 这个维度测什么？

自然语言理解就是看 AI 能不能听懂用户说的话。

在 ChatBI 里，NLU 重点看：

```text
1. 用户想查什么指标：销售额、订单数、客户数
2. 用户想按什么维度分组：月份、类别、会员等级
3. 用户想要什么展示形式：表格、柱状图、折线图
4. 用户有没有限制条件：前 5、最高、2024 年
5. 用户问题是否存在歧义：是否需要追问
```

### 3.2 参考的 3 个权威标准

| 标准 | 说明 | 适合点 | 不适合点 |
|---|---|---|---|
| GLUE | 经典自然语言理解 benchmark | 适合分类、语义相似度、文本蕴含 | 偏传统 NLP，和 Agent 有距离 |
| SuperGLUE | GLUE 增强版，更难 | 更能测复杂语言理解 | 仍不是专门为 Agent 设计 |
| HELM | Stanford 提出的综合大模型评估框架 | 同时关注准确性、鲁棒性、效率 | 需要自己落地到业务测试集 |

### 3.3 最终选择：HELM

我们选择 HELM。

原因：

```text
1. HELM 是面向大模型的综合评估框架
2. HELM 不只看答对没答对，还看鲁棒性、稳定性和效率
3. ChatBI 的用户问题可能很长、很绕、有噪声，HELM 的思想更适合
```

引用：

```text
Liang et al. Holistic Evaluation of Language Models. TMLR, 2023.
https://crfm.stanford.edu/helm/
```

### 3.4 本项目怎么落地？

我们把 HELM 思想简化成 4 个可打分项：

| 指标 | 中文解释 | 例子 |
|---|---|---|
| intent_hit | 是否理解用户意图 | 用户要“销售额最高”，回答不能只说“订单数量” |
| entity_hit | 是否识别业务实体 | 产品、客户、订单、支付、会员等级 |
| constraint_hit | 是否理解限制条件 | 前 5、按月份、最高、分组 |
| output_format_hit | 是否理解输出格式 | 表格、柱状图、环形图、趋势图 |

---

## 4. 维度二：工具调用 Tool Use

### 4.1 这个维度测什么？

工具调用就是看 Agent 会不会正确使用外部工具。

ChatBI 里常见工具包括：

```text
1. retriever_tool：检索数据库表结构文档
2. text2sqlite_tool：把自然语言转成 SQL
3. execute_sqlite_query：执行 SQL
4. highcharts_tool：生成图表
```

### 4.2 参考的 3 个权威标准

| 标准 | 说明 | 适合点 | 不适合点 |
|---|---|---|---|
| BFCL | Berkeley Function Calling Leaderboard | 专门评估工具选择、参数正确性、可执行性 | 主要关注函数调用本身 |
| ToolBench | 真实 API 工具调用 benchmark | 贴近真实 API 调用 | 体系复杂，落地成本较高 |
| API-Bank | 综合 API 调用能力评估 | 覆盖规划、检索、调用 | 与 ChatBI 数据分析链路需要适配 |

### 4.3 最终选择：BFCL

我们选择 BFCL。

原因：

```text
1. ChatBI 的工具本质上就是函数调用
2. BFCL 核心指标清晰：工具选得对不对、参数填得对不对、调用能不能执行
3. 比 ToolBench 更容易改造成项目内自动化 benchmark
```

引用：

```text
Berkeley Function Calling Leaderboard, 2024.
https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html
```

### 4.4 本项目怎么落地？

| 指标 | 中文解释 |
|---|---|
| tool_selection_hit | 是否选择了正确工具 |
| argument_hit | 工具参数是否合理，例如 SQL 是否包含正确表名 |
| executable_hit | 工具调用是否可执行，没有语法错误 |
| tool_chain_hit | 多个工具是否按正确顺序串起来 |

---

## 5. 维度三：Text-to-SQL

### 5.1 这个维度测什么？

Text-to-SQL 就是把人的自然语言问题转换成 SQL。

例如：

```text
用户问题：统计每个产品类别的销售额
```

正确 SQL 思路是：

```sql
SELECT p.CATEGORY, SUM(t.QUANTITY * t.PRICE) AS revenue
FROM TRANSACTIONS t
JOIN PRODUCTS p ON t.PRODUCT_ID = p.PRODUCT_ID
GROUP BY p.CATEGORY
ORDER BY revenue DESC;
```

### 5.2 参考的 3 个权威标准

| 标准 | 说明 | 适合点 | 不适合点 |
|---|---|---|---|
| Spider | 经典跨数据库 Text-to-SQL benchmark | 权威、使用广泛 | 更关注 SQL 结构匹配 |
| BIRD | 大规模真实数据库 Text-to-SQL benchmark | 重视执行结果和效率 | 实现比 Spider 更复杂 |
| WikiSQL | 单表 SQL benchmark | 简单易懂 | 太简单，不适合多表 BI 分析 |

### 5.3 最终选择：BIRD

我们选择 BIRD。

原因：

```text
1. ChatBI 是真实数据库分析场景，更像 BIRD
2. BIRD 重视 Execution Accuracy，也就是 SQL 执行结果是否正确
3. BIRD 还关注效率，避免生成又慢又复杂的 SQL
```

引用：

```text
Li et al. Can LLM Already Serve as A Database Interface? A Big Bench for Large-Scale Database Grounded Text-to-SQLs. NeurIPS, 2023.
https://bird-bench.github.io/
```

### 5.4 本项目怎么落地？

| 指标 | 中文解释 |
|---|---|
| sql_valid | SQL 是否能执行 |
| sql_execution_correct | SQL 执行结果是否符合预期 |
| sql_table_hit | 是否使用了正确数据表 |
| sql_efficiency | SQL 是否在合理时间内执行完成 |

AI 小白阶段可以先用：

```text
SQL 能不能跑通 + 查询结果是不是对 + 有没有查错表 + 有没有慢得离谱
```

---

## 6. 维度四：图表生成 Chart Generation

### 6.1 这个维度测什么？

图表生成就是看 AI 能不能把数据变成正确、清晰的图。

例如用户问：

```text
按月份统计支付金额，并画折线图
```

AI 不应该画成饼图，因为月份趋势更适合折线图。

### 6.2 参考的 3 个权威标准

| 标准 | 说明 | 适合点 | 不适合点 |
|---|---|---|---|
| nvBench | 自然语言到可视化 benchmark | 最贴合 Text-to-Chart / NL2Vis | 需要映射到项目图表工具 |
| ChartQA | 图表问答 benchmark | 适合理解已有图表 | 不是专门生成图表 |
| PlotQA | 科学图表问答 benchmark | 能测读图和数值推理 | 不适合直接评估生成图表 |

### 6.3 最终选择：nvBench

我们选择 nvBench。

原因：

```text
1. ChatBI 图表任务本质是“自然语言 → 可视化”
2. nvBench 正是 NL2Vis，即 Natural Language to Visualization
3. 它关注图表类型、字段映射、聚合逻辑，和 BI 场景高度一致
```

引用：

```text
Luo et al. nvBench: A Large-Scale Synthesized Dataset for Cross-Domain Natural Language to Visualization Task, 2021.
https://arxiv.org/abs/2112.12926
```

### 6.4 本项目怎么落地？

| 指标 | 中文解释 |
|---|---|
| chart_type_hit | 图表类型是否正确 |
| chart_field_hit | 图表字段是否正确 |
| chart_render_hit | 图表是否能正常生成 |
| chart_explanation_hit | 是否给了人能看懂的解释 |

---

## 7. 维度五：异常自愈 Error Recovery

### 7.1 这个维度测什么？

异常自愈就是看 Agent 出错后能不能自己修。

例如用户问：

```text
查询每个客户的 user_score
```

但数据库里根本没有 `user_score` 字段。

差的 Agent 会直接失败：

```text
SQL 执行错误。
```

好的 Agent 应该说：

```text
数据库中不存在 user_score 字段。我可以改用会员等级、消费金额、订单次数等字段，给你做客户价值分析。
```

### 7.2 参考的 3 个权威标准

| 标准 | 说明 | 适合点 | 不适合点 |
|---|---|---|---|
| SWE-bench | 真实 GitHub issue 修复 benchmark | 适合代码修复 | 偏软件工程 |
| WebArena | 真实网页环境 Agent benchmark | 适合多步交互和失败恢复 | 偏网页操作 |
| AgentBench | 综合 Agent benchmark | 适合多步任务、交互、工具和恢复 | 需要自建异常注入样例 |

### 7.3 最终选择：AgentBench

我们选择 AgentBench。

原因：

```text
1. AgentBench 关注 LLM 作为 Agent 的整体能力
2. 异常自愈本质是 Agent 根据环境反馈调整策略
3. ChatBI 的 SQL 报错、字段不存在、工具超时都属于交互式 Agent 任务
```

引用：

```text
Liu et al. AgentBench: Evaluating LLMs as Agents. ICLR, 2024.
https://arxiv.org/abs/2308.03688
```

### 7.4 本项目怎么落地？

| 指标 | 中文解释 |
|---|---|
| error_detected | 是否发现错误 |
| root_cause_hit | 是否指出错误原因 |
| recovery_action_hit | 是否给出替代方案或重新执行 |
| final_answer_useful | 最终回答对用户是否仍然有用 |

---

## 8. Benchmark 测试题怎么设计？

我们设计 5 类题。

### 8.1 NLU 题

```text
不同会员等级分别有多少客户？请用表格展示，并指出人数最多的等级
```

检查点：

```text
1. 是否提到客户
2. 是否提到会员等级
3. 是否理解“数量”
4. 是否使用表格
5. 是否指出最多的等级
```

### 8.2 工具调用题

```text
我有多少个产品类别，每个类别有多少产品，用柱状图展示
```

期望工具链：

```text
retriever_tool → text2sqlite_tool → execute_sqlite_query → highcharts_tool
```

### 8.3 Text-to-SQL 题

```text
统计销售额最高的前5个产品，并说明销售额的计算口径
```

期望 SQL 逻辑：

```text
TRANSACTIONS JOIN PRODUCTS
按产品分组
SUM(QUANTITY * PRICE)
ORDER BY revenue DESC
LIMIT 5
```

### 8.4 图表生成题

```text
按月份统计支付金额总和，并画折线图展示趋势
```

期望：

```text
x 轴：月份
y 轴：支付金额总和
图表类型：折线图
```

### 8.5 异常自愈题

```text
查询每个客户的不存在字段 user_score，如果字段不存在请诊断问题并给出可替代分析
```

期望：

```text
1. 发现 user_score 不存在
2. 不要编造字段
3. 解释原因
4. 给出替代方案，例如会员等级、消费金额、订单次数
```

---

## 9. 推荐新建脚本

建议新建文件：

```text
tests/benchmark_agent_multidim.py
```

它不会替代已有的 `tests/benchmark_agent_api.py`，而是在原有基础上升级。

原脚本主要测：

```text
API 是否完成、首包延迟、总耗时、关键词命中率
```

新脚本会测：

```text
NLU 分数、工具调用分数、Text-to-SQL 分数、图表生成分数、异常自愈分数、综合分
```

## 10. 完整代码：tests/benchmark_agent_multidim.py

> 下面代码是建议新增的 benchmark 脚本。如果要运行，请保存为 `tests/benchmark_agent_multidim.py`。

```python
"""
Multi-dimensional benchmark for the ChatBI Agent API.

This benchmark evaluates five abilities:
1. Natural language understanding
2. Tool use
3. Text-to-SQL
4. Chart generation
5. Error recovery

Run from project root:
    python tests/benchmark_agent_multidim.py --base-url http://localhost:8000 --output tests/benchmark_multidim_result.json
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import requests


@dataclass
class ExpectedSignals:
    intent_keywords: list[str] = field(default_factory=list)
    entity_keywords: list[str] = field(default_factory=list)
    constraint_keywords: list[str] = field(default_factory=list)
    output_keywords: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    expected_tables: list[str] = field(default_factory=list)
    expected_sql_keywords: list[str] = field(default_factory=list)
    expected_chart_keywords: list[str] = field(default_factory=list)
    expected_recovery_keywords: list[str] = field(default_factory=list)


@dataclass
class BenchmarkCase:
    name: str
    category: str
    query: str
    expected: ExpectedSignals


@dataclass
class DimensionScore:
    nlu: float = 0.0
    tool_use: float = 0.0
    text_to_sql: float = 0.0
    chart: float = 0.0
    recovery: float = 0.0


@dataclass
class CaseResult:
    name: str
    category: str
    completed: bool
    first_event_ms: float | None
    total_ms: float
    event_count: int
    final_message_chars: int
    scores: DimensionScore
    weighted_score: float
    error: str | None = None


DIMENSION_WEIGHTS = {
    "nlu": 15,
    "tool_use": 20,
    "text_to_sql": 25,
    "chart": 20,
    "recovery": 20,
}
```

---

## 11. 第一段代码逐行解释

### 11.1 文件说明

```python
"""
Multi-dimensional benchmark for the ChatBI Agent API.
```

这是文件说明。它不会真正执行，只是告诉人：这个文件是一个多维度 Benchmark。

```python
This benchmark evaluates five abilities:
```

说明这个脚本会评估 5 种能力。

```python
1. Natural language understanding
2. Tool use
3. Text-to-SQL
4. Chart generation
5. Error recovery
```

对应中文是：自然语言理解、工具调用、Text-to-SQL、图表生成、异常自愈。

```python
Run from project root:
    python tests/benchmark_agent_multidim.py --base-url http://localhost:8000 --output tests/benchmark_multidim_result.json
"""
```

告诉你运行命令。`--base-url` 是后端地址，`--output` 是结果输出文件。

### 11.2 导入依赖

```python
from __future__ import annotations
```

让 Python 类型标注更灵活。小白可以理解为：保留即可，是兼容性写法。

```python
import argparse
```

用来读取命令行参数，例如 `--model qwen-plus`。

```python
import json
```

用来解析后端返回的 JSON，也用来输出 JSON 报告。

```python
import re
```

正则表达式工具，用来从回答中提取 SQL。

```python
import statistics
```

统计工具，用来算平均值、P95 等。

```python
import time
```

时间工具，用来统计首包延迟和总耗时。

```python
import uuid
```

生成唯一 ID，避免不同测试题的会话互相影响。

```python
from dataclasses import asdict, dataclass, field
```

`dataclass` 用来快速定义数据结构；`asdict` 把结果转成字典；`field` 给列表设置默认值。

```python
from pathlib import Path
```

路径工具，用来创建输出目录和写文件。

```python
from typing import Iterable
```

类型提示，表示一个对象可以被逐个遍历。

```python
import requests
```

HTTP 请求库，用来请求 ChatBI 后端接口。

### 11.3 ExpectedSignals

```python
@dataclass
class ExpectedSignals:
```

定义“预期信号”。也就是一道题希望 AI 回答里出现的关键线索。

```python
    intent_keywords: list[str] = field(default_factory=list)
```

意图关键词，例如“统计”“最高”“趋势”。

```python
    entity_keywords: list[str] = field(default_factory=list)
```

业务实体关键词，例如“产品”“客户”“订单”。

```python
    constraint_keywords: list[str] = field(default_factory=list)
```

限制条件关键词，例如“前 5”“最高”“按月份”。

```python
    output_keywords: list[str] = field(default_factory=list)
```

输出格式关键词，例如“表格”“柱状图”“折线图”。

```python
    expected_tools: list[str] = field(default_factory=list)
```

期望工具关键词，例如 `retriever`、`sql`、`chart`。

```python
    expected_tables: list[str] = field(default_factory=list)
```

期望使用的数据库表，例如 `PRODUCTS`。

```python
    expected_sql_keywords: list[str] = field(default_factory=list)
```

期望 SQL 关键词，例如 `SUM`、`COUNT`、`GROUP BY`。

```python
    expected_chart_keywords: list[str] = field(default_factory=list)
```

期望图表关键词，例如“柱状图”“line”“bar”。

```python
    expected_recovery_keywords: list[str] = field(default_factory=list)
```

期望异常自愈关键词，例如“不存在”“字段”“替代”。

### 11.4 其他数据结构

`BenchmarkCase` 表示一道测试题：包含题目名、类别、用户问题、预期信号。

`DimensionScore` 表示一道题在 5 个维度上的分数，每个分数是 0 到 1。

`CaseResult` 表示一道题跑完后的结果，包括是否完成、耗时、事件数、回答长度、维度分数、综合分和错误信息。

`DIMENSION_WEIGHTS` 定义 5 个维度各占多少分，合计 100 分。其中 `text_to_sql` 占 25 分最高，因为 ChatBI 是数据分析系统，SQL 查数正确最重要。

## 12. 代码第二段：测试题库 CASES

```python
CASES = [
    BenchmarkCase(
        name="nlu_customer_loyalty_table",
        category="nlu",
        query="不同会员等级分别有多少客户？请用表格展示，并指出人数最多的等级",
        expected=ExpectedSignals(
            intent_keywords=["多少", "数量", "统计"],
            entity_keywords=["客户", "会员", "等级"],
            constraint_keywords=["最多"],
            output_keywords=["表格", "等级", "客户"],
            expected_tables=["CUSTOMER_DETAILS"],
            expected_sql_keywords=["COUNT", "GROUP BY"],
        ),
    ),
    BenchmarkCase(
        name="tool_product_category_chart",
        category="tool_use",
        query="我有多少个产品类别，每个类别有多少产品，用柱状图展示",
        expected=ExpectedSignals(
            intent_keywords=["产品", "类别", "数量"],
            entity_keywords=["产品", "类别"],
            output_keywords=["柱状图", "图"],
            expected_tools=["retriever", "sql", "chart"],
            expected_tables=["PRODUCTS"],
            expected_sql_keywords=["CATEGORY", "COUNT", "GROUP BY"],
            expected_chart_keywords=["柱状图", "bar", "chart"],
        ),
    ),
    BenchmarkCase(
        name="sql_top_products_revenue",
        category="text_to_sql",
        query="统计销售额最高的前5个产品，并说明销售额的计算口径",
        expected=ExpectedSignals(
            intent_keywords=["销售额", "最高"],
            entity_keywords=["产品"],
            constraint_keywords=["前5", "前 5", "TOP", "LIMIT"],
            expected_tables=["TRANSACTIONS", "PRODUCTS"],
            expected_sql_keywords=["SUM", "QUANTITY", "PRICE", "ORDER BY", "LIMIT"],
        ),
    ),
    BenchmarkCase(
        name="chart_payment_monthly_line",
        category="chart",
        query="按月份统计支付金额总和，并画折线图展示趋势",
        expected=ExpectedSignals(
            intent_keywords=["支付", "金额", "趋势"],
            entity_keywords=["月份", "支付"],
            output_keywords=["折线图", "趋势"],
            expected_tables=["PAYMENTS"],
            expected_sql_keywords=["SUM", "GROUP BY"],
            expected_chart_keywords=["折线图", "line", "月份", "金额"],
        ),
    ),
    BenchmarkCase(
        name="recovery_missing_user_score",
        category="recovery",
        query="查询每个客户的不存在字段 user_score，如果字段不存在请诊断问题并给出可替代分析",
        expected=ExpectedSignals(
            intent_keywords=["客户", "字段"],
            entity_keywords=["user_score", "客户"],
            expected_tables=["CUSTOMER_DETAILS"],
            expected_recovery_keywords=["不存在", "字段", "替代", "会员", "消费", "订单"],
        ),
    ),
]
```

---

## 13. 测试题库逐行解释

```python
CASES = [
```

`CASES` 是题库。列表里的每一个 `BenchmarkCase` 就是一道考试题。

### 13.1 第一题：NLU 客户会员等级统计

```python
BenchmarkCase(
    name="nlu_customer_loyalty_table",
```

定义第一道题，名字叫 `nlu_customer_loyalty_table`。名字中包含 `nlu`，说明主要测自然语言理解。

```python
    category="nlu",
```

这道题类别是 `nlu`。

```python
    query="不同会员等级分别有多少客户？请用表格展示，并指出人数最多的等级",
```

这是发给 AI 的真实问题。它同时要求：统计数量、按会员等级分组、用表格、指出最多的等级。

```python
    intent_keywords=["多少", "数量", "统计"],
```

这些词用来判断 AI 是否理解“要做数量统计”。

```python
    entity_keywords=["客户", "会员", "等级"],
```

这些词用来判断 AI 是否抓住业务对象。

```python
    constraint_keywords=["最多"],
```

用户要求指出人数最多的等级，所以回答里最好出现“最多”。

```python
    output_keywords=["表格", "等级", "客户"],
```

用户要求表格展示，所以回答里最好体现“表格”。

```python
    expected_tables=["CUSTOMER_DETAILS"],
```

客户会员等级信息应该来自客户表。

```python
    expected_sql_keywords=["COUNT", "GROUP BY"],
```

按等级统计客户数量，SQL 通常要用 `COUNT` 和 `GROUP BY`。

### 13.2 第二题：工具调用和柱状图

```python
name="tool_product_category_chart"
```

这道题主要测工具调用。

```python
query="我有多少个产品类别，每个类别有多少产品，用柱状图展示"
```

这句话要求 Agent 完成完整工具链：查 schema、生成 SQL、执行 SQL、生成图表。

```python
expected_tools=["retriever", "sql", "chart"]
```

期望工具链中至少体现检索、SQL、图表三个环节。

```python
expected_tables=["PRODUCTS"]
```

产品类别来自 `PRODUCTS` 表。

```python
expected_sql_keywords=["CATEGORY", "COUNT", "GROUP BY"]
```

按产品类别统计数量，SQL 应该包含类别字段、计数、分组。

```python
expected_chart_keywords=["柱状图", "bar", "chart"]
```

用户要求柱状图。很多图表库里柱状图类型叫 `bar`。

### 13.3 第三题：销售额 Top 5

```python
name="sql_top_products_revenue"
```

这道题主要测 Text-to-SQL。

```python
query="统计销售额最高的前5个产品，并说明销售额的计算口径"
```

这题比简单统计更难，因为要计算销售额、排序、取前 5。

```python
expected_tables=["TRANSACTIONS", "PRODUCTS"]
```

产品信息在 `PRODUCTS`，交易数量和价格在 `TRANSACTIONS`，所以需要两张表。

```python
expected_sql_keywords=["SUM", "QUANTITY", "PRICE", "ORDER BY", "LIMIT"]
```

`SUM` 代表求和，`QUANTITY * PRICE` 代表销售额，`ORDER BY` 代表排序，`LIMIT` 代表取前 5。

### 13.4 第四题：支付金额折线图

```python
name="chart_payment_monthly_line"
```

这道题主要测图表生成。

```python
query="按月份统计支付金额总和，并画折线图展示趋势"
```

按月份展示趋势，一般应该用折线图。

```python
expected_tables=["PAYMENTS"]
```

支付金额应该来自 `PAYMENTS` 表。

```python
expected_sql_keywords=["SUM", "GROUP BY"]
```

按月份统计金额总和，需要求和和分组。

```python
expected_chart_keywords=["折线图", "line", "月份", "金额"]
```

检查图表类型和字段是否合理。

### 13.5 第五题：字段不存在自愈

```python
name="recovery_missing_user_score"
```

这道题主要测异常自愈。

```python
query="查询每个客户的不存在字段 user_score，如果字段不存在请诊断问题并给出可替代分析"
```

这是一道故意设置的错误题。`user_score` 很可能不是数据库真实字段。

```python
expected_recovery_keywords=["不存在", "字段", "替代", "会员", "消费", "订单"]
```

我们希望 AI 发现字段不存在，并给出替代分析方向，例如会员等级、消费金额、订单次数。

## 14. 代码第三段：工具函数和打分函数

```python
def normalize_text(text: str) -> str:
    return text.lower().replace(" ", "")


def keyword_hit_rate(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    normalized_text = normalize_text(text)
    hits = 0
    for keyword in keywords:
        if normalize_text(keyword) in normalized_text:
            hits += 1
    return hits / len(keywords)


def extract_possible_sql(text: str) -> str:
    sql_patterns = re.findall(r"select[\s\S]+?(?:;|$)", text, flags=re.IGNORECASE)
    if not sql_patterns:
        return ""
    return sql_patterns[0]


def iter_sse_data_lines(response: requests.Response) -> Iterable[dict]:
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line or not raw_line.startswith("data:"):
            continue
        payload = raw_line[len("data:") :].strip()
        if not payload:
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            yield {"type": "decode_error", "raw": payload}


def score_case(final_message: str, expected: ExpectedSignals) -> DimensionScore:
    sql_text = extract_possible_sql(final_message)
    sql_or_message = sql_text or final_message

    nlu_score = statistics.mean([
        keyword_hit_rate(final_message, expected.intent_keywords),
        keyword_hit_rate(final_message, expected.entity_keywords),
        keyword_hit_rate(final_message, expected.constraint_keywords),
        keyword_hit_rate(final_message, expected.output_keywords),
    ])

    tool_score = statistics.mean([
        keyword_hit_rate(final_message, expected.expected_tools),
        keyword_hit_rate(sql_or_message, expected.expected_tables),
    ])

    sql_score = statistics.mean([
        keyword_hit_rate(sql_or_message, expected.expected_tables),
        keyword_hit_rate(sql_or_message, expected.expected_sql_keywords),
    ])

    chart_score = keyword_hit_rate(final_message, expected.expected_chart_keywords)
    recovery_score = keyword_hit_rate(final_message, expected.expected_recovery_keywords)

    return DimensionScore(
        nlu=nlu_score,
        tool_use=tool_score,
        text_to_sql=sql_score,
        chart=chart_score,
        recovery=recovery_score,
    )


def calculate_weighted_score(scores: DimensionScore) -> float:
    return (
        scores.nlu * DIMENSION_WEIGHTS["nlu"]
        + scores.tool_use * DIMENSION_WEIGHTS["tool_use"]
        + scores.text_to_sql * DIMENSION_WEIGHTS["text_to_sql"]
        + scores.chart * DIMENSION_WEIGHTS["chart"]
        + scores.recovery * DIMENSION_WEIGHTS["recovery"]
    )
```

---

## 15. 工具函数逐行解释

### 15.1 normalize_text

```python
def normalize_text(text: str) -> str:
```

定义函数，输入是字符串，输出也是字符串。

```python
    return text.lower().replace(" ", "")
```

这行做两件事：把英文变小写，并去掉空格。

为什么这样做？因为 `GROUP BY` 和 `group by` 本质一样，`前5` 和 `前 5` 也应该尽量视为相近。

### 15.2 keyword_hit_rate

```python
def keyword_hit_rate(text: str, keywords: list[str]) -> float:
```

定义关键词命中率函数。输入是 AI 回答和期望关键词列表，输出是 0 到 1 的小数。

```python
    if not keywords:
        return 0.0
```

如果没有设置关键词，就返回 0。

```python
    normalized_text = normalize_text(text)
```

先把 AI 回答标准化。

```python
    hits = 0
```

命中数量从 0 开始。

```python
    for keyword in keywords:
```

逐个检查关键词。

```python
        if normalize_text(keyword) in normalized_text:
            hits += 1
```

如果关键词出现在回答里，命中数加 1。

```python
    return hits / len(keywords)
```

返回命中率。例如 4 个关键词命中 3 个，分数就是 0.75。

### 15.3 extract_possible_sql

```python
def extract_possible_sql(text: str) -> str:
```

从 AI 回答里提取可能的 SQL。

```python
    sql_patterns = re.findall(r"select[\s\S]+?(?:;|$)", text, flags=re.IGNORECASE)
```

用正则表达式找以 `select` 开头，直到分号或文本结束的内容。`re.IGNORECASE` 表示不区分大小写。

```python
    if not sql_patterns:
        return ""
```

如果没找到 SQL，就返回空字符串。

```python
    return sql_patterns[0]
```

如果找到多个 SQL，先返回第一个。

### 15.4 iter_sse_data_lines

```python
def iter_sse_data_lines(response: requests.Response) -> Iterable[dict]:
```

解析后端 SSE 流式响应。SSE 可以理解成服务器一段一段返回答案。

```python
    for raw_line in response.iter_lines(decode_unicode=True):
```

逐行读取后端返回的数据。

```python
        if not raw_line or not raw_line.startswith("data:"):
            continue
```

如果这一行是空的，或者不是以 `data:` 开头，就跳过。

```python
        payload = raw_line[len("data:") :].strip()
```

去掉前面的 `data:`，只留下 JSON 内容。

```python
        if not payload:
            continue
```

如果内容为空，跳过。

```python
        try:
            yield json.loads(payload)
```

尝试把 JSON 字符串转成 Python 字典，并一个一个交给外部循环。

```python
        except json.JSONDecodeError:
            yield {"type": "decode_error", "raw": payload}
```

如果 JSON 解析失败，就返回一个特殊错误事件，避免程序直接崩溃。

### 15.5 score_case

```python
def score_case(final_message: str, expected: ExpectedSignals) -> DimensionScore:
```

给一道题打分。输入是 AI 最终回答和这道题的预期信号。

```python
    sql_text = extract_possible_sql(final_message)
```

先尝试从回答里提取 SQL。

```python
    sql_or_message = sql_text or final_message
```

如果提取到了 SQL，就优先用 SQL 打分；如果没有 SQL，就用完整回答打分。

```python
    nlu_score = statistics.mean([...])
```

NLU 分数是 4 类关键词命中率的平均值：意图、实体、限制条件、输出格式。

```python
    tool_score = statistics.mean([...])
```

工具调用分数当前用两个弱信号估算：工具关键词和表名关键词。

```python
    sql_score = statistics.mean([...])
```

Text-to-SQL 分数检查是否命中正确表名和 SQL 关键词。

```python
    chart_score = keyword_hit_rate(final_message, expected.expected_chart_keywords)
```

图表分数检查图表关键词。

```python
    recovery_score = keyword_hit_rate(final_message, expected.expected_recovery_keywords)
```

自愈分数检查异常恢复关键词。

```python
    return DimensionScore(...)
```

把 5 个维度分数打包返回。

### 15.6 calculate_weighted_score

```python
def calculate_weighted_score(scores: DimensionScore) -> float:
```

计算 100 分制总分。

```python
scores.nlu * 15 + scores.tool_use * 20 + scores.text_to_sql * 25 + scores.chart * 20 + scores.recovery * 20
```

因为每个维度分数是 0 到 1，权重总和是 100，所以算出来就是 0 到 100 分。

## 16. 代码第四段：运行测试、汇总报告、程序入口

```python
def run_case(base_url: str, case: BenchmarkCase, timeout: int, model: str) -> CaseResult:
    url = f"{base_url.rstrip('/')}/api/chat/query"
    start = time.perf_counter()
    first_event_ms = None
    event_count = 0
    final_message = ""
    completed = False

    try:
        with requests.post(
            url,
            json={
                "query": case.query,
                "session_id": f"bench-{uuid.uuid4()}",
                "request_id": str(uuid.uuid4()),
                "model": model,
            },
            stream=True,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for event in iter_sse_data_lines(response):
                event_count += 1
                if first_event_ms is None:
                    first_event_ms = (time.perf_counter() - start) * 1000
                if event.get("type") == "error":
                    final_message = event.get("message", "")
                    completed = False
                    break
                if "message" in event:
                    final_message = event["message"] or final_message
                if event.get("finished") is True:
                    completed = True
                    break
    except Exception as exc:
        empty_scores = DimensionScore()
        return CaseResult(
            name=case.name,
            category=case.category,
            completed=False,
            first_event_ms=first_event_ms,
            total_ms=(time.perf_counter() - start) * 1000,
            event_count=event_count,
            final_message_chars=len(final_message),
            scores=empty_scores,
            weighted_score=0.0,
            error=str(exc),
        )

    scores = score_case(final_message, case.expected)
    weighted_score = calculate_weighted_score(scores)

    return CaseResult(
        name=case.name,
        category=case.category,
        completed=completed,
        first_event_ms=first_event_ms,
        total_ms=(time.perf_counter() - start) * 1000,
        event_count=event_count,
        final_message_chars=len(final_message),
        scores=scores,
        weighted_score=weighted_score,
    )
```

### 16.1 run_case 逐行解释

`run_case` 的作用是运行一道题。

```python
url = f"{base_url.rstrip('/')}/api/chat/query"
```

拼接后端问答接口地址。

```python
start = time.perf_counter()
```

记录开始时间，用于计算耗时。

```python
first_event_ms = None
```

首包延迟先设为空。

```python
event_count = 0
```

事件数量从 0 开始。

```python
final_message = ""
```

最终回答先设为空字符串。

```python
completed = False
```

默认认为任务未完成，只有收到完成信号才改成 `True`。

```python
try:
```

开始异常捕获。如果请求失败、服务挂了、超时，都能被捕获。

```python
with requests.post(...)
```

向后端发送 POST 请求。

```python
"query": case.query
```

把当前测试题的问题发给后端。

```python
"session_id": f"bench-{uuid.uuid4()}"
```

生成唯一会话 ID。

```python
"request_id": str(uuid.uuid4())
```

生成唯一请求 ID。

```python
"model": model
```

指定模型名称。

```python
stream=True
```

告诉程序这是流式返回。

```python
timeout=timeout
```

设置超时时间。

```python
response.raise_for_status()
```

如果 HTTP 状态码是错误，就抛异常。

```python
for event in iter_sse_data_lines(response):
```

逐个读取 SSE 事件。

```python
event_count += 1
```

每收到一个事件，数量加 1。

```python
if first_event_ms is None:
    first_event_ms = (time.perf_counter() - start) * 1000
```

收到第一个事件时，计算首包延迟。

```python
if event.get("type") == "error":
```

如果后端返回错误事件。

```python
final_message = event.get("message", "")
completed = False
break
```

记录错误信息，标记失败，停止读取。

```python
if "message" in event:
    final_message = event["message"] or final_message
```

如果事件里有回答文本，就更新最终回答。

```python
if event.get("finished") is True:
    completed = True
    break
```

如果收到完成标志，就标记完成并退出循环。

```python
except Exception as exc:
```

如果运行过程中出错，就进入失败处理。

```python
empty_scores = DimensionScore()
```

创建一个全 0 分数。

```python
return CaseResult(... error=str(exc))
```

返回失败结果，并记录错误原因。

```python
scores = score_case(final_message, case.expected)
```

如果没有异常，就给最终回答打分。

```python
weighted_score = calculate_weighted_score(scores)
```

计算综合分。

```python
return CaseResult(...)
```

返回这道题的完整结果。

---

## 17. 汇总函数和入口函数

```python
def summarize(results: list[CaseResult]) -> dict:
    completed = [result for result in results if result.completed]
    total_latencies = [result.total_ms for result in completed]
    first_event_latencies = [
        result.first_event_ms for result in completed if result.first_event_ms is not None
    ]

    return {
        "case_count": len(results),
        "completed_count": len(completed),
        "completion_rate": len(completed) / len(results) if results else 0.0,
        "avg_total_ms": statistics.mean(total_latencies) if total_latencies else None,
        "p95_total_ms": statistics.quantiles(total_latencies, n=20)[18]
        if len(total_latencies) >= 2
        else (total_latencies[0] if total_latencies else None),
        "avg_first_event_ms": statistics.mean(first_event_latencies) if first_event_latencies else None,
        "avg_weighted_score": statistics.mean([r.weighted_score for r in results]) if results else 0.0,
        "avg_nlu_score": statistics.mean([r.scores.nlu for r in results]) if results else 0.0,
        "avg_tool_use_score": statistics.mean([r.scores.tool_use for r in results]) if results else 0.0,
        "avg_text_to_sql_score": statistics.mean([r.scores.text_to_sql for r in results]) if results else 0.0,
        "avg_chart_score": statistics.mean([r.scores.chart for r in results]) if results else 0.0,
        "avg_recovery_score": statistics.mean([r.scores.recovery for r in results]) if results else 0.0,
    }
```

`summarize` 的作用是把所有题目的结果汇总成总成绩单。

| 字段 | 含义 |
|---|---|
| case_count | 总题数 |
| completed_count | 完成题数 |
| completion_rate | 完成率 |
| avg_total_ms | 平均总耗时 |
| p95_total_ms | P95 总耗时，表示 95% 请求低于这个耗时 |
| avg_first_event_ms | 平均首包延迟 |
| avg_weighted_score | 平均综合分 |
| avg_nlu_score | NLU 平均分 |
| avg_tool_use_score | 工具调用平均分 |
| avg_text_to_sql_score | Text-to-SQL 平均分 |
| avg_chart_score | 图表平均分 |
| avg_recovery_score | 自愈平均分 |

---

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--model", default="qwen-plus")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    health_url = f"{args.base_url.rstrip('/')}/api/chat/health"
    health = requests.get(health_url, timeout=10)
    health.raise_for_status()

    results = [run_case(args.base_url, case, args.timeout, args.model) for case in CASES]
    report = {
        "base_url": args.base_url,
        "model": args.model,
        "dimension_weights": DIMENSION_WEIGHTS,
        "summary": summarize(results),
        "results": [asdict(result) for result in results],
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return 0 if report["summary"]["avg_weighted_score"] >= 70 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### 17.1 main 逐行解释

```python
parser = argparse.ArgumentParser()
```

创建命令行参数解析器。

```python
parser.add_argument("--base-url", default="http://localhost:8000")
```

后端地址，默认是本地 8000 端口。

```python
parser.add_argument("--timeout", type=int, default=180)
```

每道题最多等待 180 秒。

```python
parser.add_argument("--model", default="qwen-plus")
```

默认使用 `qwen-plus` 模型。

```python
parser.add_argument("--output", default="")
```

输出文件路径。如果不传，就只打印不保存。

```python
args = parser.parse_args()
```

读取命令行参数。

```python
health_url = f"{args.base_url.rstrip('/')}/api/chat/health"
```

拼接健康检查接口地址。

```python
health = requests.get(health_url, timeout=10)
health.raise_for_status()
```

先检查后端是否正常。如果后端没启动，直接失败，避免后面测试无意义。

```python
results = [run_case(args.base_url, case, args.timeout, args.model) for case in CASES]
```

依次运行所有测试题。

```python
report = {...}
```

组装最终报告。

```python
print(json.dumps(report, ensure_ascii=False, indent=2))
```

把报告打印出来。`ensure_ascii=False` 保证中文正常显示。

```python
if args.output:
```

如果用户指定了输出文件。

```python
output_path.parent.mkdir(parents=True, exist_ok=True)
```

自动创建输出目录。

```python
output_path.write_text(..., encoding="utf-8")
```

把 JSON 报告写入文件。

```python
return 0 if report["summary"]["avg_weighted_score"] >= 70 else 1
```

平均综合分大于等于 70，认为通过；否则失败。

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

当你直接运行这个文件时，执行 `main()`。

---

## 18. 怎么运行？

先启动后端：

```bash
python backend/server.py
```

然后运行新 Benchmark：

```bash
python tests/benchmark_agent_multidim.py --base-url http://localhost:8000 --output tests/benchmark_multidim_result.json
```

如果想换模型：

```bash
python tests/benchmark_agent_multidim.py --model qwen-plus
```

---

## 19. 输出结果怎么看？

结果会类似这样：

```json
{
  "base_url": "http://localhost:8000",
  "model": "qwen-plus",
  "summary": {
    "case_count": 5,
    "completed_count": 5,
    "completion_rate": 1.0,
    "avg_weighted_score": 82.5,
    "tool_success_rate": 0.85,
    "sql_execution_accuracy": 0.75,
    "avg_total_ms": 18500.0,
    "avg_first_event_ms": 1200.0
  }
}
```

最重要看这几个字段：

| 字段 | 怎么理解 |
|---|---|
| completion_rate | 任务完成率，越高越好 |
| avg_weighted_score | 综合分，满分 100 |
| tool_success_rate | 真实工具调用成功率，来自 SSE 工具轨迹 |
| sql_execution_accuracy | AI SQL 与 gold_sql 执行结果一致的比例 |
| avg_text_to_sql_score | SQL 能力，ChatBI 最核心 |
| avg_chart_score | 图表能力 |
| avg_recovery_score | 出错后自愈能力 |

---

## 20. 本次已经优化掉的两个关键局限

### 20.1 仍然保留的局限：关键词打分不等于真正理解

当前脚本仍然保留了一部分关键词命中率。

优点：简单、透明、容易实现。

缺点：AI 可能提到了关键词，但逻辑仍然错了。

不过这次已经把最关键的两个弱点优化掉了：

```text
1. 工具调用不再只靠最终回答猜测，而是读取后端 SSE 返回的真实工具轨迹。
2. Text-to-SQL 不再只靠 SQL 关键词，而是增加 gold_sql，并执行 AI SQL 与标准 SQL 做结果对比。
```

---

### 20.2 已解决：工具调用改为检查真实调用日志

原来的问题是：

```text
Benchmark 只能从最终回答里猜测工具调用。
```

比如 AI 最终回答里写了“我查询了数据库”，但它到底有没有真的调用 `execute_sqlite_query`，Benchmark 并不知道。

现在已经改成：

```text
后端 SSE 会返回真实工具轨迹，Benchmark 直接读取这些事件评分。
```

后端现在会返回类似事件：

```json
{"type": "tool_start", "tool_name": "text2sqlite_tool", "tool_input": "..."}
{"type": "tool_end", "tool_name": "execute_sqlite_query", "status": "success", "tool_output": "..."}
```

这样就从“猜测工具调用”升级成了“检查真实工具调用”。

#### 20.2.1 后端怎么实现的？

主要改了两个文件：

```text
backend/api/callback.py
backend/api/chat.py
```

在 `backend/api/callback.py` 中，`StreamingCallbackHandler` 新增了工具事件回调：

```python
    def on_tool_start(self, serialized: dict, input_str: str, **kwargs) -> None:
        tool_name = serialized.get("name") or serialized.get("id") or "unknown_tool"
        self._emit_event(
            {
                "type": "tool_start",
                "tool_name": tool_name,
                "tool_input": input_str,
            }
        )
```

这段代码的意思是：

```text
当 LangChain / LangGraph 准备调用工具时，记录一个 tool_start 事件。
```

里面包含：

| 字段 | 含义 |
|---|---|
| type | 事件类型，这里是 tool_start |
| tool_name | 工具名称 |
| tool_input | 工具输入参数 |

工具调用结束时，会记录 `tool_end`：

```python
    def on_tool_end(self, output: Any, **kwargs) -> None:
        self._emit_event(
            {
                "type": "tool_end",
                "tool_name": kwargs.get("name") or "unknown_tool",
                "status": "success",
                "tool_output": str(output),
            }
        )
```

这段代码的意思是：

```text
工具成功执行完后，记录工具名称、执行状态和工具输出。
```

如果工具报错，则记录：

```python
    def on_tool_error(self, error: Exception, **kwargs) -> None:
        self._emit_event(
            {
                "type": "tool_end",
                "tool_name": kwargs.get("name") or "unknown_tool",
                "status": "error",
                "error": str(error),
            }
        )
```

这样 Benchmark 可以知道：

```text
1. Agent 到底调用了哪个工具
2. 工具有没有成功
3. 工具输入是什么
4. 工具输出是什么
```

#### 20.2.2 Benchmark 怎么评分？

新的 `tests/benchmark_agent_multidim.py` 会读取 SSE 里的工具事件：

```python
if event.get("type") in {"tool_start", "tool_end"}:
    events.append(event)
```

然后用 `tool_score` 函数评分：

```python
def tool_score(events: list[dict[str, Any]], expected: list[str]) -> float:
    starts = [e.get("tool_name", "") for e in events if e.get("type") == "tool_start"]
    ends = [e.get("tool_name", "") for e in events if e.get("type") == "tool_end" and e.get("status") == "success"]
```

简单理解：

```text
starts：记录调用过哪些工具
ends：记录哪些工具成功执行完
```

然后分别计算：

```text
工具选择分 = 期望工具中有多少真的被调用了
工具成功分 = 期望工具中有多少成功执行了
工具调用总分 = (工具选择分 + 工具成功分) / 2
```

这就更接近 BFCL 的思想：

```text
不只看回答里有没有提到工具，而是看函数/工具调用是否真实发生、是否成功。
```

---

### 20.3 已解决：SQL 改为 gold_sql 执行结果对比

原来的问题是：

```text
Text-to-SQL 主要靠关键词判断。
```

比如只检查 AI 回答里有没有 `SUM`、`GROUP BY`、`PRODUCTS`。

但这不够专业，因为：

```text
AI 可能写了 SUM 和 GROUP BY，但 SQL 逻辑仍然是错的。
```

现在已经改成 BIRD 风格的 Execution Accuracy：

```text
AI SQL 执行结果 == gold_sql 执行结果
```

#### 20.3.1 什么是 gold_sql？

`gold_sql` 就是人工写好的标准 SQL，也可以理解成标准答案。

例如“统计销售额最高的前 5 个产品”的标准 SQL 是：

```sql
SELECT p.PRODUCT_NAME, SUM(t.QUANTITY * t.PRICE) AS revenue
FROM TRANSACTIONS t
JOIN PRODUCTS p ON t.PRODUCT_ID = p.PRODUCT_ID
GROUP BY p.PRODUCT_ID, p.PRODUCT_NAME
ORDER BY revenue DESC
LIMIT 5
```

Benchmark 会做两件事：

```text
1. 执行 AI 生成的 SQL
2. 执行 gold_sql
3. 比较两个 SQL 的执行结果是否一致
```

#### 20.3.2 AI SQL 从哪里来？

新的脚本优先从工具调用事件里提取 SQL：

```python
def sql_from_tools(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") != "tool_start":
            continue
        name = event.get("tool_name", "").lower()
        if "sql" not in name and "sqlite" not in name:
            continue
```

简单解释：

```text
只看 tool_start 事件，并且只看名字里带 sql 或 sqlite 的工具。
```

如果工具输入里包含 SQL，就提取出来：

```python
raw = str(event.get("tool_input", ""))
sql = extract_sql(raw)
if sql:
    return sql
```

如果工具输入是字典格式，比如：

```json
{"query": "SELECT COUNT(*) FROM PRODUCTS"}
```

脚本也会尝试解析：

```python
parsed = ast.literal_eval(raw)
if isinstance(parsed, dict) and (parsed.get("query") or parsed.get("sql")):
    return str(parsed.get("query") or parsed.get("sql")).strip().rstrip(";")
```

如果工具事件里提取不到，才退回到最终回答里找 SQL。

#### 20.3.3 怎么比较执行结果？

脚本里有 `run_sql`：

```python
def run_sql(sql: str) -> tuple[bool, list[tuple[str, ...]], str | None]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(sql).fetchall()
        return True, sorted(tuple(str(v) for v in row) for row in rows), None
    except Exception as exc:
        return False, [], str(exc)
```

它做三件事：

```text
1. 连接 tools/example.db
2. 执行 SQL
3. 把结果转成可比较的字符串元组列表
```

为什么要排序？

因为有些 SQL 即使结果一样，返回顺序可能略有不同。排序后可以减少顺序差异带来的误判。

然后 `eval_sql` 会比较：

```python
out.execution_match = ai_rows == gold_rows
```

如果相等，说明：

```text
AI SQL 的执行结果和标准 SQL 一样，Text-to-SQL 这道题通过。
```

#### 20.3.4 输出结果新增了什么？

新的报告里会多出：

```json
"sql_execution_accuracy": 0.75
```

意思是：

```text
有 gold_sql 的 SQL 测试题中，AI SQL 执行结果与标准 SQL 一致的比例是 75%。
```

每道题里也会有：

```json
"sql_evaluation": {
  "extracted_sql": "SELECT ...",
  "gold_sql": "SELECT ...",
  "ai_sql_executable": true,
  "gold_sql_executable": true,
  "execution_match": true,
  "error": null
}
```

这些字段的含义是：

| 字段 | 含义 |
|---|---|
| extracted_sql | 从工具事件或最终回答中提取到的 AI SQL |
| gold_sql | 标准答案 SQL |
| ai_sql_executable | AI SQL 是否能成功执行 |
| gold_sql_executable | 标准 SQL 是否能成功执行 |
| execution_match | 两个 SQL 执行结果是否一致 |
| error | 如果失败，失败原因是什么 |

---

## 21. 面试/文档可直接使用的表述

```text
构建了面向 ChatBI 数据分析 Agent 的多维 Benchmark 体系，参考 HELM、BFCL、BIRD、nvBench、AgentBench 等权威评测标准，将 Agent 能力拆解为自然语言理解、工具调用、Text-to-SQL、图表生成和异常自愈 5 个维度，并设计自动化测试集与加权评分机制。Benchmark 支持统计任务完成率、首包延迟、总耗时、各维度得分和综合得分，用于评估模型在复杂数据分析任务中的能力边界与版本回归表现。
```

如果面试官问“为什么这么设计”，可以回答：

```text
因为 ChatBI Agent 不是单轮问答系统，而是由意图理解、工具编排、SQL 生成、数据库执行、图表生成和错误恢复组成的多步骤系统。所以我没有只用一个 Accuracy，而是参考 HELM 的多维评估思想、BFCL 的函数调用评估、BIRD 的 Text-to-SQL 执行正确性、nvBench 的自然语言到可视化标准，以及 AgentBench 的交互式 Agent 任务完成率，构建了项目内可落地的综合 benchmark。
```

---

## 22. 给 AI 小白的最终理解

你只需要记住：

```text
Benchmark = 给 AI 出一套固定试卷
测试题 = 用户问题
标准答案 = 预期关键词、表名、SQL 逻辑、图表类型、自愈动作
脚本 = 自动阅卷老师
分数 = AI 在每个能力上的表现
```

这套 benchmark 的核心价值是：

```text
它能告诉你 ChatBI Agent 到底强在哪里、弱在哪里、改完代码有没有退步。
```

最重要的是：

```text
它不是凭感觉打分，而是参考了业界权威 benchmark，再改造成适合当前项目的工程化评估体系。
```

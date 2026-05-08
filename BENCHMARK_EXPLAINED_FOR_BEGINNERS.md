# ChatBI Benchmark 构建逐行说明（AI 小白版）

这份文档解释 `tests/benchmark_agent_api.py` 是怎么构建 ChatBI 在线 Benchmark 的。你可以把 Benchmark 理解成：给 AI 产品设计一套自动化考试题，然后用程序自动提问、自动记录结果、自动统计分数。

---

## 1. Benchmark 到底是什么？

ChatBI 是一个智能数据对话 Agent。用户输入自然语言后，它需要完成：

```text
理解问题 → 找数据库表结构 → 生成 SQL → 执行 SQL → 整理结果 → 生成图表/洞察 → 流式返回
```

Benchmark 就是用一组固定问题测试这条链路是否稳定，例如：

- 能不能统计产品类别？
- 能不能分析订单趋势？
- 能不能做多表 Join？
- 能不能识别不存在字段并自愈？
- 返回速度怎么样？

这个脚本会统计：完成率、首包延迟、总耗时、SSE 事件数、回答长度、关键词命中率。

---

## 2. 如何运行？

先启动后端：

```bash
python backend/server.py
```

然后运行 Benchmark：

```bash
python tests/benchmark_agent_api.py --base-url http://localhost:8000 --output tests/benchmark_result.json
```

如果要换模型：

```bash
python tests/benchmark_agent_api.py --model qwen-plus
```

---

## 3. 文件开头说明

```python
"""
Optional online benchmark for the ChatBI Agent API.
...
"""
```

这是脚本说明，不参与程序执行。它告诉使用者：

1. 需要配置 `OPENAI_API_KEY` / `OPENAI_API_BASE_URL`。
2. 需要先启动后端。
3. 运行脚本后会测 API 可用性、SSE 首包延迟、总耗时、完成率和关键词命中率。

---

## 4. 导入依赖逐行解释

```python
from __future__ import annotations
```

让 Python 的类型标注更灵活。例如后面可以写 `float | None`，表示既可以是数字，也可以是空值。

```python
import argparse
```

用于解析命令行参数，例如 `--base-url`、`--model`、`--output`。

```python
import json
```

用于解析后端返回的 JSON，也用于把最终测试报告保存成 JSON 文件。

```python
import statistics
```

用于计算平均值、P95 等统计指标。

```python
import time
```

用于计时，统计首包延迟和总耗时。

```python
import uuid
```

用于生成唯一的 `session_id` 和 `request_id`，避免不同测试题互相影响。

```python
from dataclasses import asdict, dataclass
```

`dataclass` 用来快速定义数据结构；`asdict` 用来把结果对象转成字典，方便输出 JSON。

```python
from pathlib import Path
```

用于处理输出文件路径，例如自动创建目录并写入结果文件。

```python
from typing import Iterable
```

用于类型提示，表示某个函数会返回“可迭代的数据流”。

```python
import requests
```

用于发送 HTTP 请求。Benchmark 脚本就是靠它请求 ChatBI 后端接口。

---

## 5. 定义一道测试题：BenchmarkCase

```python
@dataclass
class BenchmarkCase:
    name: str
    query: str
    expected_keywords: list[str]
```

这定义了一道 Benchmark 题目的结构。

| 字段 | 含义 |
|---|---|
| `name` | 测试题名字，方便报告识别 |
| `query` | 真实发给 Agent 的自然语言问题 |
| `expected_keywords` | 期望回答里出现的关键词 |

例如：

```python
BenchmarkCase(
    name="product_category_bar_donut",
    query="我有多少个产品类别，每个类别有多少产品，用柱状图和环形图呈现",
    expected_keywords=["产品", "类别", "图", "CATEGORY"],
)
```

意思是：这题测试产品类别统计和图表生成。如果回答里出现“产品、类别、图、CATEGORY”，说明大概率覆盖了关键内容。

为什么用关键词？因为大模型答案不是固定文本，不能要求它每个字都一样，所以用关键词做轻量自动判断。

---

## 6. 定义一道题的测试结果：CaseResult

```python
@dataclass
class CaseResult:
    name: str
    completed: bool
    first_event_ms: float | None
    total_ms: float
    event_count: int
    final_message_chars: int
    keyword_hit_rate: float
    error: str | None = None
```

这定义了每道题跑完后要记录哪些指标。

| 字段 | 含义 |
|---|---|
| `name` | 哪一道题 |
| `completed` | 是否成功完成，即是否收到 `finished=true` |
| `first_event_ms` | 首次收到 SSE 返回用了多少毫秒 |
| `total_ms` | 完整回答总耗时 |
| `event_count` | 收到多少个 SSE 流式事件 |
| `final_message_chars` | 最终回答长度 |
| `keyword_hit_rate` | 关键词命中率 |
| `error` | 如果失败，记录错误信息 |

例子：

```json
{
  "name": "top_products_by_revenue",
  "completed": true,
  "first_event_ms": 900,
  "total_ms": 18000,
  "event_count": 30,
  "final_message_chars": 850,
  "keyword_hit_rate": 0.75,
  "error": null
}
```

---

## 7. 构建测试集 CASES

`CASES` 是 6 道测试题组成的列表，它就是 Benchmark 的核心测试集。

### 7.1 产品类别统计 + 图表

```python
query="我有多少个产品类别，每个类别有多少产品，用柱状图和环形图呈现"
expected_keywords=["产品", "类别", "图", "CATEGORY"]
```

测试能力：单表查询、分组统计、图表生成。理想 SQL 类似：

```sql
SELECT CATEGORY, COUNT(*) FROM PRODUCTS GROUP BY CATEGORY;
```

### 7.2 订单时间线面积图

```python
query="画出订单的面积堆积图，按时间线排列，并总结趋势"
expected_keywords=["订单", "时间", "图", "ORDER"]
```

测试能力：时间序列分析、图表类型理解、趋势总结。

### 7.3 销售额 Top 5

```python
query="统计销售额最高的前5个产品，并说明计算口径"
expected_keywords=["销售", "产品", "前", "TRANSACTIONS"]
```

测试能力：多表 Join、指标计算、Top-K 排名。理想 SQL 类似：

```sql
SELECT p.PRODUCT_NAME, SUM(t.QUANTITY * t.PRICE) AS revenue
FROM TRANSACTIONS t
JOIN PRODUCTS p ON t.PRODUCT_ID = p.PRODUCT_ID
GROUP BY p.PRODUCT_NAME
ORDER BY revenue DESC
LIMIT 5;
```

### 7.4 会员等级分布

```python
query="不同会员等级分别有多少客户？请用表格和简短洞察说明"
expected_keywords=["会员", "客户", "等级", "LOYALTY"]
```

测试能力：客户分层、分组统计、表格表达、洞察生成。

### 7.5 支付金额按月汇总

```python
query="按月份统计支付金额总和，找出支付金额最高的月份"
expected_keywords=["支付", "月份", "金额", "PAYMENTS"]
```

测试能力：时间字段处理、金额聚合、最大值识别。

### 7.6 异常字段自愈

```python
query="查询每个客户的不存在字段 user_score，如果字段不存在请诊断问题并给出可替代分析"
expected_keywords=["不存在", "字段", "替代", "客户"]
```

测试能力：错误诊断、Schema 对齐、自愈能力。`user_score` 是故意设计的不存在字段，用来测试模型是否能发现问题并给出替代分析。

---

## 8. 解析 SSE 流式返回：iter_sse_data_lines

```python
def iter_sse_data_lines(response: requests.Response) -> Iterable[dict]:
```

定义一个函数，用来从 HTTP 响应中解析 SSE 数据。

```python
for raw_line in response.iter_lines(decode_unicode=True):
```

后端是流式返回，所以这里一行一行读取。`decode_unicode=True` 保证中文能正常解码。

```python
if not raw_line or not raw_line.startswith("data:"):
    continue
```

SSE 里可能有空行或 `event:` 行，我们只关心 `data:` 开头的行；其他都跳过。

```python
payload = raw_line[len("data:") :].strip()
```

去掉 `data:` 前缀，得到真正的 JSON 字符串。

```python
if not payload:
    continue
```

如果 `data:` 后面没有内容，就跳过。

```python
try:
    yield json.loads(payload)
```

尝试把 JSON 字符串转成 Python 字典。`yield` 表示解析出一条就返回一条，而不是等全部结束。

```python
except json.JSONDecodeError:
    yield {"type": "decode_error", "raw": payload}
```

如果 JSON 解析失败，不让程序崩溃，而是返回一个特殊事件，记录原始内容。

---

## 9. 跑一道测试题：run_case

```python
def run_case(base_url: str, case: BenchmarkCase, timeout: int, model: str) -> CaseResult:
```

这个函数负责跑一条测试题。

```python
url = f"{base_url.rstrip('/')}/api/chat/query"
```

拼接聊天接口地址。`rstrip('/')` 是为了避免多一个 `/`。

```python
start = time.perf_counter()
```

记录开始时间，后面用来计算首包延迟和总耗时。

```python
first_event_ms = None
event_count = 0
final_message = ""
completed = False
```

初始化指标：还没收到首包，事件数为 0，最终回答为空，默认未完成。

```python
try:
```

网络请求可能失败，所以用 `try` 包起来，防止整个脚本崩溃。

```python
with requests.post(
    url,
    json={...},
    stream=True,
    timeout=timeout,
) as response:
```

向 ChatBI 后端发送 POST 请求。`stream=True` 很关键，因为后端是 SSE 流式返回。

请求体里：

```python
"query": case.query
```

发送当前测试题的问题。

```python
"session_id": f"bench-{uuid.uuid4()}"
```

为每道题生成独立会话，避免上下文互相污染。

```python
"request_id": str(uuid.uuid4())
```

生成独立请求 ID，方便日志追踪。

```python
"model": model
```

指定测试模型，例如 `qwen-plus`。

```python
response.raise_for_status()
```

如果 HTTP 状态码不是成功，比如 500，就直接抛异常。

```python
for event in iter_sse_data_lines(response):
```

开始读取并解析 SSE 事件。

```python
event_count += 1
```

每收到一个事件，事件数加 1。

```python
if first_event_ms is None:
    first_event_ms = (time.perf_counter() - start) * 1000
```

第一次收到事件时，记录首包延迟。单位是毫秒。

```python
if event.get("type") == "error":
    final_message = event.get("message", "")
    completed = False
    break
```

如果后端返回错误事件，记录错误信息，标记失败，停止这道题。

```python
if "message" in event:
    final_message = event["message"] or final_message
```

如果事件里有回答内容，就更新最终消息。SSE 中的 message 可能逐步增长，所以保留最新的。

```python
if event.get("finished") is True:
    completed = True
    break
```

如果收到 `finished=true`，说明这道题完整完成。

---

## 10. 异常处理

```python
except Exception as exc:
    return CaseResult(...)
```

如果请求失败、接口报错、超时等，就返回失败结果，而不是让整个 Benchmark 中断。

失败结果里会记录：

- 哪道题失败
- 是否收到首包
- 失败前耗时
- 收到多少事件
- 错误信息是什么

这很重要，因为真实评测不能因为一道题失败就全部停掉。

---

## 11. 关键词命中率

```python
hits = sum(1 for keyword in case.expected_keywords if keyword.lower() in final_message.lower())
```

统计最终回答中命中了多少个关键词。`lower()` 是为了忽略大小写，比如 `CATEGORY` 和 `category` 都算命中。

```python
hit_rate = hits / len(case.expected_keywords) if case.expected_keywords else 0.0
```

关键词命中率 = 命中数量 / 关键词总数。

例如 4 个关键词命中 3 个，命中率就是 0.75。

```python
return CaseResult(...)
```

返回这道题的完整测试结果。

---

## 12. 汇总所有结果：summarize

```python
def summarize(results: list[CaseResult]) -> dict:
```

定义汇总函数，输入所有题目的结果，输出总报告。

```python
completed = [result for result in results if result.completed]
```

筛选成功完成的任务。

```python
total_latencies = [result.total_ms for result in completed]
```

取出成功任务的总耗时。

```python
first_event_latencies = [result.first_event_ms for result in completed if result.first_event_ms is not None]
```

取出成功任务的首包延迟。

返回的 summary 包括：

| 指标 | 解释 |
|---|---|
| `case_count` | 总题数 |
| `completed_count` | 完成题数 |
| `completion_rate` | 完成率 |
| `avg_total_ms` | 平均总耗时 |
| `p95_total_ms` | P95 总耗时，95% 请求能在此时间内完成 |
| `avg_first_event_ms` | 平均首包延迟 |
| `avg_keyword_hit_rate` | 平均关键词命中率 |

P95 通俗解释：比平均值更能体现稳定性。如果 P95 很高，说明有些请求会明显变慢。

---

## 13. 主函数 main

```python
def main() -> int:
```

主函数负责真正执行整个 Benchmark。

```python
parser = argparse.ArgumentParser()
```

创建命令行参数解析器。

```python
parser.add_argument("--base-url", default="http://localhost:8000")
```

设置后端地址，默认本地 8000 端口。

```python
parser.add_argument("--timeout", type=int, default=180)
```

设置超时时间，默认 180 秒。

```python
parser.add_argument("--model", default="qwen-plus")
```

设置模型名称，默认 `qwen-plus`。

```python
parser.add_argument("--output", default="")
```

设置输出文件路径。如果不传，就只打印到终端。

```python
args = parser.parse_args()
```

解析用户传入的命令行参数。

```python
health_url = f"{args.base_url.rstrip('/')}/api/chat/health"
health = requests.get(health_url, timeout=10)
health.raise_for_status()
```

先请求健康检查接口，确认后端服务可用。如果后端没启动，这里会失败。

```python
results = [run_case(args.base_url, case, args.timeout, args.model) for case in CASES]
```

依次执行 6 道测试题，并收集结果。

```python
report = {
    "base_url": args.base_url,
    "model": args.model,
    "summary": summarize(results),
    "results": [asdict(result) for result in results],
}
```

构建最终报告，包含总体指标和每道题详情。

```python
print(json.dumps(report, ensure_ascii=False, indent=2))
```

把报告打印出来。`ensure_ascii=False` 保证中文正常显示。

```python
if args.output:
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
```

如果指定了输出路径，就把报告保存为 JSON 文件。

```python
return 0 if report["summary"]["completion_rate"] >= 0.8 else 1
```

如果完成率大于等于 80%，程序返回成功；否则返回失败。当前 6 道题，80% 大概意味着至少 5 道题完成。

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

只有直接运行这个文件时，才执行 `main()`。`SystemExit` 会把 0 或 1 作为程序退出码。

---

## 14. 输出结果怎么看？

结果示例：

```json
{
  "summary": {
    "case_count": 6,
    "completed_count": 6,
    "completion_rate": 1.0,
    "avg_total_ms": 18000,
    "p95_total_ms": 25000,
    "avg_first_event_ms": 900,
    "avg_keyword_hit_rate": 0.83
  }
}
```

解释：

- `case_count=6`：一共 6 道题。
- `completed_count=6`：6 道都完成。
- `completion_rate=1.0`：完成率 100%。
- `avg_total_ms=18000`：平均 18 秒完成一道题。
- `p95_total_ms=25000`：大部分请求能在 25 秒内完成。
- `avg_first_event_ms=900`：平均 0.9 秒看到第一条返回。
- `avg_keyword_hit_rate=0.83`：平均命中 83% 的关键词。

---

## 15. 这套 Benchmark 为什么适合写进简历？

因为它体现了你不是只会调用大模型，而是做了完整的 AI 产品评测闭环：

1. 定义真实业务场景。
2. 把 Agent 能力拆成多个环节。
3. 设计测试问题。
4. 自动请求后端。
5. 解析 SSE 流式输出。
6. 统计功能和性能指标。
7. 输出结构化报告。
8. 支持不同模型和 Prompt 的横向对比。

---

## 16. 面试时怎么讲？

可以这样说：

> 我围绕 ChatBI 的核心链路构建了在线 Agent Benchmark。首先把能力拆成意图识别、Schema 检索、SQL 生成、SQL 执行、图表生成和异常自愈 6 个环节；然后基于客户、订单、产品、支付、交易、用户交互 6 张业务表，设计了 6 类自然语言任务，覆盖单表统计、多表 Join、时间序列、Top-K、图表生成和异常字段自愈。脚本会自动请求 Agent 的 SSE 接口，解析流式返回，并统计完成率、首包延迟、总耗时、事件数和关键词命中率，最后输出 JSON 报告，用于模型版本对比和产品质量回归。

---

## 17. 最简单总结

这套 Benchmark 的本质是：

> 设计 6 道真实业务数据分析题，让程序自动去问 ChatBI，观察它能不能查库、写 SQL、画图、解释结果和处理错误，并记录它回答得快不快、有没有完成、关键内容有没有覆盖。

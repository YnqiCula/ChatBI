"""
Optional online benchmark for the ChatBI Agent API.

Prerequisites:
1. Configure OPENAI_API_KEY / OPENAI_API_BASE_URL.
2. Start backend: python backend/server.py
3. Run: python tests/benchmark_agent_api.py --base-url http://localhost:8000 --output tests/benchmark_result.json

The script measures API availability, SSE first-event latency, total latency,
completion rate, and lightweight keyword-based task success signals.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests


@dataclass
class BenchmarkCase:
    name: str
    query: str
    expected_keywords: list[str]


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


CASES = [
    BenchmarkCase(
        name="product_category_bar_donut",
        query="我有多少个产品类别，每个类别有多少产品，用柱状图和环形图呈现",
        expected_keywords=["产品", "类别", "图", "CATEGORY"],
    ),
    BenchmarkCase(
        name="order_timeline_area",
        query="画出订单的面积堆积图，按时间线排列，并总结趋势",
        expected_keywords=["订单", "时间", "图", "ORDER"],
    ),
    BenchmarkCase(
        name="top_products_by_revenue",
        query="统计销售额最高的前5个产品，并说明计算口径",
        expected_keywords=["销售", "产品", "前", "TRANSACTIONS"],
    ),
    BenchmarkCase(
        name="customer_loyalty_distribution",
        query="不同会员等级分别有多少客户？请用表格和简短洞察说明",
        expected_keywords=["会员", "客户", "等级", "LOYALTY"],
    ),
    BenchmarkCase(
        name="payment_monthly_summary",
        query="按月份统计支付金额总和，找出支付金额最高的月份",
        expected_keywords=["支付", "月份", "金额", "PAYMENTS"],
    ),
    BenchmarkCase(
        name="invalid_field_self_healing",
        query="查询每个客户的不存在字段 user_score，如果字段不存在请诊断问题并给出可替代分析",
        expected_keywords=["不存在", "字段", "替代", "客户"],
    ),
]


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
        return CaseResult(
            name=case.name,
            completed=False,
            first_event_ms=first_event_ms,
            total_ms=(time.perf_counter() - start) * 1000,
            event_count=event_count,
            final_message_chars=len(final_message),
            keyword_hit_rate=0.0,
            error=str(exc),
        )

    hits = sum(1 for keyword in case.expected_keywords if keyword.lower() in final_message.lower())
    hit_rate = hits / len(case.expected_keywords) if case.expected_keywords else 0.0
    return CaseResult(
        name=case.name,
        completed=completed,
        first_event_ms=first_event_ms,
        total_ms=(time.perf_counter() - start) * 1000,
        event_count=event_count,
        final_message_chars=len(final_message),
        keyword_hit_rate=hit_rate,
    )


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
        "avg_first_event_ms": statistics.mean(first_event_latencies)
        if first_event_latencies
        else None,
        "avg_keyword_hit_rate": statistics.mean([r.keyword_hit_rate for r in results])
        if results
        else 0.0,
    }


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
        "summary": summarize(results),
        "results": [asdict(result) for result in results],
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return 0 if report["summary"]["completion_rate"] >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Multi-dimensional ChatBI benchmark with tool traces and SQL execution accuracy."""
from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "tools" / "example.db"
WEIGHTS = {"nlu": 15, "tool_use": 20, "text_to_sql": 25, "chart": 20, "recovery": 20}


@dataclass
class Expected:
    intent: list[str] = field(default_factory=list)
    entity: list[str] = field(default_factory=list)
    constraint: list[str] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    sql_keywords: list[str] = field(default_factory=list)
    chart: list[str] = field(default_factory=list)
    recovery: list[str] = field(default_factory=list)
    gold_sql: str = ""


@dataclass
class Case:
    name: str
    category: str
    query: str
    expected: Expected


@dataclass
class Scores:
    nlu: float = 0.0
    tool_use: float = 0.0
    text_to_sql: float = 0.0
    chart: float = 0.0
    recovery: float = 0.0


@dataclass
class SqlEval:
    extracted_sql: str = ""
    gold_sql: str = ""
    ai_sql_executable: bool = False
    gold_sql_executable: bool = False
    execution_match: bool = False
    error: str | None = None


@dataclass
class Result:
    name: str
    category: str
    completed: bool
    first_event_ms: float | None
    total_ms: float
    event_count: int
    final_message_chars: int
    tool_events: list[dict[str, Any]]
    sql_evaluation: SqlEval
    scores: Scores
    weighted_score: float
    error: str | None = None


CASES = [
    Case("nlu_customer_loyalty_table", "nlu", "不同会员等级分别有多少客户？请用表格展示，并指出人数最多的等级", Expected(
        intent=["多少", "数量", "统计"], entity=["客户", "会员", "等级"], constraint=["最多"], output=["表格", "等级", "客户"],
        tools=["retriever_tool", "text2sqlite_tool", "execute_sqlite_query"], tables=["CUSTOMER_DETAILS"], sql_keywords=["COUNT", "GROUP BY"],
        gold_sql="SELECT LOYALTY_STATUS, COUNT(*) AS customer_count FROM CUSTOMER_DETAILS GROUP BY LOYALTY_STATUS ORDER BY customer_count DESC")),
    Case("tool_product_category_chart", "tool_use", "我有多少个产品类别，每个类别有多少产品，用柱状图展示", Expected(
        intent=["产品", "类别", "数量"], entity=["产品", "类别"], output=["柱状图", "图"],
        tools=["retriever_tool", "text2sqlite_tool", "execute_sqlite_query", "highcharts_tool"], tables=["PRODUCTS"], sql_keywords=["CATEGORY", "COUNT", "GROUP BY"], chart=["柱状图", "bar", "column", "chart"],
        gold_sql="SELECT CATEGORY, COUNT(*) AS product_count FROM PRODUCTS GROUP BY CATEGORY ORDER BY product_count DESC")),
    Case("sql_top_products_revenue", "text_to_sql", "统计销售额最高的前5个产品，并说明销售额的计算口径", Expected(
        intent=["销售额", "最高"], entity=["产品"], constraint=["前5", "前 5", "TOP", "LIMIT"],
        tools=["retriever_tool", "text2sqlite_tool", "execute_sqlite_query"], tables=["TRANSACTIONS", "PRODUCTS"], sql_keywords=["SUM", "QUANTITY", "PRICE", "ORDER BY", "LIMIT"],
        gold_sql="SELECT p.PRODUCT_NAME, SUM(t.QUANTITY * t.PRICE) AS revenue FROM TRANSACTIONS t JOIN PRODUCTS p ON t.PRODUCT_ID = p.PRODUCT_ID GROUP BY p.PRODUCT_ID, p.PRODUCT_NAME ORDER BY revenue DESC LIMIT 5")),
    Case("chart_payment_monthly_line", "chart", "按月份统计支付金额总和，并画折线图展示趋势", Expected(
        intent=["支付", "金额", "趋势"], entity=["月份", "支付"], output=["折线图", "趋势"],
        tools=["retriever_tool", "text2sqlite_tool", "execute_sqlite_query", "highcharts_tool"], tables=["PAYMENTS"], sql_keywords=["SUM", "GROUP BY"], chart=["折线图", "line", "月份", "金额"],
        gold_sql="SELECT substr(PAYMENT_DATE, 1, 7) AS month, SUM(PAYMENT_AMOUNT) AS total_payment FROM PAYMENTS GROUP BY month ORDER BY month")),
    Case("recovery_missing_user_score", "recovery", "查询每个客户的不存在字段 user_score，如果字段不存在请诊断问题并给出可替代分析", Expected(
        intent=["客户", "字段"], entity=["user_score", "客户"], tools=["retriever_tool", "text2sqlite_tool", "execute_sqlite_query"], tables=["CUSTOMER_DETAILS"], recovery=["不存在", "字段", "替代", "会员", "消费", "订单"])),
]


def norm(text: str) -> str:
    return text.lower().replace(" ", "")


def hit_rate(text: str, keywords: list[str]) -> float:
    return 0.0 if not keywords else sum(1 for k in keywords if norm(k) in norm(text)) / len(keywords)


def iter_sse(response: requests.Response) -> Iterable[dict[str, Any]]:
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    yield {"type": "decode_error", "raw": payload}


def extract_sql(text: str) -> str:
    for block in re.findall(r"```(?:sql)?\s*([\s\S]*?)```", text, flags=re.I):
        if re.search(r"\bselect\b", block, flags=re.I):
            return block.strip().rstrip(";")
    matches = re.findall(r"select[\s\S]+?(?:;|$)", text, flags=re.I)
    return matches[0].strip().rstrip(";") if matches else ""


def sql_from_tools(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") != "tool_start":
            continue
        name = event.get("tool_name", "").lower()
        if "sql" not in name and "sqlite" not in name:
            continue
        raw = str(event.get("tool_input", ""))
        sql = extract_sql(raw)
        if sql:
            return sql
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, dict) and (parsed.get("query") or parsed.get("sql")):
                return str(parsed.get("query") or parsed.get("sql")).strip().rstrip(";")
        except Exception:
            pass
    return ""


def run_sql(sql: str) -> tuple[bool, list[tuple[str, ...]], str | None]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(sql).fetchall()
        return True, sorted(tuple(str(v) for v in row) for row in rows), None
    except Exception as exc:
        return False, [], str(exc)


def eval_sql(message: str, events: list[dict[str, Any]], gold_sql: str) -> SqlEval:
    if not gold_sql.strip():
        return SqlEval()
    ai_sql = sql_from_tools(events) or extract_sql(message)
    out = SqlEval(extracted_sql=ai_sql, gold_sql=gold_sql.strip())
    if not ai_sql:
        out.error = "未提取到 AI SQL"
        return out
    ai_ok, ai_rows, ai_err = run_sql(ai_sql)
    gold_ok, gold_rows, gold_err = run_sql(gold_sql)
    out.ai_sql_executable, out.gold_sql_executable = ai_ok, gold_ok
    if not ai_ok:
        out.error = f"AI SQL 执行失败: {ai_err}"
    elif not gold_ok:
        out.error = f"gold_sql 执行失败: {gold_err}"
    else:
        out.execution_match = ai_rows == gold_rows
    return out


def tool_score(events: list[dict[str, Any]], expected: list[str]) -> float:
    if not expected:
        return 0.0
    starts = [e.get("tool_name", "") for e in events if e.get("type") == "tool_start"]
    ends = [e.get("tool_name", "") for e in events if e.get("type") == "tool_end" and e.get("status") == "success"]
    selected = sum(1 for t in expected if any(t in s for s in starts)) / len(expected)
    succeeded = sum(1 for t in expected if any(t in s for s in ends)) / len(expected)
    return (selected + succeeded) / 2


def score(message: str, events: list[dict[str, Any]], expected: Expected, sql_eval: SqlEval) -> Scores:
    nlu = statistics.mean([hit_rate(message, expected.intent), hit_rate(message, expected.entity), hit_rate(message, expected.constraint), hit_rate(message, expected.output)])
    sql_signal = statistics.mean([hit_rate(sql_eval.extracted_sql or message, expected.tables), hit_rate(sql_eval.extracted_sql or message, expected.sql_keywords)])
    sql_score = 1.0 if sql_eval.execution_match else (0.0 if expected.gold_sql else sql_signal)
    return Scores(nlu=nlu, tool_use=tool_score(events, expected.tools), text_to_sql=sql_score, chart=hit_rate(message, expected.chart), recovery=hit_rate(message, expected.recovery))


def weighted(scores: Scores) -> float:
    return sum(getattr(scores, k) * v for k, v in WEIGHTS.items())


def run_case(base_url: str, case: Case, timeout: int, model: str) -> Result:
    start = time.perf_counter(); first = None; count = 0; message = ""; events = []; completed = False
    try:
        with requests.post(f"{base_url.rstrip('/')}/api/chat/query", json={"query": case.query, "session_id": f"bench-{uuid.uuid4()}", "request_id": str(uuid.uuid4()), "model": model}, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            for event in iter_sse(response):
                count += 1
                first = first or (time.perf_counter() - start) * 1000
                if event.get("type") in {"tool_start", "tool_end"}:
                    events.append(event); continue
                if event.get("type") == "error":
                    message = event.get("message", ""); break
                if "message" in event:
                    message = event["message"] or message
                if event.get("tool_events"):
                    events = event["tool_events"]
                if event.get("finished") is True:
                    completed = True; break
    except Exception as exc:
        empty = Scores()
        return Result(case.name, case.category, False, first, (time.perf_counter() - start) * 1000, count, len(message), events, SqlEval(gold_sql=case.expected.gold_sql), empty, 0.0, str(exc))
    sql_eval = eval_sql(message, events, case.expected.gold_sql)
    scores = score(message, events, case.expected, sql_eval)
    return Result(case.name, case.category, completed, first, (time.perf_counter() - start) * 1000, count, len(message), events, sql_eval, scores, weighted(scores))


def summarize(results: list[Result]) -> dict[str, Any]:
    completed = [r for r in results if r.completed]
    sql_cases = [r for r in results if r.sql_evaluation.gold_sql]
    return {
        "case_count": len(results),
        "completed_count": len(completed),
        "completion_rate": len(completed) / len(results) if results else 0.0,
        "avg_weighted_score": statistics.mean([r.weighted_score for r in results]) if results else 0.0,
        "tool_success_rate": statistics.mean([r.scores.tool_use for r in results]) if results else 0.0,
        "sql_execution_accuracy": statistics.mean([1.0 if r.sql_evaluation.execution_match else 0.0 for r in sql_cases]) if sql_cases else 0.0,
        "avg_total_ms": statistics.mean([r.total_ms for r in completed]) if completed else None,
        "avg_first_event_ms": statistics.mean([r.first_event_ms for r in completed if r.first_event_ms is not None]) if completed else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--model", default="qwen-plus")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    requests.get(f"{args.base_url.rstrip('/')}/api/chat/health", timeout=10).raise_for_status()
    results = [run_case(args.base_url, case, args.timeout, args.model) for case in CASES]
    report = {"base_url": args.base_url, "model": args.model, "database_path": str(DB_PATH), "dimension_weights": WEIGHTS, "summary": summarize(results), "results": [asdict(r) for r in results]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["summary"]["avg_weighted_score"] >= 70 else 1


if __name__ == "__main__":
    raise SystemExit(main())

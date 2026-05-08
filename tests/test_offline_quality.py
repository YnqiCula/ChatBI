"""
Offline functional and performance regression tests for ChatBI.

Run from project root:
    python -m unittest discover -s tests -p "test_*.py" -v

These tests avoid real LLM calls so they can run without OPENAI_API_KEY.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import statistics
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TOOLS_DIR = PROJECT_ROOT / "tools"
DB_PATH = TOOLS_DIR / "example.db"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DatabaseContractTests(unittest.TestCase):
    required_tables = {
        "CUSTOMER_DETAILS",
        "ORDER_DETAILS",
        "PAYMENTS",
        "PRODUCTS",
        "TRANSACTIONS",
        "USER_INTERACTIONS",
    }

    def test_example_database_exists(self):
        self.assertTrue(DB_PATH.exists(), f"Missing SQLite database: {DB_PATH}")

    def test_required_tables_exist(self):
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        actual_tables = {row[0] for row in rows}
        self.assertTrue(
            self.required_tables.issubset(actual_tables),
            f"Missing tables: {sorted(self.required_tables - actual_tables)}",
        )

    def test_required_tables_have_sample_data(self):
        with sqlite3.connect(DB_PATH) as conn:
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in self.required_tables
            }
        empty_tables = {table: count for table, count in counts.items() if count <= 0}
        self.assertFalse(empty_tables, f"Tables without sample data: {empty_tables}")

    def test_schema_supports_core_bi_tasks(self):
        with sqlite3.connect(DB_PATH) as conn:
            product_category_rows = conn.execute(
                "SELECT CATEGORY, COUNT(*) FROM PRODUCTS GROUP BY CATEGORY"
            ).fetchall()
            monthly_order_rows = conn.execute(
                "SELECT substr(ORDER_DATE, 1, 7) AS month, SUM(TOTAL_AMOUNT) "
                "FROM ORDER_DETAILS GROUP BY month ORDER BY month"
            ).fetchall()
            join_rows = conn.execute(
                "SELECT p.CATEGORY, SUM(t.QUANTITY * t.PRICE) AS revenue "
                "FROM TRANSACTIONS t JOIN PRODUCTS p ON t.PRODUCT_ID = p.PRODUCT_ID "
                "GROUP BY p.CATEGORY ORDER BY revenue DESC"
            ).fetchall()
        self.assertGreaterEqual(len(product_category_rows), 1)
        self.assertGreaterEqual(len(monthly_order_rows), 1)
        self.assertGreaterEqual(len(join_rows), 1)


class SQLiteToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.execute_module = load_module(
            "tools_execute_sqlite_under_test",
            TOOLS_DIR / "tools_execute_sqlite.py",
        )

    def call_tool(self, query: str):
        tool_obj = self.execute_module.execute_sqlite_query
        if hasattr(tool_obj, "invoke"):
            return tool_obj.invoke({"query": query})
        return tool_obj(query)

    def test_execute_valid_select_query(self):
        result = self.call_tool("SELECT COUNT(*) AS total_products FROM PRODUCTS")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["columns"], ["total_products"])
        self.assertGreater(result["result"]["rows"][0][0], 0)

    def test_execute_join_and_aggregation_query(self):
        result = self.call_tool(
            "SELECT p.CATEGORY, SUM(t.QUANTITY) AS total_quantity "
            "FROM TRANSACTIONS t JOIN PRODUCTS p ON t.PRODUCT_ID = p.PRODUCT_ID "
            "GROUP BY p.CATEGORY ORDER BY total_quantity DESC"
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["columns"], ["CATEGORY", "total_quantity"])
        self.assertGreaterEqual(len(result["result"]["rows"]), 1)

    def test_execute_invalid_sql_returns_structured_error(self):
        result = self.call_tool("SELECT NOT_EXIST_COLUMN FROM PRODUCTS")
        self.assertEqual(result["status"], "error")
        self.assertIn("NOT_EXIST_COLUMN", result["error"])


class StreamingCallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.callback_module = load_module(
            "callback_under_test",
            PROJECT_ROOT / "backend" / "api" / "callback.py",
        )

    def test_streaming_callback_accumulates_tokens_and_invokes_callback(self):
        received = []
        handler = self.callback_module.StreamingCallbackHandler(token_callback=received.append)
        for token in ["产品", "类别", "统计"]:
            handler.on_llm_new_token(token)
        handler.on_llm_end(response=None)
        self.assertEqual(handler.final_message, "产品类别统计")
        self.assertEqual(received, ["产品", "类别", "统计"])
        self.assertTrue(handler.has_streaming_ended)

    def test_extract_text_from_openai_like_delta(self):
        class DeltaToken:
            delta = {"content": "首包"}

        text = self.callback_module._extract_text(DeltaToken())
        self.assertEqual(text, "首包")


class StaticProductContractTests(unittest.TestCase):
    def test_chat_api_exposes_sse_query_health_and_models_endpoints(self):
        chat_py = (PROJECT_ROOT / "backend" / "api" / "chat.py").read_text(encoding="utf-8")
        self.assertIn('@router.post("/query")', chat_py)
        self.assertIn('@router.get("/health")', chat_py)
        self.assertIn('@router.get("/models")', chat_py)
        self.assertIn("EventSourceResponse", chat_py)

    def test_agent_registers_expected_tool_chain(self):
        agent_py = (PROJECT_ROOT / "agent.py").read_text(encoding="utf-8")
        expected_tools = [
            "retriever_tool",
            "text2sqlite_tool",
            "execute_sqlite_query",
            "highcharts_tool",
        ]
        for tool_name in expected_tools:
            self.assertIn(tool_name, agent_py)
        self.assertIn("MemorySaver", agent_py)
        self.assertIn("StateGraph", agent_py)


class LocalSQLPerformanceTests(unittest.TestCase):
    def test_core_sql_queries_p95_latency_under_500ms(self):
        queries = [
            "SELECT COUNT(*) FROM PRODUCTS",
            "SELECT CATEGORY, COUNT(*) FROM PRODUCTS GROUP BY CATEGORY",
            "SELECT substr(ORDER_DATE, 1, 7), SUM(TOTAL_AMOUNT) FROM ORDER_DETAILS GROUP BY 1",
            "SELECT p.CATEGORY, SUM(t.QUANTITY * t.PRICE) "
            "FROM TRANSACTIONS t JOIN PRODUCTS p ON t.PRODUCT_ID = p.PRODUCT_ID GROUP BY p.CATEGORY",
        ]
        durations_ms = []
        with sqlite3.connect(DB_PATH) as conn:
            for _ in range(25):
                for query in queries:
                    start = time.perf_counter()
                    conn.execute(query).fetchall()
                    durations_ms.append((time.perf_counter() - start) * 1000)
        p95 = statistics.quantiles(durations_ms, n=20)[18]
        avg = statistics.mean(durations_ms)
        self.assertLess(
            p95,
            500,
            f"Local SQL p95 latency too high: p95={p95:.2f}ms, avg={avg:.2f}ms",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

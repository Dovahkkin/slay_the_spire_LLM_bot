import unittest
import tempfile
import json
import time
from pathlib import Path
from spire_agent.profiler import StepProfiler
from spire_agent.hud import DummyHud, SpireHud
from analyze_perf import load_telemetry, print_report, export_chrome_trace


class TestProfilerIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "test_telemetry.jsonl"
        self.hud = DummyHud()
        self.profiler = StepProfiler(log_path=self.log_path, hud=self.hud)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_profiler_spans_and_finish_turn(self):
        # 模拟各阶段
        with self.profiler.span("game_sync", "等待游戏"):
            time.sleep(0.01)

        with self.profiler.span("compress", "压缩状态"):
            time.sleep(0.005)

        with self.profiler.span("llm_call", "模型推理"):
            time.sleep(0.02)

        with self.profiler.span("action_exec", "动作执行"):
            time.sleep(0.01)

        self.profiler.add_retry()
        summary = self.profiler.finish_turn(floor=1, turn=1, room_type="COMBAT")

        self.assertGreater(summary["total_time"], 0.03)
        self.assertEqual(summary["floor"], 1)
        self.assertEqual(summary["turn"], 1)
        self.assertEqual(summary["metrics"]["retries"], 1)
        self.assertTrue(self.log_path.exists())

        # 验证写入的数据格式
        records = load_telemetry(self.log_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["floor"], 1)
        self.assertIn("llm_call", records[0]["timings"])

    def test_analyzer_script_functions(self):
        # 创建几条样本数据
        for turn in range(1, 4):
            with self.profiler.span("llm_call"):
                time.sleep(0.005)
            self.profiler.finish_turn(floor=turn, turn=turn, room_type="COMBAT")

        records = load_telemetry(self.log_path)
        self.assertEqual(len(records), 3)

        # 验证 print_report 不崩溃
        print_report(records)

        # 验证 export_chrome_trace
        trace_path = Path(self.temp_dir.name) / "trace.json"
        export_chrome_trace(records, trace_path)
        self.assertTrue(trace_path.exists())

        with open(trace_path, "r", encoding="utf-8") as f:
            trace_data = json.load(f)
            self.assertIn("traceEvents", trace_data)
            self.assertGreater(len(trace_data["traceEvents"]), 0)

    def test_dual_model_config(self):
        import os
        from config import LLMConfig
        # 测试在环境变量覆盖下，宏观模型与战斗模型可独立配置
        os.environ["MACRO_LLM_PROVIDER"] = "deepseek"
        os.environ["MACRO_LLM_MODEL"] = "deepseek-reasoner"
        os.environ["MACRO_LLM_API_KEY"] = "sk-macro-test"
        os.environ["MACRO_LLM_TEMPERATURE"] = "0.7"

        key, base_url, model = LLMConfig.get_credentials(prefix="MACRO_LLM")
        self.assertEqual(key, "sk-macro-test")
        self.assertEqual(model, "deepseek-reasoner")

        temp = LLMConfig.get_temperature(model, prefix="MACRO_LLM")
        self.assertEqual(temp, 0.7)

        # 清理环境变量
        del os.environ["MACRO_LLM_PROVIDER"]
        del os.environ["MACRO_LLM_MODEL"]
        del os.environ["MACRO_LLM_API_KEY"]
        del os.environ["MACRO_LLM_TEMPERATURE"]

    def test_macro_and_reflection_profiler_spans(self):
        # 模拟战后复盘阶段
        with self.profiler.span("llm_call", "[战斗模型: kimi] 战后复盘总结"):
            time.sleep(0.01)
        summary1 = self.profiler.finish_turn(floor=1, turn=3, room_type="COMBAT_VICTORY")
        self.assertEqual(summary1["room_type"], "COMBAT_VICTORY")
        self.assertGreater(summary1["timings"]["llm_call"], 0.005)

        # 模拟宏观选牌阶段
        with self.profiler.span("llm_call", "[宏观模型: deepseek] 战后抓牌决策"):
            time.sleep(0.01)
        summary2 = self.profiler.finish_turn(floor=1, turn=0, room_type="CARD_REWARD")
        self.assertEqual(summary2["room_type"], "CARD_REWARD")
        self.assertGreater(summary2["timings"]["llm_call"], 0.005)


if __name__ == "__main__":
    unittest.main()


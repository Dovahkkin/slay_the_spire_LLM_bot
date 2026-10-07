"""
杀戮尖塔 Agent 性能与耗时遥测分析器 (Performance & Latency Profiler)
精细化打点追踪四阶段耗时：
1. 游戏同步 (game_sync): 通信等待、动画就绪、JSON 接收
2. 状态压缩 (compress): DSL 状态压缩与知识库注入
3. 模型推理 (llm_call): 网络请求、TTFT、Token 生成、重试
4. 动作执行 (action_exec): 指令发送与各卡牌动作结算
"""

import time
import json
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Dict, Any, Optional, List

logger = logging.getLogger("spire_agent.profiler")


class StepProfiler:
    """
    回合/决策步级性能分析器
    单次打点耗时 < 0.001ms，零开销。
    """

    def __init__(self, log_path: Optional[Path] = None, hud: Optional[Any] = None):
        self.hud = hud
        if log_path is None:
            project_root = Path(__file__).resolve().parent.parent
            self.log_path = project_root / "logs" / "telemetry.jsonl"
        else:
            self.log_path = log_path

        # 确保日志目录存在
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        self.reset()

    def reset(self):
        """重置当前回合打点数据"""
        self.turn_start_time = time.perf_counter()
        self.stage_timings: Dict[str, float] = {
            "game_sync": 0.0,
            "compress": 0.0,
            "llm_call": 0.0,
            "action_exec": 0.0,
        }
        self.current_stage: Optional[str] = None
        self.current_stage_start: float = 0.0
        self.metrics: Dict[str, Any] = {
            "retries": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model": "",
            "provider": "",
        }

    @contextmanager
    def span(self, stage: str, description: str = ""):
        """
        高阶耗时上下文管理器
        用法:
            with profiler.span("llm_call", "大模型推理中..."):
                resp = llm.call(...)
        """
        self.start_stage(stage, description)
        try:
            yield
        finally:
            self.end_stage(stage)

    def start_stage(self, stage: str, description: str = ""):
        """进入某一阶段并向 HUD 推送实时秒表更新"""
        self.current_stage = stage
        self.current_stage_start = time.perf_counter()

        if self.hud and hasattr(self.hud, "update_profiler_live"):
            try:
                self.hud.update_profiler_live(
                    stage=stage,
                    desc=description or stage,
                    stage_start=self.current_stage_start,
                )
            except Exception as e:
                logger.debug(f"更新 HUD 实时秒表异常: {e}")

    def end_stage(self, stage: str):
        """离开某一阶段，累计记录该阶段耗时"""
        if self.current_stage == stage:
            elapsed = time.perf_counter() - self.current_stage_start
            self.stage_timings[stage] = self.stage_timings.get(stage, 0.0) + elapsed
            self.current_stage = None

    def record_metric(self, key: str, value: Any):
        """记录模型或执行指标（如 token 数、重试次数）"""
        self.metrics[key] = value

    def add_retry(self):
        """记录一次重试"""
        self.metrics["retries"] = self.metrics.get("retries", 0) + 1

    def finish_turn(
        self,
        floor: int = 0,
        turn: int = 0,
        room_type: str = "COMBAT",
        extra_note: str = ""
    ) -> Dict[str, Any]:
        """
        结束当前回合/动作周期，汇总数据、判断最大瓶颈，并输出到 HUD 与 JSONL 日志。
        """
        # 如果还有未正常关闭的 span，闭合之
        if self.current_stage:
            self.end_stage(self.current_stage)

        total_time = max(0.001, time.perf_counter() - self.turn_start_time)
        t_game = self.stage_timings.get("game_sync", 0.0)
        t_comp = self.stage_timings.get("compress", 0.0)
        t_llm = self.stage_timings.get("llm_call", 0.0)
        t_act = self.stage_timings.get("action_exec", 0.0)

        # 找最大瓶颈
        stage_names = {
            "game_sync": "游戏同步 (Game I/O)",
            "compress": "状态压缩 (Compress)",
            "llm_call": "大模型推理 (LLM Call)",
            "action_exec": "动作执行 (Action Exec)",
        }
        max_stage = max(self.stage_timings, key=self.stage_timings.get)
        bottleneck_name = stage_names.get(max_stage, max_stage)
        bottleneck_pct = (self.stage_timings[max_stage] / total_time) * 100

        summary = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "floor": floor,
            "turn": turn,
            "room_type": room_type,
            "total_time": round(total_time, 3),
            "timings": {
                "game_sync": round(t_game, 3),
                "compress": round(t_comp, 3),
                "llm_call": round(t_llm, 3),
                "action_exec": round(t_act, 3),
            },
            "percentages": {
                "game_sync": round((t_game / total_time) * 100, 1),
                "compress": round((t_comp / total_time) * 100, 1),
                "llm_call": round((t_llm / total_time) * 100, 1),
                "action_exec": round((t_act / total_time) * 100, 1),
            },
            "bottleneck": max_stage,
            "bottleneck_desc": f"{bottleneck_name} ({bottleneck_pct:.1f}%)",
            "metrics": self.metrics.copy(),
            "extra_note": extra_note,
        }

        # 1. 写入结构化 telemetry.jsonl
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"写入 telemetry.jsonl 失败: {e}")

        # 2. 推送给 HUD
        if self.hud and hasattr(self.hud, "update_profiler"):
            try:
                self.hud.update_profiler(summary)
            except Exception as e:
                logger.debug(f"推送 HUD 耗时汇总失败: {e}")

        # 重置分析器备用
        self.reset()
        return summary

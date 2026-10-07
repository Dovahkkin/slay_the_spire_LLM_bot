#!/usr/bin/env python3
"""
杀戮尖塔 Agent 离线性能与耗时深度分析工具 (Offline Telemetry & Latency Profiler)
用法:
    python analyze_perf.py                  # 分析最新 telemetry.jsonl
    python analyze_perf.py --export-trace trace.json   # 导出为 Chrome 瀑布流甘特图 (可在 chrome://tracing 查看)
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_telemetry(log_path: Path) -> List[Dict[str, Any]]:
    if not log_path.exists():
        print(f"[错误] 未找到性能日志文件: {log_path}", file=sys.stderr)
        return []

    records = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def export_chrome_trace(records: List[Dict[str, Any]], output_path: Path):
    """
    导出标准 Google Chrome Trace Event 格式
    可在浏览器中直接输入 chrome://tracing 或 https://ui.perfetto.dev 查看完整的瀑布流交互图。
    """
    trace_events = []
    current_ts_us = 0

    for i, r in enumerate(records):
        floor = r.get("floor", 0)
        turn = r.get("turn", 0)
        room = r.get("room_type", "UNKNOWN")
        timings = r.get("timings", {})
        pid = 1  # Process: Agent
        tid = 1  # Thread: Turn

        step_name = f"Floor {floor} | Turn {turn} ({room})"

        # 记录各阶段耗时区间 (单位: 微秒 us)
        stage_order = [
            ("game_sync", "1. 游戏同步 (Game I/O)"),
            ("compress", "2. 状态压缩 (Compress)"),
            ("llm_call", "3. 模型推理 (LLM Call)"),
            ("action_exec", "4. 动作执行 (Action Exec)"),
        ]

        turn_start_us = current_ts_us
        for key, display_name in stage_order:
            dur_sec = timings.get(key, 0.0)
            dur_us = int(dur_sec * 1_000_000)
            if dur_us > 0:
                trace_events.append({
                    "name": display_name,
                    "cat": "spire_agent",
                    "ph": "X",  # Complete Event
                    "ts": current_ts_us,
                    "dur": dur_us,
                    "pid": pid,
                    "tid": tid,
                    "args": {
                        "floor": floor,
                        "turn": turn,
                        "room": room,
                        "duration_sec": dur_sec,
                    }
                })
                current_ts_us += dur_us

        # 加一个 turn 的包裹事件
        total_dur_us = current_ts_us - turn_start_us
        trace_events.append({
            "name": step_name,
            "cat": "turn_summary",
            "ph": "X",
            "ts": turn_start_us,
            "dur": total_dur_us,
            "pid": pid,
            "tid": 2,  # Separate track for high-level turns
            "args": r.get("percentages", {}),
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"traceEvents": trace_events}, f, ensure_ascii=False, indent=2)

    print(f"\n[成功] 已将性能瀑布流导出为 Chrome Trace 格式: {output_path}")
    print("[提示] 请在 Chrome / Edge 浏览器打开 'chrome://tracing' 并将此文件拖入，即可交互式查看甘特图！")


def print_report(records: List[Dict[str, Any]]):
    if not records:
        print("[提示] 暂无性能日志数据，请先运行一次 Agent 对局。")
        return

    total_turns = len(records)
    total_time = sum(r.get("total_time", 0.0) for r in records)
    sum_game = sum(r.get("timings", {}).get("game_sync", 0.0) for r in records)
    sum_comp = sum(r.get("timings", {}).get("compress", 0.0) for r in records)
    sum_llm = sum(r.get("timings", {}).get("llm_call", 0.0) for r in records)
    sum_act = sum(r.get("timings", {}).get("action_exec", 0.0) for r in records)
    total_retries = sum(r.get("metrics", {}).get("retries", 0) for r in records)

    avg_turn_time = total_time / total_turns if total_turns > 0 else 0

    p_game = (sum_game / total_time * 100) if total_time > 0 else 0
    p_comp = (sum_comp / total_time * 100) if total_time > 0 else 0
    p_llm = (sum_llm / total_time * 100) if total_time > 0 else 0
    p_act = (sum_act / total_time * 100) if total_time > 0 else 0

    def bar(p):
        f = max(0, min(20, int(round(p / 5.0))))
        return "█" * f + "▒" * (20 - f)

    print("\n" + "=" * 65)
    print("      [REPORT] 杀戮尖塔 AGENT 全局耗时与性能深度诊断报告")
    print("=" * 65)
    print(f"分析总轮数: {total_turns} 步/回合 | 累计运行耗时: {total_time:.2f} 秒")
    print(f"平均每回合耗时: {avg_turn_time:.2f} 秒 | 格式重试总次数: {total_retries} 次")
    print("-" * 65)
    print("【全局各阶段耗时分布瀑布流】:")
    print(f"  1. 模型推理 (LLM Call):   {sum_llm:7.2f}s  [{bar(p_llm)}]  {p_llm:5.1f}%  (均: {sum_llm/total_turns:.2f}s)")
    print(f"  2. 游戏同步 (Game I/O):   {sum_game:7.2f}s  [{bar(p_game)}]  {p_game:5.1f}%  (均: {sum_game/total_turns:.2f}s)")
    print(f"  3. 动作执行 (Action Exec): {sum_act:7.2f}s  [{bar(p_act)}]  {p_act:5.1f}%  (均: {sum_act/total_turns:.2f}s)")
    print(f"  4. 状态压缩 (Compress):   {sum_comp:7.2f}s  [{bar(p_comp)}]  {p_comp:5.1f}%  (均: {sum_comp/total_turns:.3f}s)")

    # 瓶颈阶段频率统计
    bottleneck_counts: Dict[str, int] = {}
    for r in records:
        b = r.get("bottleneck", "unknown")
        bottleneck_counts[b] = bottleneck_counts.get(b, 0) + 1

    print("-" * 65)
    print("【最大卡顿瓶颈归属统计】:")
    names = {
        "llm_call": "大模型推理 API",
        "game_sync": "游戏状态同步/动画等待",
        "action_exec": "动作指令下发/出牌动画",
        "compress": "本地 DSL 状态压缩",
    }
    for b_key, count in sorted(bottleneck_counts.items(), key=lambda x: x[1], reverse=True):
        b_name = names.get(b_key, b_key)
        pct = (count / total_turns) * 100
        print(f"  - {b_name:<20}: {count:3d} 轮 ({pct:5.1f}%) 成为该轮最大耗时项")

    # 最慢 Top 5 慢动作回放
    print("-" * 65)
    print("【最慢 TOP 5 决策回合深度排查】:")
    slowest = sorted(records, key=lambda x: x.get("total_time", 0.0), reverse=True)[:5]
    for rank, r in enumerate(slowest, 1):
        fl = r.get("floor", 0)
        tu = r.get("turn", 0)
        rm = r.get("room_type", "")
        tt = r.get("total_time", 0.0)
        ti = r.get("timings", {})
        re_cnt = r.get("metrics", {}).get("retries", 0)
        retry_tag = f" [重试 {re_cnt} 次]" if re_cnt > 0 else ""

        print(f"  #{rank}. 第 {fl} 层 | 回合 {tu} [{rm}] -> 总耗时: {tt:.2f}s{retry_tag}")
        print(f"      LLM: {ti.get('llm_call', 0):.2f}s | 游戏同步: {ti.get('game_sync', 0):.2f}s | 执行: {ti.get('action_exec', 0):.2f}s")

    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="杀戮尖塔 Agent 离线耗时分析工具")
    parser.add_argument(
        "--log",
        default="logs/telemetry.jsonl",
        help="遥测日志路径 (默认 logs/telemetry.jsonl)",
    )
    parser.add_argument(
        "--export-trace",
        default=None,
        help="导出为 Chrome 性能甘特图文件路径 (例如 trace.json)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    log_path = Path(args.log)
    if not log_path.is_absolute():
        log_path = project_root / log_path

    records = load_telemetry(log_path)
    print_report(records)

    if args.export_trace:
        export_path = Path(args.export_trace)
        if not export_path.is_absolute():
            export_path = project_root / export_path
        export_chrome_trace(records, export_path)


if __name__ == "__main__":
    main()

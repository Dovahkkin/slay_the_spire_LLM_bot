import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("combat_tracer")

class CombatTracer:
    """
    战斗全流程深度追踪诊断器：
    专用于定位首回合怪物意图伤害丢失、药水未执行、卡牌出牌异常等时序与通信问题。
    将每一步的原始通信数据、状态压缩文本、Prompt、模型输出及执行细节写入 logs/combat_trace.log。
    """
    _instance: Optional["CombatTracer"] = None

    def __init__(self, log_path: Optional[Path] = None):
        if log_path is None:
            project_root = Path(__file__).resolve().parent.parent
            log_dir = project_root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = log_dir / "combat_trace.log"
        else:
            self.log_path = log_path

    @classmethod
    def get_instance(cls) -> "CombatTracer":
        if cls._instance is None:
            cls._instance = CombatTracer()
        return cls._instance

    def _write_section(self, title: str, content: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        separator = "=" * 70
        block = f"\n{separator}\n[{timestamp}] {title}\n{separator}\n{content}\n"
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(block)
        except Exception as e:
            logger.warning(f"写入 combat_trace.log 失败: {e}")

    def log_raw_combat_frame(self, raw_json: Dict[str, Any], debounce_status: str = "PASS"):
        """记录 CommunicationMod 发来的底层原始帧详情"""
        game_state = raw_json.get("game_state", {})
        combat_state = game_state.get("combat_state") or raw_json.get("combat_state") or {}
        monsters = combat_state.get("monsters", [])

        lines = []
        lines.append(f"Ready: {raw_json.get('ready_for_command')} | Available Commands: {raw_json.get('available_commands')}")
        lines.append(f"In Combat: {game_state.get('in_combat', raw_json.get('in_combat'))} | Turn: {combat_state.get('turn', '?')} | Floor: {game_state.get('floor', '?')}")
        lines.append(f"防抖拦截判定: {debounce_status}")
        lines.append("\n【原始怪物列表 (CommunicationMod Raw Monsters)】:")
        if not monsters:
            lines.append("  (无怪物数据)")
        for idx, m in enumerate(monsters):
            lines.append(
                f"  - Monster #{idx} [{m.get('name')} | ID: {m.get('id')}]:\n"
                f"      HP: {m.get('current_hp')}/{m.get('max_hp')} | Block: {m.get('block')}\n"
                f"      Intent: {m.get('intent')}\n"
                f"      move_adjusted_damage: {m.get('move_adjusted_damage')}\n"
                f"      move_base_damage: {m.get('move_base_damage')}\n"
                f"      move_hits: {m.get('move_hits')}\n"
                f"      is_gone: {m.get('is_gone')} | half_dead: {m.get('half_dead')}"
            )

        hand = combat_state.get("hand", [])
        lines.append(f"\n【原始手牌列表 (共 {len(hand)} 张)】:")
        for idx, c in enumerate(hand):
            lines.append(
                f"  - Card #{idx} [{c.get('name')} | ID: {c.get('id')}]: "
                f"cost={c.get('cost')}, type={c.get('type')}, target={c.get('target')}, "
                f"has_target={c.get('has_target')}, dmg={c.get('damage')}, blk={c.get('block')}"
            )

        self._write_section("STEP 1: COMMUNICATIONMOD RAW FRAME DATA", "\n".join(lines))

    def log_compressed_prompt(self, turn: int, dsl_state: str, guidance: str):
        """记录状态压缩器生成并提交给大模型的完整 Prompt DSL"""
        content = f"--- TURN {turn} DSL STATE ---\n{dsl_state}\n\n--- GUIDANCE ---\n{guidance}"
        self._write_section(f"STEP 2: COMPRESSED COMBAT DSL PROMPT (TURN {turn})", content)

    def log_llm_response(self, turn: int, raw_response: str):
        """记录大模型的原始推演与规划输出"""
        self._write_section(f"STEP 3: LLM RAW RESPONSE (TURN {turn})", raw_response if raw_response else "(EMPTY RESPONSE)")

    def log_parsed_plan(self, turn: int, actions: List[Any]):
        """记录从大模型输出中解析出的动作序列"""
        lines = [f"解析出 {len(actions)} 个动作:"]
        for idx, act in enumerate(actions):
            lines.append(f"  #{idx + 1}: {act.__class__.__name__} -> {getattr(act, 'raw_command', str(act))}")
        self._write_section(f"STEP 4: PARSED ACTION SEQUENCE (TURN {turn})", "\n".join(lines))

    def log_action_execution(self, act_idx: int, cmd: str, result_summary: str):
        """记录单个动作发送给游戏后的响应"""
        content = f"Action #{act_idx}: {cmd}\nResult: {result_summary}"
        self._write_section(f"STEP 5: ACTION EXECUTION", content)

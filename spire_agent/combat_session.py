import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from .models import (
    CombatState,
    PlayCardAction,
    UsePotionAction,
    EndTurnAction,
    TurnPlan,
    Card,
    Monster,
)
from .compressor import StateCompressor
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from llm_client import SpireLLMClient

logger = logging.getLogger("spire_agent.combat")


class AmbiguousTargetError(Exception):
    """当存在多个存活敌人且单体攻击卡缺失目标时抛出，用于向大模型返回错误并重规划"""

    def __init__(self, card_name: str, alive_monsters: List[Monster]):
        self.card_name = card_name
        self.alive_monsters = alive_monsters
        m_list = ", ".join([f"[E{m.index}] {m.name} (HP {m.current_hp})" for m in alive_monsters])
        self.message = (
            f"Card [{card_name}] is a single-target attack card. There are {len(alive_monsters)} alive enemies: {m_list}. "
            f"Target enemy was not specified (you MUST explicitly specify target like E0, E1)!"
        )
        super().__init__(self.message)


class CombatSession:
    """
    微观战斗独立会话管理器：
    - 生命周期：单场即弃。战斗打响时激活，战斗胜利后【立即 reset() 清空】；
    - 绝不把上一场的陈旧出牌碎语带入下一场战斗，保证极低 Token 消耗与最高专注度；
    - 负责单回合连击规划 (TurnPlan) 生成与合法性校验。
    """

    def __init__(
        self,
        llm_client: SpireLLMClient,
        enable_tools: bool = True,
        enable_calculator: bool = True,
        blackboard: Optional[Any] = None,
        profiler: Optional[Any] = None,
    ):
        self.llm_client = llm_client
        self.enable_tools = enable_tools
        self.enable_calculator = enable_calculator
        self.blackboard = blackboard
        self.hud = getattr(blackboard, "hud", None)
        self.profiler = profiler
        self.messages: List[Dict[str, Any]] = []
        self.system_prompt = self._load_system_prompt()
        self.current_combat_turn = 0

        # 本场战斗统计指标
        self.combat_start_hp: int = 0
        self.combat_start_max_hp: int = 0
        self.encounter_name: str = "未知怪物"

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).parent.parent / "prompts" / "combat_system.md"
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return "You are an expert Slay the Spire player. Plan the best card sequence for this turn."

    def reset(self):
        """战斗结束时调用：清空所有本场对话记忆"""
        logger.info("[CombatSession] 战斗结束，重置并清空战斗临时上下文。")
        self.messages = []
        self.current_combat_turn = 0
        self.combat_start_hp = 0
        self.encounter_name = "未知怪物"

    def on_combat_end(self, final_hp: int = 0, max_hp: int = 80, floor: int = 0):
        """战斗胜利结束时由主驱动调用：生成实战复盘写入黑板，随后重置战斗上下文"""
        turns = self.current_combat_turn or 1
        start_hp = self.combat_start_hp if self.combat_start_hp > 0 else (final_hp or max_hp)
        actual_final_hp = final_hp if final_hp > 0 else start_hp
        hp_lost = max(0, start_hp - actual_final_hp)

        model_name = getattr(self.llm_client, "model", "")
        model_label = f" [{model_name}]" if model_name else ""
        stage_desc = f"[战斗模型: {model_name}] 战后复盘总结" if model_name else "战后复盘总结"

        if self.hud and hasattr(self.hud, "update_thinking"):
            self.hud.update_thinking(
                thought=f"战斗胜利！正在进行第 {floor} 层遭遇战【{self.encounter_name}】战后复盘分析...",
                action="WAIT",
                status=f"第 {floor} 层 | 遭遇战胜利 | 战后复盘",
                badge=f"📝 战后复盘{model_label}",
                badge_color="#3742fa",
            )

        reflection = ""
        if self.profiler:
            with self.profiler.span("llm_call", description=stage_desc):
                reflection = self._generate_combat_reflection(floor, turns, hp_lost, actual_final_hp, max_hp)
        else:
            reflection = self._generate_combat_reflection(floor, turns, hp_lost, actual_final_hp, max_hp)

        if self.blackboard:
            self.blackboard.record_combat_postmortem(
                floor=floor,
                encounter=self.encounter_name,
                turns=turns,
                hp_lost=hp_lost,
                remaining_hp=actual_final_hp,
                max_hp=max_hp,
                summary=reflection,
            )

        if self.hud and hasattr(self.hud, "update_thinking"):
            self.hud.update_thinking(
                thought=f"战后复盘：{reflection}",
                action="PROCEED",
                status=f"第 {floor} 层 | 战利品结算",
                badge="🏆 战斗胜利",
                badge_color="#2ed573",
            )

        if self.profiler:
            self.profiler.finish_turn(floor=floor, turn=turns, room_type="COMBAT_VICTORY")

        self.reset()

    def _generate_combat_reflection(
        self, floor: int, turns: int, hp_lost: int, final_hp: int, max_hp: int
    ) -> str:
        """调用大模型（或规则兜底）生成精炼的一句话实战反思"""
        if self.llm_client.is_available:
            prompt = (
                f"You just concluded combat on floor {floor} against [{self.encounter_name}].\n"
                f"Combat stats: Duration {turns} turns, HP lost {hp_lost} (Current HP: {final_hp}/{max_hp}).\n"
                "Provide a concise 1-sentence post-combat tactical reflection (evaluating offensive/defensive tempo, deck deficiencies, and lessons for subsequent card drafting). Output the reflection text directly without extra commentary."
            )
            try:
                # 附带本场完整出牌推演历史，使战后反思更具深度与连续性
                reflection_messages = list(self.messages) if self.messages else [
                    {"role": "system", "content": self.system_prompt}
                ]
                reflection_messages.append({"role": "user", "content": prompt})
                res = self.llm_client.run_react_turn(
                    messages=reflection_messages,
                    enable_tools=False,
                )
                clean = res.strip().replace("\n", " ")
                if clean:
                    return clean
            except Exception as e:
                logger.warning(f"大模型战后反思生成异常: {e}")

        # 本地启发式反思保底
        if hp_lost == 0:
            return f"Flawless victory in {turns} turns with 0 HP lost; offensive and defensive tempo was smooth."
        elif hp_lost >= 15:
            return f"High HP loss ({hp_lost} HP) over {turns} turns; slow setup or defensive gaps, beware defense vacuums."
        else:
            return f"Combat concluded steadily in {turns} turns with {hp_lost} HP lost; normal transition pacing."

    def plan_turn(self, state: CombatState, run_memo: str = "") -> TurnPlan:
        """
        推演并生成当前回合的完整出牌方案
        """
        is_new_combat = (
            not self.messages
            or state.turn < self.current_combat_turn
        )
        if is_new_combat:
            self.messages = [
                {"role": "system", "content": self.system_prompt}
            ]
            self.combat_start_hp = state.player.current_hp
            self.combat_start_max_hp = state.player.max_hp
            alive_monsters = [m.name for m in state.monsters if m.current_hp > 0]
            if alive_monsters:
                self.encounter_name = ", ".join(alive_monsters)

        self.current_combat_turn = state.turn

        # 上下文长度截断保护：若回合数异常冗长（超过 30 条消息），保留 system prompt 及最近 10 条交互
        if len(self.messages) > 30:
            logger.info("[CombatSession] 战斗对话历史超过 30 条，执行尾部窗口截断保护。")
            self.messages = [self.messages[0]] + self.messages[-10:]

        if self.profiler:
            with self.profiler.span("compress", "压缩战斗状态与组装 Prompt"):
                dsl_state = StateCompressor.compress_combat(state)
        else:
            dsl_state = StateCompressor.compress_combat(state)

        if self.enable_tools and self.enable_calculator:
            guidance = (
                "[Combat Guidance]: Analyze the combat state, verify calculations with the calculator tool if needed, "
                "leverage monster tactical intelligence, and output the optimal turn plan."
            )
        else:
            guidance = (
                "[Mental Arithmetic Mode]: Calculate damage and block using card numbers, monster tactical intelligence, "
                "and Spire damage formulas to provide the optimal turn plan."
            )

        # 从黑板获取宏观战略锦囊
        if self.blackboard:
            briefing = self.blackboard.get_combat_briefing()
        else:
            briefing = run_memo or "No specific strategic memo."

        user_content = f"=== MACRO STRATEGIC BRIEFING ===\n{briefing}\n\n{dsl_state}\n\n{guidance}"

        from .combat_tracer import CombatTracer
        tracer = CombatTracer.get_instance()
        tracer.log_compressed_prompt(turn=state.turn, dsl_state=dsl_state, guidance=guidance)

        # 记录本回合状态输入
        self.messages.append({"role": "user", "content": user_content})

        raw_response = ""
        if self.llm_client.is_available:
            try:
                if self.profiler:
                    with self.profiler.span("llm_call", f"调用大模型推演战斗 (回合 {state.turn})"):
                        raw_response = self.llm_client.run_react_turn(
                            messages=self.messages,
                            context=state,
                            max_iterations=4 if self.enable_tools else 1,
                            enable_tools=self.enable_tools,
                        )
                else:
                    raw_response = self.llm_client.run_react_turn(
                        messages=self.messages,
                        context=state,
                        max_iterations=4 if self.enable_tools else 1,
                        enable_tools=self.enable_tools,
                    )
                tracer.log_llm_response(turn=state.turn, raw_response=raw_response)
                if raw_response:
                    logger.info(f"大模型原始战斗规划输出:\n{raw_response}")
            except Exception as e:
                logger.error(f"调用大模型推演战斗异常: {e}")

        # 解析模型输出的 plan 块（支持目标歧义自动反馈重规划）
        plan = None
        for retry in range(2):
            try:
                plan = self._parse_plan_from_text(raw_response, state)
                if plan and plan.actions:
                    tracer.log_parsed_plan(turn=state.turn, actions=plan.actions)
                    if raw_response:
                        self.messages.append({"role": "assistant", "content": raw_response})
                    break
            except AmbiguousTargetError as e:
                logger.warning(f"[CombatSession] 检测到目标缺失且存在多个敌人: {e.message}")
                if not self.llm_client.is_available:
                    plan = self._parse_plan_from_text(raw_response, state, allow_fallback_multi_target=True)
                    if plan and plan.actions:
                        tracer.log_parsed_plan(turn=state.turn, actions=plan.actions)
                    if raw_response:
                        self.messages.append({"role": "assistant", "content": raw_response})
                    break

                error_feedback = (
                    f"Command Syntax Error: {e.message}\n"
                    f"Please re-output the ```plan code block with explicit target enemy indices for single-target attack cards (e.g. PLAY c0 E0 or PLAY c0 E1)."
                )
                self.messages.append({"role": "assistant", "content": raw_response})
                self.messages.append({"role": "user", "content": error_feedback})
                try:
                    if self.profiler:
                        self.profiler.add_retry()
                        with self.profiler.span("llm_call", "目标缺失/重试修正推演"):
                            retry_response = self.llm_client.run_react_turn(
                                messages=self.messages,
                                context=state,
                                max_iterations=1,
                                enable_tools=False,
                            )
                    else:
                        retry_response = self.llm_client.run_react_turn(
                            messages=self.messages,
                            context=state,
                            max_iterations=1,
                            enable_tools=False,
                        )
                    if retry_response:
                        logger.info(f"大模型重规划修正输出:\n{retry_response}")
                        raw_response = retry_response
                    else:
                        if self.messages and self.messages[-1].get("role") == "user":
                            self.messages.pop()
                except Exception as ex:
                    logger.error(f"模型修正调用异常: {ex}")
                    if self.messages and self.messages[-1].get("role") == "user":
                        self.messages.pop()
                    plan = self._parse_plan_from_text(raw_response, state, allow_fallback_multi_target=True)
                    break

        if not plan or not plan.actions:
            logger.info("未提取到大模型有效 plan，采用本地启发式兜底生成出牌序列。")
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
            plan = self._heuristic_fallback_turn_plan(state)

        return plan

    def decide_in_combat_card_selection(
        self,
        screen_type: str,
        prompt: str,
        cards: List[Card],
        can_confirm: bool = False,
    ) -> BaseAction:
        """
        处理战斗内的二次卡牌选择（如战吼放回牌顶、头槌捞弃牌堆、真拟选卡消耗、武装升级等）
        将候选卡牌与游戏目标完全呈现给大模型，由大模型自主决策！
        """
        from .models import ChooseAction, ConfirmAction

        from .knowledge.cards_db import lookup_card_stats
        is_upgrade_mode = any(kw in (prompt or "").lower() for kw in ["upgrade", "smith", "armaments", "武装", "升级"])

        card_lines = []
        for idx, c in enumerate(cards):
            effs = []
            if c.damage > 0:
                effs.append(f"{c.damage} dmg")
            if c.block > 0:
                effs.append(f"{c.block} blk")
            if c.description:
                effs.append(c.description)
            eff_desc = ", ".join(effs) if effs else "Special"

            if is_upgrade_mode:
                stats = lookup_card_stats(c.id, c.name, upgraded=False)
                raw_entry = stats.get("raw_entry", {})
                upg_desc = raw_entry.get("desc", "")
                if upg_desc:
                    eff_desc += f" | [Upgrade Effect: {upg_desc}]"

            card_lines.append(f"* [{idx}] {c.name} ({c.cost}E, {c.type}) -> {eff_desc}")

        cards_str = "\n".join(card_lines)
        user_content = (
            f"=== IN-COMBAT CARD SELECTION ({screen_type}) ===\n"
            f"Game Objective: {prompt or 'Select a card'}\n\n"
            f"VISIBLE CANDIDATE CARDS:\n{cards_str}\n\n"
            f"Please reason about which card best fits your immediate tactical needs, "
            f"then output your choice inside an ```action block: CHOOSE <index>."
        )

        if not self.messages:
            self.messages = [{"role": "system", "content": self.system_prompt}]

        self.messages.append({"role": "user", "content": user_content})

        if self.llm_client.is_available:
            try:
                res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                if res:
                    self.messages.append({"role": "assistant", "content": res})
                    pattern = r"```(?:action)?\s*CHOOSE\s+(?:#|c|\[c?)?(\d+)\]?.*?(?:```|$)"
                    match = re.search(pattern, res, re.DOTALL | re.IGNORECASE)
                    if not match:
                        match = re.search(r"CHOOSE\s+(?:#|c|\[c?)?(\d+)", res, re.IGNORECASE)
                    if match:
                        chosen_idx = int(match.group(1))
                        if 0 <= chosen_idx < len(cards):
                            logger.info(f"大模型自主选择战斗子卡牌 (索引 #{chosen_idx}): {cards[chosen_idx].name}")
                            return ChooseAction.create(chosen_idx)
                else:
                    if self.messages and self.messages[-1].get("role") == "user":
                        self.messages.pop()
            except Exception as e:
                logger.error(f"大模型子卡牌选择推演异常: {e}")
                if self.messages and self.messages[-1].get("role") == "user":
                    self.messages.pop()
        else:
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()

        # 启发式兜底：优先选择非基础打击防御的高价值卡牌
        unupgraded_cards = [c for c in cards if not getattr(c, "upgraded", False)]
        candidates = unupgraded_cards if unupgraded_cards else cards
        non_basic = [c for c in candidates if c.name.lower() not in ["strike", "defend", "打击", "防御"]]
        best_candidate = non_basic[0] if non_basic else candidates[0]
        logger.info(f"战斗子卡牌选择启发式兜底: 索引 #{best_candidate.index} ({best_candidate.name})")
        return ChooseAction.create(best_candidate.index)

    def _parse_plan_from_text(
        self, text: str, state: CombatState, allow_fallback_multi_target: bool = False
    ) -> Optional[TurnPlan]:
        if not text:
            return None

        # 1. 匹配 ```plan ... ```
        pattern = r"```plan\s*(.*?)\s*```"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        plan_block = match.group(1).strip() if match else ""

        # 2. 容错匹配：如果模型没有使用 ```plan 块，尝试按行抓取以 PLAY 或 END 开头的行
        if not plan_block:
            lines = [line.strip() for line in text.split("\n") if line.strip().upper().startswith(("PLAY", "END"))]
            plan_block = "\n".join(lines)

        if not plan_block:
            return None

        actions = []
        alive_indices = {m.index for m in state.alive_monsters}
        default_target = state.alive_monsters[0].index if state.alive_monsters else 0

        # 维护规划中的可用手牌与药水副本，避免同张牌/同格药水被重复规划
        remaining_hand = list(state.hand)
        remaining_potions = [p for p in state.potions if p.can_use]

        for line in plan_block.split("\n"):
            line = line.strip()
            if not line:
                continue

            # 去掉行号（如 "1. PLAY 0 0" -> "PLAY 0 0"）
            clean_line = re.sub(r"^\d+[\.\s\-]+", "", line).strip()
            parts = clean_line.split()
            if not parts:
                continue

            cmd = parts[0].upper()

            if cmd == "END" or "END" in cmd:
                actions.append(EndTurnAction.create())
                break

            if cmd in ["USE", "POTION", "DRINK"]:
                sub_parts = parts[1:]
                while sub_parts and sub_parts[0].upper() in ["USE", "POTION"]:
                    sub_parts = sub_parts[1:]
                if not sub_parts:
                    continue

                potion_token = sub_parts[0].strip("[],()\"' ")
                target_token = sub_parts[1].strip("[],()\"' ") if len(sub_parts) >= 2 else None

                matched_pot = None
                # 策略 1: 尝试匹配数字索引 (0, "p0", "[p0]")
                m_p = re.search(r"p?(\d+)", potion_token, re.IGNORECASE)
                if m_p:
                    parsed_p_idx = int(m_p.group(1))
                    matched_pot = next((p for p in remaining_potions if p.index == parsed_p_idx), None)

                # 策略 2: 尝试按药水名称模糊匹配
                if not matched_pot:
                    p_name_target = potion_token.lower()
                    matched_pot = next(
                        (p for p in remaining_potions if p_name_target in p.name.lower() or p_name_target in p.id.lower()),
                        None
                    )

                if not matched_pot:
                    logger.warning(f"[_parse_plan] 无法在可用药水中识别或已被使用: '{potion_token}'，跳过该行。")
                    continue

                remaining_potions.remove(matched_pot)

                # 解析目标索引
                t_idx = None
                if target_token:
                    m_t = re.search(r"e?(\d+)", target_token, re.IGNORECASE)
                    if m_t:
                        t_idx = int(m_t.group(1))

                # 目标判定：若药水需要指定敌人目标
                if matched_pot.requires_target:
                    if t_idx is not None and t_idx in alive_indices:
                        final_p_target = t_idx
                    else:
                        final_p_target = default_target
                else:
                    final_p_target = None

                actions.append(UsePotionAction.create(potion_index=matched_pot.index, target_index=final_p_target))
                continue

            if cmd == "PLAY" and len(parts) >= 2:
                card_token = parts[1].strip("[],()\"' ")
                target_token = parts[2].strip("[],()\"' ") if len(parts) >= 3 else None

                matched_card = None

                # 策略 1: 尝试匹配数字索引 (0, "c0", "[c0]")
                m_c = re.search(r"c?(\d+)", card_token, re.IGNORECASE)
                if m_c:
                    parsed_idx = int(m_c.group(1))
                    matched_card = next((c for c in remaining_hand if c.index == parsed_idx), None)

                # 策略 2: 尝试按卡牌名匹配 (如 "Strike", "Defend", "Bash", "打击", "防御", "痛击")
                if not matched_card:
                    t_lower = card_token.lower()
                    for c in remaining_hand:
                        c_name_lower = c.name.lower()
                        if (
                            t_lower in c_name_lower
                            or t_lower in c.id.lower()
                            or (c_name_lower == "strike" and any(k in t_lower for k in ["strike", "打击"]))
                            or (c_name_lower == "defend" and any(k in t_lower for k in ["defend", "防御"]))
                            or (c_name_lower == "bash" and any(k in t_lower for k in ["bash", "痛击"]))
                        ):
                            matched_card = c
                            break

                if not matched_card:
                    logger.warning(f"[_parse_plan] 无法在当前手牌中识别卡牌: '{card_token}'，跳过该行。")
                    continue

                remaining_hand.remove(matched_card)

                # 解析目标索引
                t_idx = None
                if target_token:
                    m_t = re.search(r"e?(\d+)", target_token, re.IGNORECASE)
                    if m_t:
                        t_idx = int(m_t.group(1))

                # 目标判定：单体攻击卡或标记为需要目标的卡牌必须具有有效目标
                is_attack = matched_card.type == "ATTACK" and matched_card.target_type != "ALL_ENEMY"
                needs_target = matched_card.has_target or matched_card.target_type == "ENEMY" or is_attack

                if needs_target:
                    if t_idx is not None and t_idx in alive_indices:
                        final_target = t_idx
                    else:
                        # 目标未指定或指定的目标已不在存活列表中
                        if len(state.alive_monsters) <= 1:
                            # 只有一个存活目标：直接安全兜底
                            final_target = default_target
                        else:
                            # 有两个以上存活目标：抛出 AmbiguousTargetError 异常，让上层向大模型报错反思
                            if not allow_fallback_multi_target:
                                raise AmbiguousTargetError(matched_card.name, state.alive_monsters)
                            final_target = default_target
                else:
                    final_target = None

                actions.append(
                    PlayCardAction.create(
                        card_index=matched_card.index,
                        target_index=final_target,
                        card_name=matched_card.name,
                        card_id=matched_card.id,
                    )
                )

        if actions and not isinstance(actions[-1], EndTurnAction):
            actions.append(EndTurnAction.create())

        # 提取推演说明
        reasoning = text.split("```plan")[0].strip() if "```plan" in text else text[:200]
        return TurnPlan(reasoning=reasoning, actions=actions)

    def _heuristic_fallback_turn_plan(self, state: CombatState) -> TurnPlan:
        """
        离线启发式连击规划（无 API Key 或大模型异常时的可靠保底）
        按逻辑生成本回合的一整套连招：
        1. 0 费增益/过牌前置；
        2. 斩杀检测（若有残血直接带走）；
        3. 算清未格挡伤害，必要时出防御；
        4. 倾泻剩余能量打出伤害；
        5. 结束回合。
        """
        actions = []
        energy = state.player.energy
        playable = [c for c in state.playable_cards]
        alive = state.alive_monsters

        if not alive or not playable:
            return TurnPlan(reasoning="无可用手牌或无存活敌人，直接结束回合。", actions=[EndTurnAction.create()])

        # 1. 0 费增益卡（如活动肌肉 Flex）优先
        flex = next((c for c in playable if c.cost == 0 and "flex" in c.name.lower()), None)
        if flex:
            actions.append(PlayCardAction.create(flex.index, None))
            playable = [c for c in playable if c.index != flex.index]

        # 2. 计算未格挡伤害与防御需求
        total_incoming = sum(m.total_incoming_damage for m in alive)
        needed_block = max(0, total_incoming - state.player.block)

        # 3. 痛击/易伤前置
        target_m = alive[0]
        bash = next((c for c in playable if c.cost <= energy and (c.id == "Bash" or "vulnerable" in (c.description or "").lower())), None)
        if bash:
            actions.append(PlayCardAction.create(bash.index, target_m.index))
            energy -= bash.cost
            playable = [c for c in playable if c.index != bash.index]

        # 4. 需要防御则打防御
        if needed_block > 0:
            blocks = [c for c in playable if c.block > 0 and c.cost <= energy]
            for b in blocks:
                actions.append(PlayCardAction.create(b.index, None))
                energy -= b.cost
                needed_block -= b.block
                playable = [c for c in playable if c.index != b.index]
                if needed_block <= 0:
                    break

        # 5. 剩余能量打攻击
        attacks = [c for c in playable if c.type == "ATTACK" and c.cost <= energy]
        for atk in attacks:
            if energy >= atk.cost:
                t = target_m.index if (atk.has_target or atk.target_type == "ENEMY") else None
                actions.append(PlayCardAction.create(atk.index, t))
                energy -= atk.cost

        # 6. 回合收尾
        actions.append(EndTurnAction.create())
        return TurnPlan(reasoning="【规则保底推演】按时序前置增益并平衡攻防。", actions=actions)

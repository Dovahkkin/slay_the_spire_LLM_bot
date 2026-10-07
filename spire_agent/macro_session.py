import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from .models import (
    FullGameState,
    Card,
    BaseAction,
    ChooseAction,
    CancelAction,
    ProceedAction,
    LeaveAction,
    ConfirmAction,
)
from .compressor import StateCompressor
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from llm_client import SpireLLMClient

logger = logging.getLogger("spire_agent.macro")


class MacroSession:
    """
    宏观长线战略会话管理器：
    - 统一处理：战后抓牌 (Card Reward)、事件抉择 (Event)、商店消费与删牌 (Shop)、地图走图导航 (Map Route)；
    - 跨层保持卡组流派理解，维护动态【战略备忘录 Run Memo】；
    - 隔离于战斗出牌碎语，专注牌组构筑与宏观风险收益平衡。
    """

    def __init__(
        self,
        llm_client: SpireLLMClient,
        blackboard: Optional[Any] = None,
        hud: Optional[Any] = None,
        profiler: Optional[Any] = None,
    ):
        self.llm_client = llm_client
        self.blackboard = blackboard
        self.hud = hud or getattr(blackboard, "hud", None)
        self.profiler = profiler
        self.shop_purchase_count = 0
        self._fallback_memo = "Starter Deck. Act 1: Prioritize frontloaded burst physical damage (e.g. Carnage, Cleave, Heavy Blade) to prepare for early Elites."
        self.system_prompt = self._load_system_prompt()
        self.messages: List[Dict[str, Any]] = []
        self.current_room_floor: int = -1

    def reset_room_context(self):
        """重置当前房间内的对话历史与状态（在进入新层数/房间时调用）"""
        self.messages = []
        self.current_room_floor = -1
        self.shop_purchase_count = 0

    def _ensure_room_messages(self, floor: int = 0):
        """
        确保当前房间内的对话历史上下文存在且有效：
        - 若进入新层数（floor > 0 且 self.current_room_floor > 0 且 floor != self.current_room_floor），重置房间记忆；
        - 确保起始消息为 system prompt；
        - 防止单房间内对话过度膨胀（保留 system prompt 与最近 10 条消息）。
        """
        if floor > 0 and self.current_room_floor > 0 and floor != self.current_room_floor:
            self.reset_room_context()
        if floor > 0:
            self.current_room_floor = floor

        if not self.messages:
            self.messages = [{"role": "system", "content": self.system_prompt}]
        elif self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": self.system_prompt})

        if len(self.messages) > 15:
            self.messages = [self.messages[0]] + self.messages[-10:]

    @property
    def run_memo(self) -> str:
        if self.blackboard:
            return self.blackboard.get_macro_context()
        return self._fallback_memo

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).parent.parent / "prompts" / "macro_system.md"
        if prompt_path.exists():
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return "You are an expert Slay the Spire strategist. Make the best macro decisions for card rewards and map routing."

    def update_run_memo_heuristic(self, deck: List[Card], relics: List[str]):
        """本地启发式流派识别（作为大模型未输出 memo 时的智能保底）"""
        cards_lower = [c.name.lower() for c in deck]
        relics_lower = [r.lower() for r in relics]

        archetype = "Deck Building / Transition"
        win_con = "Balance offense and defense, acquire core enablers."
        play_guide = "Block incoming threat accurately, unleash attacks on safe turns."
        focus = "Acquire core scaling enablers; purge basic Strikes at shops."

        # 1. 树枝腐化 (God Tier)
        if any("dead branch" in r for r in relics_lower) and any("corruption" in c for c in cards_lower):
            archetype = "Corruption + Dead Branch (God Tier)"
            win_con = "Dead Branch + Corruption engine: infinite card draw, block, and firepower."
            play_guide = "Play Corruption early, dump 0-cost skills to generate endless fresh resources."
            focus = "Draft high-impact skills, Feel No Pain, Dark Embrace; aggressively purge Strikes."
        # 2. 异蛇之眼
        elif any("snecko eye" in r for r in relics_lower):
            archetype = "Snecko Eye High-Cost Heavy Bomb"
            win_con = "Draw 7 cards per turn, crush enemies with 2-3 cost heavy bombs."
            play_guide = "Prioritize high-cost bombs rolled at 0-1 energy (Bludgeon, Immolate, Demon Form)."
            focus = "Draft premium 2-3 cost cards; strictly avoid 0-1 cost clutter."
        # 3. 腐化黑拥精炼消耗流
        elif any("corruption" in c for c in cards_lower) and any("dark embrace" in c for c in cards_lower):
            archetype = "Exhaust Engine (Corruption + Dark Embrace)"
            win_con = "Cycle entire deck in 1 turn via Exhaust synergy, Entrench block into Body Slam lethal."
            play_guide = "Set up Dark Embrace & Feel No Pain, trigger Corruption to cycle all skills."
            focus = "Look for Body Slam, Entrench, Feel No Pain, Sentinel; purge Strikes at shops."
        # 4. 防战壁垒
        elif (any("barricade" in c for c in cards_lower) or any("calipers" in r for r in relics_lower)) and any("entrench" in c or "body slam" in c for c in cards_lower):
            archetype = "High Defense & Body Slam (Barricade)"
            win_con = "Retain block across turns, double block with Entrench, lethal Body Slam damage."
            play_guide = "Play Barricade on turn 1, stack block, execute lethal once block doubles."
            focus = "Find Body Slam, Entrench, Impervious; purge basic Strikes."
        # 5. 力量战
        elif any("spot weakness" in c or "inflame" in c or "demon form" in c for c in cards_lower) and any("limit break" in c or "heavy blade" in c or "reaper" in c for c in cards_lower):
            archetype = "High Strength Scaling"
            win_con = "Stack Strength via Spot Weakness / Inflame, scale with Limit Break, finish with Heavy Blade & Reaper."
            play_guide = "Deploy Strength powers early, hold Heavy Blade for lethal finish, sustain HP with Reaper."
            focus = "Look for Reaper, multi-hit attacks (Twin Strike, Whirlwind), maintain solid defense."
        # 6. 状态进化流
        elif any("evolve" in c or "fire breathing" in c for c in cards_lower) and any("power through" in c or "wild strike" in c or "reckless charge" in c or "immolate" in c for c in cards_lower):
            archetype = "Status & Evolve / Fire Breathing"
            win_con = "Generate Wounds/Dazed to trigger massive draw from Evolve and AoE burn from Fire Breathing."
            play_guide = "Play Evolve and Fire Breathing ASAP; turn Power Through and Immolate downsides into pure value."
            focus = "Look for Power Through, Immolate, Medical Kit relic; sustain status generation."
        # 7. 完美打击流
        elif any("perfected strike" in c for c in cards_lower):
            archetype = "Perfected Strike Burst"
            win_con = "Stack cards with 'Strike' in their name for massive single-hit flat damage."
            play_guide = "Play Perfected Strike for 40-80 burst damage; duplicate with Dual Wield."
            focus = "Draft Pommel Strike, Twin Strike; do NOT remove basic Strikes; acquire defensive relics."
        elif len(deck) <= 12:
            archetype = "Act 1 Transition"
            win_con = "Use high-damage physical burst attacks to burst down enemies."
            play_guide = "Calculate lethal aggressively; avoid non-lethal skills against Gremlin Nob."
            focus = "Draft premium single-target physical attacks (Carnage, Cleave, Heavy Blade, Iron Wave)."

        if self.blackboard:
            self.blackboard.update_macro_memo(archetype, win_con, play_guide, focus)
        else:
            self._fallback_memo = f"【{archetype}】{win_con} 重点: {focus}"

    def decide_card_reward(
        self,
        deck: List[Card],
        relics: List[str],
        offered_cards: List[Card],
        can_skip: bool = True,
        floor: int = 0,
    ) -> BaseAction:
        """战后三选一选牌决策：大模型自主演化战略备忘并做出选牌选择"""
        if not offered_cards:
            return CancelAction.create()

        # 获取黑板上下文
        if self.blackboard:
            macro_context = self.blackboard.get_macro_context()
        else:
            macro_context = self.run_memo

        compressed = StateCompressor.compress_card_reward(deck, relics, offered_cards, can_skip)
        user_prompt = (
            f"=== STRATEGIC BLACKBOARD ===\n{macro_context}\n\n"
            f"{compressed}\n\n"
            "Considering your current deck and offered candidate cards, provide two outputs:\n"
            "1. In a ```memo code block, update your archetype direction and combat guidelines:\n"
            "```memo\n"
            "ARCHETYPE: <archetype name, e.g. High Strength / Barricade Defense / Exhaust Corruption / Transition>\n"
            "WIN_CON: <core win condition>\n"
            "PLAY_GUIDE: <combat play preferences and opening instructions>\n"
            "DRAFTING_FOCUS: <priorities for next card drafting or card removal>\n"
            "```\n"
            "2. In an ```action code block, output your card choice: CHOOSE <index> or CANCEL (to skip)."
        )

        self._ensure_room_messages(floor)
        prev_msg_len = len(self.messages)
        self.messages.append({"role": "user", "content": user_prompt})

        model_name = getattr(self.llm_client, "model", "")
        model_label = f" [{model_name}]" if model_name else ""
        card_names = [f"#{c.index} {c.name}" for c in offered_cards]
        if self.hud and hasattr(self.hud, "update_thinking"):
            self.hud.update_thinking(
                thought=f"甄选卡牌中... 候选牌: {', '.join(card_names)}",
                action="WAIT",
                status=f"第 {floor} 层 | 战后抓牌决策",
                badge=f"🃏 抓牌决策{model_label}",
                badge_color="#a55eea",
            )

        stage_desc = f"[宏观模型: {model_name}] 战后抓牌决策" if model_name else "战后抓牌决策"
        if self.llm_client.is_available:
            try:
                if self.profiler:
                    with self.profiler.span("llm_call", description=stage_desc):
                        res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                else:
                    res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                # 解析并更新模型自主生成的战略备忘录
                self._parse_memo(res)
                action = self._parse_action(res, offered_cards)
                if action:
                    self.messages.append({"role": "assistant", "content": res})
                    return action
            except Exception as e:
                logger.error(f"大模型选牌决策异常: {e}")

        # 回滚未成功的消息记录
        self.messages = self.messages[:prev_msg_len]

        # 模型未输出有效 memo 时，使用本地启发式智能兜底更新黑板
        self.update_run_memo_heuristic(deck, relics)

        # 启发式保底选牌：优先拿高伤害攻击牌
        attacks = [c for c in offered_cards if c.type == "ATTACK"]
        if attacks:
            best_atk = max(attacks, key=lambda c: c.damage)
            return ChooseAction.create(best_atk.index)
        return ChooseAction.create(0)

    def _parse_memo(self, text: str):
        """解析大模型生成的 ```memo 块并更新黑板"""
        if not text or not self.blackboard:
            return

        pattern = r"```memo\s*(.*?)\s*```"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            memo_block = match.group(1).strip()
            archetype = ""
            win_con = ""
            play_guide = ""
            drafting_focus = ""
            for line in memo_block.split("\n"):
                line = line.strip()
                if line.upper().startswith("ARCHETYPE:"):
                    archetype = line.split(":", 1)[1].strip()
                elif line.upper().startswith("WIN_CON:"):
                    win_con = line.split(":", 1)[1].strip()
                elif line.upper().startswith("PLAY_GUIDE:"):
                    play_guide = line.split(":", 1)[1].strip()
                elif line.upper().startswith("DRAFTING_FOCUS:"):
                    drafting_focus = line.split(":", 1)[1].strip()

            if archetype or win_con or play_guide or drafting_focus:
                self.blackboard.update_macro_memo(
                    archetype=archetype,
                    win_con=win_con,
                    play_guide=play_guide,
                    drafting_focus=drafting_focus,
                )

    def decide_map_route(
        self,
        current_hp: int,
        max_hp: int,
        gold: int,
        floor: int,
        act: int,
        next_nodes: List[Any],
        boss_available: bool = False,
    ) -> BaseAction:
        """地图路线导航决策"""
        if boss_available:
            return ChooseAction.create("boss")
        if not next_nodes or len(next_nodes) <= 1:
            return ChooseAction.create(0)

        compressed = StateCompressor.compress_map_selection(
            current_hp, max_hp, gold, floor, act, next_nodes, boss_available
        )
        user_prompt = (
            f"=== STRATEGIC RUN MEMO ===\n{self.run_memo}\n\n"
            f"{compressed}\n\n"
            "Considering current HP percentage and gold, evaluate risk vs. reward across available path branches. "
            "Provide a 1-sentence analysis, then output inside an ```action code block: CHOOSE <node_index>."
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        model_name = getattr(self.llm_client, "model", "")
        stage_desc = f"[宏观模型: {model_name}] 地图路径决策" if model_name else "地图路径决策"
        if self.llm_client.is_available:
            try:
                if self.profiler:
                    with self.profiler.span("llm_call", description=stage_desc):
                        res = self.llm_client.run_react_turn(messages, enable_tools=False)
                else:
                    res = self.llm_client.run_react_turn(messages, enable_tools=False)
                action = self._parse_action(res, next_nodes)
                if action:
                    return action
            except Exception as e:
                logger.error(f"大模型地图决策异常: {e}")

        # 启发式保底：血量低于 45% 时寻找火堆营地 (R)
        hp_ratio = current_hp / max_hp if max_hp > 0 else 1.0
        for idx, n in enumerate(next_nodes):
            sym = getattr(n, "symbol", n.get("symbol", "?") if isinstance(n, dict) else "?")
            if hp_ratio < 0.45 and sym == "R":
                return ChooseAction.create(idx)
        return ChooseAction.create(0)

    def _parse_action(self, text: str, candidates: List[Any]) -> Optional[BaseAction]:
        if not text:
            return None

        pattern = r"```action\s*(.*?)\s*```"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        action_line = match.group(1).strip() if match else ""

        if not action_line:
            for line in text.split("\n"):
                l = line.strip().upper()
                if l.startswith("CHOOSE") or l.startswith("CANCEL") or l.startswith("PROCEED"):
                    action_line = l
                    break

        if not action_line:
            return None

        parts = action_line.split()
        cmd = parts[0].upper()

        if cmd == "CANCEL":
            return CancelAction.create()
        if cmd == "PROCEED":
            return ProceedAction.create()
        if cmd == "CHOOSE" and len(parts) >= 2:
            return ChooseAction.create(parts[1])

        return None

    def decide_event(self, game_state: FullGameState) -> BaseAction:
        """
        事件决策：结合卡组、血量、金币与黑板战略，由大模型自主权衡选择。
        包含：
        1. 快速通过优化（0/1 个可用选项直接处理，不浪费 LLM Token）；
        2. 多轮 ReAct 纠错循环：若模型解析失败、选择了越界或禁用的选项，将错误回传模型重新思考；
        3. 多次重试耗尽后的安全保底（优先选离开/无害选项）。
        """
        screen_state = game_state.screen_state or {}
        event_id = screen_state.get("event_id", "Unknown Event")
        body_text = screen_state.get("body_text", "")
        options = screen_state.get("options", [])
        available_cmds = [str(c).lower() for c in game_state.available_commands]

        # 1. 提取所有未被禁用的选项索引
        enabled_indices = [
            idx for idx, opt in enumerate(options)
            if not opt.get("disabled", False)
        ]

        # 场景 A: 没有任何可用选项，但可 PROCEED / CONFIRM
        if not enabled_indices:
            if "proceed" in available_cmds:
                return ProceedAction.create()
            if "confirm" in available_cmds:
                return ConfirmAction.create()
            return ProceedAction.create()

        # 场景 B: 仅有 1 个可用选项（如单向剧情推进、纯确认、或者只剩离开按钮）
        if len(enabled_indices) == 1:
            chosen_idx = enabled_indices[0]
            opt_label = options[chosen_idx].get("label", "")
            logger.info(f"事件 [{event_id}] 仅有 1 个可用选项，自动快速选择 #{chosen_idx}: {opt_label}")
            return ChooseAction.create(chosen_idx)

        # 场景 C: 存在 2 个及以上可用选项，唤醒大模型进行权衡决策
        compressed = StateCompressor.compress_event(
            event_id=event_id,
            body_text=body_text,
            options=options,
            current_hp=game_state.current_hp,
            max_hp=game_state.max_hp,
            gold=game_state.gold,
            floor=game_state.floor,
            deck=game_state.deck,
            relics=game_state.relics,
        )

        user_prompt = (
            f"=== STRATEGIC RUN MEMO ===\n{self.run_memo}\n\n"
            f"{compressed}\n\n"
            "Considering current deck status, remaining HP, and gold, evaluate the risks and rewards of each option.\n"
            "Provide 1-2 sentences of analysis, then output your choice inside an ```action code block (must select an option marked AVAILABLE):\n"
            "```action\n"
            "CHOOSE <option_index>\n"
            "```"
        )

        self._ensure_room_messages(game_state.floor)
        prev_msg_len = len(self.messages)
        self.messages.append({"role": "user", "content": user_prompt})

        model_name = getattr(self.llm_client, "model", "")
        stage_desc = f"[宏观模型: {model_name}] 未知事件抉择" if model_name else "未知事件抉择"

        max_retries = 2
        for attempt in range(max_retries + 1):
            if not self.llm_client.is_available:
                break

            try:
                if self.profiler:
                    with self.profiler.span("llm_call", description=stage_desc):
                        res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                else:
                    res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                parsed_idx, thought = self._parse_event_action(res)

                # 校验解析结果：必须是合法索引且未被禁用
                if parsed_idx is not None:
                    if parsed_idx in enabled_indices:
                        chosen_label = options[parsed_idx].get("label", "")
                        logger.info(f"大模型决定事件 [{event_id}] 选择 #{parsed_idx}: {chosen_label}")
                        self.messages.append({"role": "assistant", "content": res})
                        if self.hud:
                            self.hud.update_thinking(
                                thought=thought or f"选择 #{parsed_idx}: {chosen_label}",
                                action=f"CHOOSE {parsed_idx}",
                                status=f"第 {game_state.floor} 层 | HP: {game_state.current_hp}/{game_state.max_hp} | 事件: {event_id}",
                                badge="📖 事件决策",
                                badge_color="#e056fd",
                            )
                        return ChooseAction.create(parsed_idx)
                    else:
                        error_msg = (
                            f"Command Execution Failed: The selected option index [{parsed_idx}] is DISABLED or out of range!\n"
                            f"Currently available option indices: {enabled_indices}.\n"
                            f"Please re-analyze available options and output a valid command, e.g. ```action\nCHOOSE {enabled_indices[0]}\n```"
                        )
                else:
                    error_msg = (
                        f"Command Syntax Error: Could not parse a valid ```action code block (e.g. CHOOSE <index>) from your output.\n"
                        f"Currently available option indices: {enabled_indices}.\n"
                        "Please re-think and strictly output inside an ```action\nCHOOSE <index>\n``` code block."
                    )

                logger.warning(f"大模型事件决策输出无效 (尝试 {attempt + 1}/{max_retries + 1}): {error_msg}")

                # 若还有重试机会，将错误回传大模型开启下一轮 ReAct 纠错
                if attempt < max_retries:
                    self.messages.append({"role": "assistant", "content": res})
                    self.messages.append({"role": "user", "content": error_msg})
                    continue

            except Exception as e:
                logger.error(f"大模型事件决策调用异常 (尝试 {attempt + 1}): {e}")
                if attempt < max_retries:
                    continue

        self.messages = self.messages[:prev_msg_len]

        # 多次尝试均失败，触发安全保底逻辑
        fallback_idx = self._safe_fallback_event_option(options, enabled_indices)
        fallback_label = options[fallback_idx].get("label", "")
        logger.warning(f"大模型决策重试耗尽或模型不可用，触发安全保底选择 #{fallback_idx}: {fallback_label}")
        if self.hud:
            self.hud.update_thinking(
                thought=f"决策重试耗尽，启用安全保底选择: {fallback_label}",
                action=f"CHOOSE {fallback_idx}",
                status=f"第 {game_state.floor} 层 | HP: {game_state.current_hp}/{game_state.max_hp} | 事件保底",
                badge="⚠️ 事件保底",
                badge_color="#ff4757",
            )
        return ChooseAction.create(fallback_idx)

    def _parse_event_action(self, text: str) -> Tuple[Optional[int], str]:
        """从模型回复中提取选择编号与思考内容"""
        if not text:
            return None, ""

        thought = ""
        pattern_action = r"```action\s*(.*?)\s*```"
        match = re.search(pattern_action, text, re.DOTALL | re.IGNORECASE)
        if match:
            action_line = match.group(1).strip()
            thought = text[:match.start()].strip()
        else:
            action_line = ""
            for line in text.split("\n"):
                l = line.strip().upper()
                if l.startswith("CHOOSE") or l.startswith("PROCEED"):
                    action_line = l
                    break
            thought = text.strip()

        thought_clean = " ".join(thought.split())[:150]

        parts = action_line.split()
        if len(parts) >= 2 and parts[0].upper() == "CHOOSE":
            try:
                idx = int(parts[1])
                return idx, thought_clean
            except ValueError:
                pass
        return None, thought_clean

    def _safe_fallback_event_option(self, options: List[Dict[str, Any]], enabled_indices: List[int]) -> int:
        """安全保底：优先寻找离开/放弃类选项，若无则取首个有效选项"""
        for idx in enabled_indices:
            lbl = options[idx].get("label", "").lower()
            if any(k in lbl for k in ["离开", "leave", "pass", "walk away", "ignore", "放弃"]):
                return idx
        return enabled_indices[0] if enabled_indices else 0

    def decide_shop(self, game_state: FullGameState) -> BaseAction:
        """
        商店消费决策：结合当前金币量、牌组厚度与黑板流派规划，
        由大模型自主在遗物、卡牌、药水与删牌服务间进行预算分配与购买。
        """
        screen_state = game_state.screen_state or {}
        cards = screen_state.get("cards", [])
        relics = screen_state.get("relics", [])
        potions = screen_state.get("potions", [])
        purge_available = screen_state.get("purge_available", False)
        purge_cost = screen_state.get("purge_cost", 75)
        gold = game_state.gold
        choice_list = [str(c).lower() for c in game_state.choice_list]

        # 检查药水空位
        potion_slots_open = sum(1 for p in game_state.potions if p.is_empty)
        if not game_state.potions:
            potion_slots_open = 2

        # 1. 安全熔断与快速通道：
        # 若连续购买次数 >= 5，或者身上金币买不起任何商品且无法删牌，直接离开
        affordable_relics = [r for r in relics if r.get("price", 999) <= gold]
        affordable_cards = [c for c in cards if c.get("price", 999) <= gold]
        affordable_potions = [p for p in potions if p.get("price", 999) <= gold and potion_slots_open > 0]
        can_purge = purge_available and gold >= purge_cost

        if self.shop_purchase_count >= 5 or (
            not affordable_relics and not affordable_cards and not affordable_potions and not can_purge
        ):
            logger.info("商店预算不足以购买任何物品或已达购买上限，选择离开商店。")
            if self.hud:
                self.hud.update_thinking(
                    thought="预算不足以购买剩余商品，理智离开商店。",
                    action="LEAVE",
                    status=f"第 {game_state.floor} 层 | 金币: {gold}G | 离开商店",
                    badge="🛒 商店离开",
                    badge_color="#70a1ff",
                )
            return LeaveAction.create()

        # 2. 状态压缩提炼
        compressed = StateCompressor.compress_shop(
            gold=gold,
            cards=cards,
            relics=relics,
            potions=potions,
            purge_available=purge_available,
            purge_cost=purge_cost,
            floor=game_state.floor,
            deck=game_state.deck,
            current_relics=game_state.relics,
            potion_slots_open=potion_slots_open,
        )

        user_prompt = (
            f"=== STRATEGIC RUN MEMO ===\n{self.run_memo}\n\n"
            f"{compressed}\n\n"
            "Evaluate current gold and deck deficiencies to decide which shop action to take:\n"
            "- BUY RELIC <index> (e.g. BUY RELIC 0)\n"
            "- BUY CARD <index> (e.g. BUY CARD 1)\n"
            "- BUY POTION <index> (e.g. BUY POTION 0)\n"
            "- PURGE (card removal service)\n"
            "- LEAVE (leave shop if remaining items are low value or unaffordable)\n\n"
            "Provide a 1-sentence evaluation and output inside an ```action code block:"
        )

        self._ensure_room_messages(game_state.floor)
        prev_msg_len = len(self.messages)
        self.messages.append({"role": "user", "content": user_prompt})

        model_name = getattr(self.llm_client, "model", "")
        stage_desc = f"[宏观模型: {model_name}] 商店消费决策" if model_name else "商店消费决策"

        max_retries = 2
        for attempt in range(max_retries + 1):
            if not self.llm_client.is_available:
                break

            try:
                if self.profiler:
                    with self.profiler.span("llm_call", description=stage_desc):
                        res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                else:
                    res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                action_type, target_idx, thought = self._parse_shop_action(res)

                if action_type == "LEAVE":
                    logger.info("大模型决定结束购物离开商店。")
                    self.messages.append({"role": "assistant", "content": res})
                    if self.hud:
                        self.hud.update_thinking(
                            thought=thought or "主动结束购物离开商店",
                            action="LEAVE",
                            status=f"第 {game_state.floor} 层 | 金币: {gold}G",
                            badge="🛒 商店离开",
                            badge_color="#70a1ff",
                        )
                    return LeaveAction.create()

                elif action_type == "PURGE":
                    if can_purge:
                        if "purge" in choice_list:
                            choice_idx = choice_list.index("purge")
                        else:
                            choice_idx = "purge"
                        self.shop_purchase_count += 1
                        logger.info(f"大模型决定购买删牌服务 (花费 {purge_cost}G)")
                        self.messages.append({"role": "assistant", "content": res})
                        if self.hud:
                            self.hud.update_thinking(
                                thought=thought or f"购买单次删牌服务 (花费 {purge_cost}G)",
                                action=f"PURGE",
                                status=f"第 {game_state.floor} 层 | 金币: {gold}G",
                                badge="✂️ 商店删牌",
                                badge_color="#ff4757",
                            )
                        return ChooseAction.create(choice_idx)
                    else:
                        error_msg = f"Command Execution Failed: Card removal service is unavailable (already used or requires {purge_cost}G, currently have {gold}G). Please choose another item or output LEAVE."

                elif action_type == "BUY_RELIC":
                    if target_idx is not None and 0 <= target_idx < len(relics):
                        target_relic = relics[target_idx]
                        price = target_relic.get("price", 999)
                        if gold >= price:
                            r_name = str(target_relic.get("name", target_relic.get("id", ""))).lower()
                            matched_idx = None
                            for c_idx, c_item in enumerate(choice_list):
                                if r_name in c_item or c_item in r_name:
                                     matched_idx = c_idx
                                     break
                            choice_arg = matched_idx if matched_idx is not None else target_relic.get("name", target_idx)
                            self.shop_purchase_count += 1
                            logger.info(f"大模型决定购买遗物 [{target_relic.get('name')}] (花费 {price}G)")
                            self.messages.append({"role": "assistant", "content": res})
                            if self.hud:
                                self.hud.update_thinking(
                                    thought=thought or f"购买遗物 {target_relic.get('name')} (花费 {price}G)",
                                    action=f"BUY RELIC {target_idx}",
                                    status=f"第 {game_state.floor} 层 | 金币: {gold}G",
                                    badge="💎 购买遗物",
                                    badge_color="#ffa502",
                                )
                            return ChooseAction.create(choice_arg)
                        else:
                            error_msg = f"Command Execution Failed: Relic [{target_relic.get('name')}] costs {price}G, but you only have {gold}G! Please choose another item or output LEAVE."
                    else:
                        error_msg = f"Command Execution Failed: Relic index [{target_idx}] out of range (valid range 0~{len(relics)-1}). Please choose again."

                elif action_type == "BUY_CARD":
                    if target_idx is not None and 0 <= target_idx < len(cards):
                        target_card = cards[target_idx]
                        price = target_card.get("price", 999)
                        if gold >= price:
                            c_name = str(target_card.get("name", target_card.get("id", ""))).lower()
                            matched_idx = None
                            for c_idx, c_item in enumerate(choice_list):
                                if c_name in c_item or c_item in c_name:
                                    matched_idx = c_idx
                                    break
                            choice_arg = matched_idx if matched_idx is not None else target_card.get("name", target_idx)
                            self.shop_purchase_count += 1
                            logger.info(f"大模型决定购买卡牌 [{target_card.get('name')}] (花费 {price}G)")
                            self.messages.append({"role": "assistant", "content": res})
                            if self.hud:
                                self.hud.update_thinking(
                                    thought=thought or f"购买卡牌 {target_card.get('name')} (花费 {price}G)",
                                    action=f"BUY CARD {target_idx}",
                                    status=f"第 {game_state.floor} 层 | 金币: {gold}G",
                                    badge="🃏 购买卡牌",
                                    badge_color="#2ed573",
                                )
                            return ChooseAction.create(choice_arg)
                        else:
                            error_msg = f"Command Execution Failed: Card [{target_card.get('name')}] costs {price}G, but you only have {gold}G! Please choose another item or output LEAVE."
                    else:
                        error_msg = f"Command Execution Failed: Card index [{target_idx}] out of range (valid range 0~{len(cards)-1}). Please choose again."

                elif action_type == "BUY_POTION":
                    if target_idx is not None and 0 <= target_idx < len(potions):
                        target_potion = potions[target_idx]
                        price = target_potion.get("price", 999)
                        if potion_slots_open <= 0:
                            error_msg = "Command Execution Failed: Potion slots are full! Please choose another item or output LEAVE."
                        elif gold < price:
                            error_msg = f"Command Execution Failed: Potion [{target_potion.get('name')}] costs {price}G, but you only have {gold}G! Please choose another item or output LEAVE."
                        else:
                            p_name = str(target_potion.get("name", target_potion.get("id", ""))).lower()
                            matched_idx = None
                            for c_idx, c_item in enumerate(choice_list):
                                if p_name in c_item or c_item in p_name:
                                    matched_idx = c_idx
                                    break
                            choice_arg = matched_idx if matched_idx is not None else target_potion.get("name", target_idx)
                            self.shop_purchase_count += 1
                            logger.info(f"大模型决定购买药水 [{target_potion.get('name')}] (花费 {price}G)")
                            self.messages.append({"role": "assistant", "content": res})
                            if self.hud:
                                self.hud.update_thinking(
                                    thought=thought or f"购买药水 {target_potion.get('name')} (花费 {price}G)",
                                    action=f"BUY POTION {target_idx}",
                                    status=f"第 {game_state.floor} 层 | 金币: {gold}G",
                                    badge="🧪 购买药水",
                                    badge_color="#1e90ff",
                                )
                            return ChooseAction.create(choice_arg)
                    else:
                        error_msg = f"Command Execution Failed: Potion index [{target_idx}] out of range (valid range 0~{len(potions)-1})."
                else:
                    error_msg = "Command Syntax Error: Please output a valid BUY RELIC <idx> / BUY CARD <idx> / BUY POTION <idx> / PURGE / LEAVE code block."

                logger.warning(f"大模型商店决策异常 (尝试 {attempt + 1}/{max_retries + 1}): {error_msg}")
                if attempt < max_retries:
                    self.messages.append({"role": "assistant", "content": res})
                    self.messages.append({"role": "user", "content": error_msg})
                    continue

            except Exception as e:
                logger.error(f"大模型商店调用异常: {e}")
                if attempt < max_retries:
                    continue

        self.messages = self.messages[:prev_msg_len]

        # 保底逻辑：优先删牌（如果可以），否则离开
        if can_purge and "purge" in choice_list:
            logger.info("商店决策保底：执行删牌服务。")
            self.shop_purchase_count += 1
            return ChooseAction.create(choice_list.index("purge"))
        return LeaveAction.create()

    def _parse_shop_action(self, text: str) -> Tuple[str, Optional[int], str]:
        """解析模型输出的商店购买指令"""
        if not text:
            return "LEAVE", None, ""

        thought = ""
        pattern = r"```action\s*(.*?)\s*```"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            action_line = match.group(1).strip()
            thought = text[:match.start()].strip()
        else:
            action_line = ""
            for line in text.split("\n"):
                l = line.strip().upper()
                if l.startswith("BUY") or l.startswith("PURGE") or l.startswith("LEAVE"):
                    action_line = l
                    break
            thought = text.strip()

        thought_clean = " ".join(thought.split())[:150]
        parts = action_line.split()
        if not parts:
            return "UNKNOWN", None, thought_clean

        cmd = parts[0].upper()
        if cmd == "LEAVE":
            return "LEAVE", None, thought_clean
        if cmd == "PURGE":
            return "PURGE", None, thought_clean

        if cmd == "BUY" and len(parts) >= 3:
            item_type = parts[1].upper()
            try:
                idx = int(parts[2])
                if item_type == "RELIC":
                    return "BUY_RELIC", idx, thought_clean
                elif item_type == "CARD":
                    return "BUY_CARD", idx, thought_clean
                elif item_type == "POTION":
                    return "BUY_POTION", idx, thought_clean
            except ValueError:
                pass

        return "UNKNOWN", None, thought_clean

    def decide_deck_purge_card(self, cards: List[Card], prompt: str = "") -> BaseAction:
        """
        非战斗卡组删牌决策（如商店删牌、问号事件删牌）：
        优先级：
        1. 致命诅咒牌 (Curse)
        2. 基础打击 (Strike)（若非完美打击流）
        3. 基础防御 (Defend)
        """
        if not cards:
            return ConfirmAction.create()

        # 1. 诅咒优先
        curse_names = {"pain", "regret", "doubt", "normality", "injury", "parasite", "decay", "writhe", "clumsy", "shame"}
        for c in cards:
            if c.type == "CURSE" or c.name.lower() in curse_names:
                logger.info(f"非战斗删牌：优先移除诅咒牌 [{c.name}] (索引 #{c.index})")
                if self.hud:
                    self.hud.update_thinking(
                        thought=f"优先净化卡组中的致命负面诅咒 [{c.name}]",
                        action=f"CHOOSE {c.index}",
                        status="卡组精简 | 移除诅咒",
                        badge="✂️ 诅咒净化",
                        badge_color="#ff4757",
                    )
                return ChooseAction.create(c.index)

        # 2. 检查是否为完美打击流 (Perfected Strike)
        is_perf_strike = "perfected strike" in self.run_memo.lower() or "完美打击" in self.run_memo

        if not is_perf_strike:
            # 常规流派：优先删除基础打击
            for c in cards:
                if "strike" in c.id.lower() or c.name.lower() in ["strike", "打击"]:
                    logger.info(f"非战斗删牌：移除基础打击 [{c.name}] (索引 #{c.index})")
                    if self.hud:
                        self.hud.update_thinking(
                            thought=f"精简卡组，提高核心单卡流转率：移除基础打击 [{c.name}]",
                            action=f"CHOOSE {c.index}",
                            status="卡组精简 | 移除打击",
                            badge="✂️ 牌组精简",
                            badge_color="#e056fd",
                        )
                    return ChooseAction.create(c.index)

        # 3. 完美打击流或已无打击：移除基础防御
        for c in cards:
            if "defend" in c.id.lower() or c.name.lower() in ["defend", "防御"]:
                logger.info(f"非战斗删牌：移除基础防御 [{c.name}] (索引 #{c.index})")
                if self.hud:
                    self.hud.update_thinking(
                        thought=f"精简卡组：移除基础防御 [{c.name}]",
                        action=f"CHOOSE {c.index}",
                        status="卡组精简 | 移除防御",
                        badge="✂️ 牌组精简",
                        badge_color="#e056fd",
                    )
                return ChooseAction.create(c.index)

        # 兜底选择第一张
        return ChooseAction.create(0)

    def decide_rest(self, game_state: FullGameState) -> BaseAction:
        """
        营地/篝火动作决策 (REST, SMITH, DIG, LIFT, TOKE, RECALL)：
        由大模型结合当前战略流派、血量安全线、特殊遗物能力进行全局评估。
        """
        options = [str(opt).upper() for opt in game_state.screen_state.get("rest_options", [])]
        has_rested = game_state.screen_state.get("has_rested", False)
        if has_rested or not options:
            return ProceedAction.create()

        # 极简单选项直通 (0-token 快速通过)
        if len(options) == 1:
            logger.info(f"营地仅有单选项 [{options[0]}]，执行直通。")
            return ChooseAction.create(options[0].lower())

        hp_ratio = game_state.current_hp / game_state.max_hp if game_state.max_hp > 0 else 1.0

        compressed = StateCompressor.compress_rest(
            current_hp=game_state.current_hp,
            max_hp=game_state.max_hp,
            floor=game_state.floor,
            act=game_state.act,
            rest_options=options,
            deck=game_state.deck,
            relics=game_state.relics,
        )

        user_prompt = (
            f"=== STRATEGIC RUN MEMO ===\n{self.run_memo}\n\n"
            f"{compressed}\n\n"
            "Evaluate HP safety margin and deck scaling needs to decide whether to heal (REST), upgrade (SMITH), or use special relic actions (DIG/LIFT/TOKE/RECALL).\n"
            "Provide a 1-sentence strategic rationale, then output inside an ```action code block: CHOOSE <option_name_or_index> (e.g. CHOOSE smith or CHOOSE rest or CHOOSE dig)."
        )

        self._ensure_room_messages(game_state.floor)
        prev_msg_len = len(self.messages)
        self.messages.append({"role": "user", "content": user_prompt})

        model_name = getattr(self.llm_client, "model", "")
        stage_desc = f"[宏观模型: {model_name}] 营地战略决策" if model_name else "营地战略决策"

        if self.llm_client.is_available:
            for retry in range(2):
                try:
                    if self.profiler:
                        with self.profiler.span("llm_call", description=stage_desc):
                            res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                    else:
                        res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                    pattern = r"```action\s*CHOOSE\s+([a-zA-Z0-9_]+)\s*```"
                    match = re.search(pattern, res, re.IGNORECASE)
                    if match:
                        token = match.group(1).upper()
                        target_opt = None
                        if token in options:
                            target_opt = token.lower()
                        elif token.isdigit():
                            idx = int(token)
                            if 0 <= idx < len(options):
                                target_opt = options[idx].lower()

                        if target_opt:
                            logger.info(f"大模型营地决策: {target_opt}")
                            self.messages.append({"role": "assistant", "content": res})
                            if self.hud:
                                self.hud.update_thinking(
                                    thought=f"营地战略决策: {target_opt}",
                                    action=f"CHOOSE {target_opt}",
                                    status=f"第 {game_state.floor} 层 | HP: {game_state.current_hp}/{game_state.max_hp}",
                                    badge="🔥 营地休整",
                                    badge_color="#ffa502",
                                )
                            return ChooseAction.create(target_opt)

                    # 指令未能识别，进行自愈修正
                    feedback = (
                        f"Command Syntax Error: Could not find a valid option among available campfire choices.\n"
                        f"Currently available options: {', '.join(options)}.\n"
                        f"Please re-output inside an ```action\nCHOOSE <option_name>\n``` block (e.g.: CHOOSE {options[0].lower()})."
                    )
                    self.messages.append({"role": "assistant", "content": res})
                    self.messages.append({"role": "user", "content": feedback})
                except Exception as e:
                    logger.error(f"大模型营地决策异常: {e}")
                    break

        self.messages = self.messages[:prev_msg_len]

        # 启发式保底机制
        logger.info("采用营地启发式规则保底决策。")
        # 1. 血量低于 45% 且可休息，优先 REST 保命
        if hp_ratio < 0.45 and "REST" in options:
            action = ChooseAction.create("rest")
        # 2. 如果有铲子挖宝 (DIG) 且血量健康 (>= 75%)，贪遗物
        elif hp_ratio >= 0.75 and "DIG" in options:
            action = ChooseAction.create("dig")
        # 3. 如果有吉拉举铁 (LIFT) 且血量健康 (>= 70%)，贪力量
        elif hp_ratio >= 0.70 and "LIFT" in options:
            action = ChooseAction.create("lift")
        # 4. 优先 SMITH
        elif "SMITH" in options:
            action = ChooseAction.create("smith")
        # 5. 再次退化为 REST
        elif "REST" in options:
            action = ChooseAction.create("rest")
        else:
            action = ChooseAction.create(options[0].lower())

        if self.hud:
            self.hud.update_thinking(
                thought=f"启发式营地保底: {action.raw_command}",
                action=action.raw_command,
                status=f"第 {game_state.floor} 层 | HP: {game_state.current_hp}/{game_state.max_hp}",
                badge="🔥 营地休整",
                badge_color="#ffa502",
            )
        return action

    def decide_smith_card(self, cards: List[Card], prompt: str = "", floor: int = 0) -> BaseAction:
        """
        锻造卡牌选择决策：
        由大模型结合当前战略流派，评估哪张未升级卡牌质变最大。
        """
        if not cards:
            return ConfirmAction.create()
        if len(cards) == 1:
            return ChooseAction.create(0)

        card_lines = []
        for idx, c in enumerate(cards):
            effs = []
            if c.damage > 0:
                effs.append(f"{c.damage} dmg")
            if c.block > 0:
                effs.append(f"{c.block} blk")
            if c.description:
                effs.append(c.description)
            eff_desc = ", ".join(effs) if effs else "Standard"
            card_lines.append(f"* [{idx}] {c.name} ({c.cost}E, {c.type}) -> {eff_desc}")

        cards_str = "\n".join(card_lines)
        user_prompt = (
            f"=== STRATEGIC RUN MEMO ===\n{self.run_memo}\n\n"
            f"=== CAMPFIRE SMITHING (CARD UPGRADE SELECTION) ===\n"
            f"Game Objective: {prompt or 'Select a card to upgrade'}\n\n"
            f"UPGRADE CANDIDATES:\n{cards_str}\n\n"
            "Evaluate which card upgrade provides the greatest scaling and power boost for your archetype:\n"
            "- Prioritize core scaling Powers (e.g. Demon Form, Inflame, Spot Weakness, Barricade);\n"
            "- Prioritize key Vulnerable/energy/card draw upgrades (e.g. Bash extending Vulnerable to 3 turns, Shockwave, Battle Trance, Offering);\n"
            "- Core attack damage staples (e.g. Whirlwind, Heavy Blade, Carnage, Perfected Strike);\n"
            "- Avoid premature upgrades to basic Strike/Defend unless no other viable options exist.\n"
            "Provide a 1-sentence rationale, then output inside an ```action code block: CHOOSE <index>."
        )

        self._ensure_room_messages(floor)
        prev_msg_len = len(self.messages)
        self.messages.append({"role": "user", "content": user_prompt})

        model_name = getattr(self.llm_client, "model", "")
        stage_desc = f"[宏观模型: {model_name}] 锻造升级卡牌" if model_name else "锻造升级卡牌"

        if self.llm_client.is_available:
            for retry in range(2):
                try:
                    if self.profiler:
                        with self.profiler.span("llm_call", description=stage_desc):
                            res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                    else:
                        res = self.llm_client.run_react_turn(self.messages, enable_tools=False)
                    pattern = r"```action\s*CHOOSE\s+(\d+)\s*```"
                    match = re.search(pattern, res, re.IGNORECASE)
                    if match:
                        chosen_idx = int(match.group(1))
                        if 0 <= chosen_idx < len(cards):
                            logger.info(f"大模型自主选择锻造升级卡牌 (索引 #{chosen_idx}): {cards[chosen_idx].name}")
                            self.messages.append({"role": "assistant", "content": res})
                            if self.hud:
                                self.hud.update_thinking(
                                    thought=f"锻造升级核心卡牌: [{cards[chosen_idx].name}]",
                                    action=f"CHOOSE {chosen_idx}",
                                    status=f"锻造质变 | {cards[chosen_idx].name}",
                                    badge="🔨 锻造升级",
                                    badge_color="#2ed573",
                                )
                            return ChooseAction.create(chosen_idx)

                    # 格式反馈修正
                    feedback = (
                        f"Command Syntax Error: Could not find a valid card index in candidates.\n"
                        f"Valid card index range: 0 to {len(cards) - 1}.\n"
                        f"Please re-output inside an ```action\nCHOOSE <index>\n``` block."
                    )
                    self.messages.append({"role": "assistant", "content": res})
                    self.messages.append({"role": "user", "content": feedback})
                except Exception as e:
                    logger.error(f"大模型锻造选卡异常: {e}")
                    break

        self.messages = self.messages[:prev_msg_len]

        # 启发式保底升级评分机制
        chosen = self._heuristic_smith_card_fallback(cards)
        logger.info(f"采用启发式规则升级卡牌: [{chosen.name}] (索引 #{chosen.index})")
        if self.hud:
            self.hud.update_thinking(
                thought=f"启发式升级关键牌: [{chosen.name}]",
                action=f"CHOOSE {chosen.index}",
                status=f"锻造质变 | {chosen.name}",
                badge="🔨 锻造升级",
                badge_color="#2ed573",
            )
        return ChooseAction.create(chosen.index)

    def _heuristic_smith_card_fallback(self, cards: List[Card]) -> Card:
        """
        启发式锻造卡牌评分选择器：
        避免将宝贵的升级机会浪费在基础 Strike/Defend 上。
        """
        high_priority_names = {
            "demon form", "inflame", "spot weakness", "limit break", "barricade",
            "feel no pain", "dark embrace", "corruption", "rupture", "brutality",
            "bash", "uppercut", "shockwave", "whirlwind", "immolate", "carnage",
            "offering", "battle trance", "armaments", "body slam", "heavy blade",
            "perfected strike", "flame barrier", "power through"
        }

        def score_card(c: Card) -> int:
            name_lower = c.name.lower()
            if name_lower in high_priority_names:
                return 100
            if c.type == "POWER":
                return 80
            if c.type in ["ATTACK", "SKILL"] and name_lower not in ["strike", "defend", "打击", "防御"]:
                return 50
            if name_lower in ["defend", "防御"]:
                return 20
            if name_lower in ["strike", "打击"]:
                return 10
            return 0

        best_card = max(cards, key=score_card)
        return best_card



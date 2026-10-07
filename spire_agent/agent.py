import os
import logging
from typing import Optional, Dict, Any, List

from .models import (
    CombatState,
    FullGameState,
    BaseAction,
    PlayCardAction,
    EndTurnAction,
    UsePotionAction,
    ChooseAction,
    ProceedAction,
    CancelAction,
    ConfirmAction,
    LeaveAction,
    ReturnAction,
    SkipAction,
    TurnPlan,
    Card,
    Monster,
)
from .combat_session import CombatSession
from .macro_session import MacroSession
from .blackboard import RunBlackboard
from .hud import DummyHud, SpireHud
from .profiler import StepProfiler
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from llm_client import SpireLLMClient

logger = logging.getLogger("spire_agent")


class SpireAgent:
    """
    基于大语言模型 (DeepSeek / Kimi / Gemini) 与双层规划会话的《杀戮尖塔》智能 Agent
    - MacroSession: 长期宏观规划 (选牌、商店删牌、路线风险平衡)
    - CombatSession: 短期回合连击规划 (工具试算、怪物禁忌对策，单场战斗后即刻清空)
    - RunBlackboard: 跨会话战略黑板 (共享战术锦囊与战后反思，实时落盘 run_memo.md)
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        enable_tools: bool = True,
        enable_calculator: bool = True,
        hud: Optional[Any] = None,
        profiler: Optional[Any] = None,
        macro_provider: Optional[str] = None,
        macro_api_key: Optional[str] = None,
        macro_base_url: Optional[str] = None,
        macro_model: Optional[str] = None,
        macro_temperature: Optional[float] = None,
        combat_llm_client: Optional[SpireLLMClient] = None,
        macro_llm_client: Optional[SpireLLMClient] = None,
    ):
        self.hud = hud or DummyHud()
        self.profiler = profiler or StepProfiler(hud=self.hud)
        self.enable_tools = enable_tools
        self.enable_calculator = enable_calculator

        from llm_client import SpireLLMClient

        # 1. 战斗微观战术客户端 (Combat Client)
        self.combat_llm_client = combat_llm_client or SpireLLMClient(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            enable_tools=enable_tools,
            enable_calculator=enable_calculator,
            config_prefix="LLM",
        )
        self.llm_client = self.combat_llm_client  # 保持旧属性兼容

        # 2. 宏观长线战略客户端 (Macro Client，KV Cache 物理隔离，支持异构模型)
        self.macro_llm_client = macro_llm_client or SpireLLMClient(
            provider=macro_provider,
            api_key=macro_api_key,
            base_url=macro_base_url,
            model=macro_model,
            temperature=macro_temperature,
            enable_tools=False,
            enable_calculator=False,
            config_prefix="MACRO_LLM",
        )

        self.blackboard = RunBlackboard(hud=self.hud)
        self.combat_session = CombatSession(
            self.combat_llm_client,
            enable_tools=enable_tools,
            enable_calculator=enable_calculator,
            blackboard=self.blackboard,
            profiler=self.profiler,
        )
        self.macro_session = MacroSession(
            self.macro_llm_client,
            blackboard=self.blackboard,
            hud=self.hud,
            profiler=self.profiler,
        )

        self.current_floor = 0
        self.skipped_cards = False
        self.skipped_potions = False
        self.visited_shop = False
        self.shop_purged = 0
        self.pending_campfire_smith = False
        self.last_played_card: Optional[Card] = None

    def plan_combat_turn(self, state: CombatState) -> TurnPlan:
        """回合连击方案规划入口"""
        plan = self.combat_session.plan_turn(state, run_memo=self.macro_session.run_memo)

        # 在 HUD 上直观展示 AI 推演出的连招
        action_names = []
        hand_map = {c.index: c.name for c in state.hand}
        for act in plan.actions:
            if isinstance(act, PlayCardAction):
                cname = hand_map.get(act.card_index, f"c{act.card_index}")
                tgt = f"->E{act.target_index}" if act.target_index is not None else ""
                action_names.append(f"{cname}{tgt}")
            elif isinstance(act, EndTurnAction):
                action_names.append("结束回合")

        self.hud.update_thinking(
            thought=plan.reasoning or "推演完毕，执行战术连击。",
            action=" ➔ ".join(action_names),
            status=f"回合 {state.turn} | HP: {state.player.current_hp}/{state.player.max_hp} | 能量: {state.player.energy}",
            badge="⚡ 回合战术连击",
            badge_color="#ff4757",
        )
        return plan

    def on_combat_end(self, game_state: Optional[FullGameState] = None):
        """当战斗胜利结束时由主循环调用：生成实战复盘反思写入黑板，清空战斗临时会话内存"""
        self.last_played_card = None
        final_hp = game_state.current_hp if game_state else 0
        max_hp = game_state.max_hp if game_state else 80
        floor = game_state.floor if game_state else self.current_floor
        self.combat_session.on_combat_end(final_hp=final_hp, max_hp=max_hp, floor=floor)

    def decide_screen_action(self, game_state: FullGameState) -> BaseAction:
        """非战斗界面（战利品结算、选牌、地图、营地、商店等）的统一决策派发"""
        st = game_state.screen_type.upper()
        if game_state.floor != self.current_floor:
            self.current_floor = game_state.floor
            self.skipped_cards = False
            self.skipped_potions = False
            self.visited_shop = False
            self.shop_purged = 0
            self.pending_campfire_smith = False
            self.macro_session.reset_room_context()

        logger.info(f"处理非战斗界面: [{st}] (第 {game_state.floor} 层)")

        if st == "COMBAT_REWARD":
            raw_rewards = game_state.screen_state.get("rewards", [])
            if not raw_rewards:
                self.skipped_cards = False
                self.skipped_potions = False
                return ProceedAction.create()

            # 1. 自动拾取金币、遗物与钥匙
            for idx, r in enumerate(raw_rewards):
                rtype = str(r.get("reward_type", "")).upper()
                if rtype in ["GOLD", "STOLEN_GOLD", "RELIC", "SAPPHIRE_KEY", "EMERALD_KEY"]:
                    logger.info(f"自动拾取战利品 (索引 #{idx}): {rtype}")
                    return ChooseAction.create(idx)

            # 2. 拾取药水（必须有空位）
            has_empty_slot = any(p.is_empty for p in game_state.potions) or len(game_state.potions) < 2
            for idx, r in enumerate(raw_rewards):
                rtype = str(r.get("reward_type", "")).upper()
                if rtype == "POTION":
                    if has_empty_slot and not self.skipped_potions:
                        self.skipped_potions = True
                        return ChooseAction.create(idx)

            # 3. 点击卡牌奖励进入选牌界面
            for idx, r in enumerate(raw_rewards):
                rtype = str(r.get("reward_type", "")).upper()
                if rtype == "CARD":
                    if self.skipped_cards:
                        continue
                    return ChooseAction.create(idx)

            self.skipped_cards = False
            self.skipped_potions = False
            return ProceedAction.create()

        elif st == "CARD_REWARD":
            raw_cards = game_state.screen_state.get("cards", [])
            offered: List[Card] = []
            for idx, c in enumerate(raw_cards):
                offered.append(
                    Card(
                        index=idx,
                        id=c.get("id", ""),
                        name=c.get("name", f"Card_{idx}"),
                        cost=c.get("cost", 1),
                        type=c.get("type", "SKILL"),
                        damage=c.get("damage", 0),
                        block=c.get("block", 0),
                        description=c.get("raw_description", ""),
                    )
                )
            can_skip = game_state.screen_state.get("skip_available", True)
            action = self.macro_session.decide_card_reward(
                game_state.deck, game_state.relics, offered, can_skip, floor=game_state.floor
            )
            if isinstance(action, CancelAction):
                self.skipped_cards = True

            card_names = [f"#{c.index} {c.name}" for c in offered]
            self.hud.update_thinking(
                thought=f"根据战略黑板流派规划甄选卡牌。候选: {', '.join(card_names)}",
                action=action.raw_command,
                status=f"第 {game_state.floor} 层 | HP: {game_state.current_hp}/{game_state.max_hp} | 战利品选牌",
                badge="🃏 抓牌决策",
                badge_color="#2ed573",
            )
            return action

        elif st == "MAP":
            self.skipped_cards = False
            self.skipped_potions = False
            next_nodes = game_state.screen_state.get("next_nodes", [])
            boss_available = game_state.screen_state.get("boss_available", False)
            action = self.macro_session.decide_map_route(
                current_hp=game_state.current_hp,
                max_hp=game_state.max_hp,
                gold=game_state.gold,
                floor=game_state.floor,
                act=game_state.act,
                next_nodes=next_nodes,
                boss_available=boss_available,
            )
            self.hud.update_thinking(
                thought="根据当前血量健康度与避险/猎杀策略选择前进路线。",
                action=action.raw_command,
                status=f"第 {game_state.floor} 层 | HP: {game_state.current_hp}/{game_state.max_hp} | 金币: {game_state.gold}",
                badge="🗺️ 路线规划",
                badge_color="#00f0ff",
            )
            return action

        elif st == "SHOP_ROOM":
            if not self.visited_shop and "choose" in game_state.available_commands:
                self.macro_session.shop_purchase_count = 0
                return ChooseAction.create(0)
            if "proceed" in game_state.available_commands:
                self.visited_shop = False
                return ProceedAction.create()
            return ProceedAction.create()

        elif st == "SHOP_SCREEN":
            self.visited_shop = True
            return self.macro_session.decide_shop(game_state)

        elif st == "REST":
            action = self.macro_session.decide_rest(game_state)
            if isinstance(action, ChooseAction) and "smith" in str(action.choice).lower():
                self.pending_campfire_smith = True
            return action

        elif st in ["HAND_SELECT", "GRID"]:
            # CommunicationMod 对 HAND_SELECT 放置于 "hand" 字段，对 GRID 放置于 "cards" 字段
            raw_cards = game_state.screen_state.get("hand") or game_state.screen_state.get("cards") or []
            if not raw_cards and game_state.combat_state and game_state.combat_state.hand and st == "HAND_SELECT":
                # 容错兜底：若 CommunicationMod 未在 screen_state 序列化 hand，取当前战斗手牌
                raw_cards = [
                    {
                        "name": c.name,
                        "id": c.id,
                        "cost": c.cost,
                        "type": c.type,
                        "damage": c.damage,
                        "block": c.block,
                        "raw_description": c.description,
                        "upgrades": 1 if c.upgraded else 0,
                    }
                    for c in game_state.combat_state.hand
                ]

            prompt = game_state.screen_state.get("prompt", "")
            if not prompt and self.last_played_card:
                action_hint = "Upgrade" if ("armaments" in self.last_played_card.name.lower() or "武装" in self.last_played_card.name) else "Select"
                prompt = f"{action_hint} a card (Triggered by playing [{self.last_played_card.name}]: {self.last_played_card.description or ''})"
            elif not prompt:
                if game_state.screen_state.get("for_upgrade", False):
                    prompt = "Select a card to upgrade"
                elif game_state.screen_state.get("for_purge", False):
                    prompt = "Select a card to purge/remove"
                elif game_state.screen_state.get("for_transform", False):
                    prompt = "Select a card to transform"
                else:
                    prompt = "Select a card"

            can_confirm = game_state.screen_state.get("can_confirm", False) or "confirm" in game_state.available_commands

            if raw_cards and "choose" in game_state.available_commands:
                selectable_cards = []
                for idx, c in enumerate(raw_cards):
                    selectable_cards.append(
                        Card(
                            index=idx,
                            id=c.get("id", ""),
                            name=c.get("name", f"Card_{idx}"),
                            cost=c.get("cost", 0),
                            type=c.get("type", "SKILL"),
                            damage=c.get("damage", 0),
                            block=c.get("block", 0),
                            description=c.get("raw_description", c.get("description", "")),
                            upgraded=c.get("upgrades", 0) > 0,
                        )
                    )
                # 若当前处于非战斗阶段：根据 CommunicationMod 原生标识、pending 状态以及 prompt 综合判断升级或删牌
                if not game_state.in_combat and (game_state.combat_state is None or not game_state.combat_state.hand):
                    for_upgrade = bool(game_state.screen_state.get("for_upgrade", False))
                    p_lower = prompt.lower()
                    is_upgrade = (
                        for_upgrade
                        or self.pending_campfire_smith
                        or any(kw in p_lower for kw in ["upgrade", "smith", "forg", "升级", "锻造"])
                    )
                    self.pending_campfire_smith = False
                    if is_upgrade:
                        return self.macro_session.decide_smith_card(selectable_cards, prompt=prompt, floor=game_state.floor)
                    else:
                        return self.macro_session.decide_deck_purge_card(selectable_cards, prompt=prompt)

                action = self.combat_session.decide_in_combat_card_selection(
                    screen_type=st,
                    prompt=prompt,
                    cards=selectable_cards,
                    can_confirm=can_confirm,
                )
                choice_raw = getattr(action, "choice", "")
                choice_idx = int(choice_raw) if str(choice_raw).isdigit() else -1
                card_name = (
                    selectable_cards[choice_idx].name
                    if 0 <= choice_idx < len(selectable_cards)
                    else str(choice_raw)
                )
                self.hud.update_thinking(
                    thought=f"战斗内选卡决策 ({prompt}): 选择 [{card_name}]",
                    action=action.raw_command,
                    status=f"第 {game_state.floor} 层 | 战斗选卡: {st}",
                    badge="⚔️ 战斗选卡",
                    badge_color="#ffa502",
                )
                return action

            # 指令降级与安全兜底：绝不盲目发送不在 available_commands 中的指令
            if "confirm" in game_state.available_commands:
                return ConfirmAction.create()
            if "proceed" in game_state.available_commands:
                return ProceedAction.create()
            if "choose" in game_state.available_commands:
                return ChooseAction.create(0)
            if "cancel" in game_state.available_commands:
                return CancelAction.create()
            return ChooseAction.create(0)

        elif st == "CHEST":
            if game_state.screen_state.get("chest_open", False):
                return ProceedAction.create()
            return ChooseAction.create("open")

        elif st == "EVENT":
            return self.macro_session.decide_event(game_state)

        elif st == "BOSS_REWARD":
            if "choose" in game_state.available_commands:
                return ChooseAction.create(0)
            return ProceedAction.create()

        elif st == "GAME_OVER":
            if "proceed" in game_state.available_commands:
                return ProceedAction.create()
            return ConfirmAction.create()

        # 兜底指令
        if "confirm" in game_state.available_commands:
            return ConfirmAction.create()
        if "proceed" in game_state.available_commands:
            return ProceedAction.create()
        if "choose" in game_state.available_commands:
            return ChooseAction.create(0)
        return ProceedAction.create()

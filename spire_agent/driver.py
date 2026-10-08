import sys
import time
import json
import logging
import socket
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from .models import (
    CombatState,
    FullGameState,
    Player,
    Monster,
    Card,
    Power,
    Potion,
    BaseAction,
    PlayCardAction,
    EndTurnAction,
    ChooseAction,
    ProceedAction,
    CancelAction,
)

logger = logging.getLogger("spire_agent.driver")


class BaseGameDriver(ABC):
    """游戏驱动基础抽象接口"""

    @abstractmethod
    def get_full_state(self) -> Optional[FullGameState]:
        """获取当前全局游戏状态帧"""
        pass

    @abstractmethod
    def send_full_action(self, action: BaseAction) -> Optional[FullGameState]:
        """发送动作并获取更新后的全局状态帧"""
        pass

    @abstractmethod
    def is_game_over(self) -> bool:
        """全局游戏或通信是否彻底结束"""
        pass

    def get_current_state(self) -> Optional[CombatState]:
        full = self.get_full_state()
        return full.combat_state if full else None

    def send_action(self, action: BaseAction) -> Optional[CombatState]:
        full = self.send_full_action(action)
        return full.combat_state if full else None

    def is_combat_over(self) -> bool:
        full = self.get_full_state()
        if not full:
            return True
        return not full.in_combat


class MockGameDriver(BaseGameDriver):
    """
    本地沙盒模拟驱动：
    模拟完整生命周期：战斗中 -> 战利品结算 -> 选牌 -> 大地图路线选择。
    """

    def __init__(self, scenario: str = "cultist"):
        self.scenario = scenario
        self.combat_over = False
        self.game_finished = False
        self.phase = "combat"
        self.combat_state = self._init_scenario(scenario)
        self.gold = 99
        self.deck = [
            Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=1, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=2, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=3, id="Defend_R", name="Defend", cost=1, type="SKILL", block=5),
            Card(index=4, id="Defend_R", name="Defend", cost=1, type="SKILL", block=5),
            Card(index=5, id="Bash", name="Bash", cost=2, type="ATTACK", damage=8),
        ]
        self.relics = ["Burning Blood"]
        self.potions: List[Potion] = []
        self.screen_rewards = [{"reward_type": "GOLD", "gold": 18}, {"reward_type": "CARD"}]

    def _init_scenario(self, scenario: str) -> CombatState:
        if scenario == "lethal":
            p = Player(current_hp=50, max_hp=80, energy=3, block=0, powers=[Power(id="Strength", name="Strength", amount=2)])
            m = Monster(index=0, id="Gremlin", name="Fat Gremlin", current_hp=15, max_hp=30, block=0, intent="ATTACK", move_damage=12, move_hits=1)
            cards = [
                Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=8),
                Card(index=1, id="Bash", name="Bash", cost=2, type="ATTACK", target_type="ENEMY", damage=10, description="Deal 10 damage. Apply 2 Vulnerable."),
                Card(index=2, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
            ]
            return CombatState(
                turn=2,
                player=p,
                monsters=[m],
                hand=cards,
                draw_pile=["Strike", "Defend", "Strike"],
                discard_pile=["Defend", "Strike"],
                draw_pile_count=10,
                discard_pile_count=5,
            )

        elif scenario == "gremlin_nob":
            p = Player(current_hp=65, max_hp=80, energy=3, block=0)
            m = Monster(index=0, id="GremlinNob", name="Gremlin Nob", current_hp=52, max_hp=86, block=0, intent="ATTACK", move_damage=14, move_hits=1)
            cards = [
                Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=6),
                Card(index=1, id="Bash", name="Bash", cost=2, type="ATTACK", target_type="ENEMY", damage=8, description="Deal 8 damage. Apply 2 Vulnerable."),
                Card(index=2, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
                Card(index=3, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
            ]
            return CombatState(
                turn=1,
                player=p,
                monsters=[m],
                hand=cards,
                draw_pile=["Strike", "Strike", "Defend", "Defend"],
                discard_pile=[],
                draw_pile_count=12,
                discard_pile_count=0,
            )

        elif scenario == "danger":
            p = Player(current_hp=20, max_hp=80, energy=3, block=0)
            m = Monster(index=0, id="JawWorm", name="Jaw Worm", current_hp=40, max_hp=42, block=0, intent="ATTACK", move_damage=17, move_hits=1)
            cards = [
                Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=6),
                Card(index=1, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
                Card(index=2, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
                Card(index=3, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
            ]
            return CombatState(
                turn=3,
                player=p,
                monsters=[m],
                hand=cards,
                draw_pile=["Strike", "Defend"],
                discard_pile=["Strike", "Defend"],
                draw_pile_count=6,
                discard_pile_count=8,
            )

        # 默认：邪教徒对攻
        p = Player(current_hp=70, max_hp=80, energy=3, block=0)
        m = Monster(
            index=0,
            id="Cultist",
            name="Cultist",
            current_hp=48,
            max_hp=48,
            block=0,
            intent="ATTACK",
            move_damage=6,
            move_hits=1,
            powers=[Power(id="Ritual", name="Ritual", amount=3)],
        )
        cards = [
            Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=6),
            Card(index=1, id="Bash", name="Bash", cost=2, type="ATTACK", target_type="ENEMY", damage=8, description="Deal 8 damage. Apply 2 Vulnerable."),
            Card(index=2, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
            Card(index=3, id="Flex", name="Flex", cost=0, type="SKILL", target_type="SELF", description="Gain 2 Strength. Lose 2 Strength at end of turn."),
        ]
        return CombatState(
            turn=1,
            player=p,
            monsters=[m],
            hand=cards,
            draw_pile=["Strike", "Strike", "Defend", "Carnage"],
            discard_pile=[],
            draw_pile_count=10,
            discard_pile_count=0,
        )

    def is_game_over(self) -> bool:
        return self.game_finished

    def get_full_state(self) -> Optional[FullGameState]:
        if self.game_finished:
            return None

        if self.phase == "combat":
            return FullGameState(
                screen_type="NONE",
                floor=1,
                act=1,
                gold=self.gold,
                current_hp=self.combat_state.player.current_hp,
                max_hp=self.combat_state.player.max_hp,
                deck=self.deck,
                relics=self.relics,
                potions=self.potions,
                combat_state=self.combat_state,
                is_screen_up=False,
                available_commands=["play", "end"],
            )
        elif self.phase == "reward":
            return FullGameState(
                screen_type="COMBAT_REWARD",
                screen_state={"rewards": self.screen_rewards},
                floor=1,
                act=1,
                gold=self.gold,
                current_hp=self.combat_state.player.current_hp,
                max_hp=self.combat_state.player.max_hp,
                deck=self.deck,
                relics=self.relics,
                potions=self.potions,
                is_screen_up=True,
                available_commands=["choose", "proceed"],
            )
        elif self.phase == "card_reward":
            offered = [
                {"id": "Carnage", "name": "Carnage", "cost": 2, "type": "ATTACK", "damage": 20, "raw_description": "Ethereal. Deal 20 damage."},
                {"id": "Iron Wave", "name": "Iron Wave", "cost": 1, "type": "ATTACK", "damage": 5, "block": 5, "raw_description": "Gain 5 Block. Deal 5 damage."},
                {"id": "Feel No Pain", "name": "Feel No Pain", "cost": 1, "type": "POWER", "raw_description": "Whenever a card is Exhausted, gain 3 Block."},
            ]
            return FullGameState(
                screen_type="CARD_REWARD",
                screen_state={"cards": offered, "skip_available": True},
                floor=1,
                act=1,
                gold=self.gold,
                current_hp=self.combat_state.player.current_hp,
                max_hp=self.combat_state.player.max_hp,
                deck=self.deck,
                relics=self.relics,
                potions=self.potions,
                is_screen_up=True,
                available_commands=["choose", "cancel"],
            )
        elif self.phase == "hand_select":
            hand_cards = [
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
                for c in self.combat_state.hand
            ]
            return FullGameState(
                screen_type="HAND_SELECT",
                screen_state={"hand": hand_cards, "max_cards": 1, "can_pick_zero": False},
                combat_state=self.combat_state,
                floor=1,
                act=1,
                gold=self.gold,
                current_hp=self.combat_state.player.current_hp,
                max_hp=self.combat_state.player.max_hp,
                deck=self.deck,
                relics=self.relics,
                potions=self.potions,
                is_screen_up=True,
                available_commands=["choose"],
            )
        elif self.phase == "map":
            next_nodes = [
                {"x": 1, "y": 2, "symbol": "M", "description": "Monster (Normal Enemy)"},
                {"x": 2, "y": 2, "symbol": "R", "description": "Rest Site (Campfire)"},
            ]
            return FullGameState(
                screen_type="MAP",
                screen_state={"next_nodes": next_nodes, "boss_available": False},
                floor=1,
                act=1,
                gold=self.gold,
                current_hp=self.combat_state.player.current_hp,
                max_hp=self.combat_state.player.max_hp,
                deck=self.deck,
                relics=self.relics,
                potions=self.potions,
                is_screen_up=True,
                available_commands=["choose"],
            )
        return None

    def send_full_action(self, action: BaseAction) -> Optional[FullGameState]:
        logger.info(f"[Mock Driver 执行动作]: {action.raw_command} (阶段: {self.phase})")

        if self.phase == "combat":
            if isinstance(action, EndTurnAction):
                self._simulate_enemy_turn()
                return self.get_full_state()

            if isinstance(action, PlayCardAction):
                card = next((c for c in self.combat_state.hand if c.index == action.card_index), None)
                if not card:
                    return self.get_full_state()

                self.combat_state.player.energy = max(0, self.combat_state.player.energy - card.cost)

                if card.block > 0:
                    self.combat_state.player.block += card.block

                if card.damage > 0:
                    target_m = self.combat_state.alive_monsters[0]
                    if action.target_index is not None:
                        target_m = next((m for m in self.combat_state.monsters if m.index == action.target_index), target_m)

                    remain_dmg = max(0, card.damage - target_m.block)
                    target_m.block = max(0, target_m.block - card.damage)
                    target_m.current_hp = max(0, target_m.current_hp - remain_dmg)

                    if target_m.current_hp <= 0:
                        logger.info(f"怪物 {target_m.name} 被击败！")
                        target_m.is_gone = True

                self.combat_state.hand = [c for c in self.combat_state.hand if c.index != card.index]
                self.combat_state.discard_pile_count += 1

                if not self.combat_state.alive_monsters:
                    logger.info("所有怪物均已阵亡，战斗胜利！进入战利品结算界面...")
                    self.combat_over = True
                    self.phase = "reward"
                    return self.get_full_state()

                if ("armaments" in card.name.lower() or card.id == "Armaments") and not card.upgraded:
                    logger.info("Mock Driver: 打出未升级武装，进入手牌选牌升级界面 (HAND_SELECT)...")
                    self.phase = "hand_select"
                    return self.get_full_state()

            return self.get_full_state()

        elif self.phase == "hand_select":
            if isinstance(action, ChooseAction):
                chosen_idx = int(action.choice)
                if 0 <= chosen_idx < len(self.combat_state.hand):
                    chosen_card = self.combat_state.hand[chosen_idx]
                    chosen_card.upgraded = True
                    chosen_card.name += "+"
                    if chosen_card.damage > 0:
                        chosen_card.damage += 3
                    if chosen_card.block > 0:
                        chosen_card.block += 3
                    logger.info(f"Mock Driver: 手牌 [{chosen_card.name}] 已升级！关闭 HandSelect 界面返回战斗。")
            self.phase = "combat"
            return self.get_full_state()

        elif self.phase == "reward":
            if isinstance(action, ChooseAction):
                if self.screen_rewards and self.screen_rewards[0]["reward_type"] == "GOLD":
                    self.gold += self.screen_rewards[0]["gold"]
                    logger.info(f"拾取金币成功！当前金币: {self.gold}")
                    self.screen_rewards.pop(0)
                    return self.get_full_state()
                elif self.screen_rewards and self.screen_rewards[0]["reward_type"] == "CARD":
                    logger.info("点击卡牌奖励，进入选牌界面...")
                    self.phase = "card_reward"
                    return self.get_full_state()
            elif isinstance(action, ProceedAction):
                logger.info("奖励领取完毕，前往地图路线选择...")
                self.phase = "map"
                return self.get_full_state()

        elif self.phase == "card_reward":
            if isinstance(action, ChooseAction):
                logger.info(f"玩家选择将候选卡牌 #{action.choice} 加入卡组！")
            elif isinstance(action, CancelAction):
                logger.info("玩家跳过本次卡牌奖励 (Skip)！")
            self.screen_rewards = []
            self.phase = "map"
            return self.get_full_state()

        elif self.phase == "map":
            if isinstance(action, ChooseAction):
                logger.info(f"玩家选择地图路线节点 #{action.choice}！")
                self.phase = "done"
                self.game_finished = True
                return None

        return self.get_full_state()

    def _simulate_enemy_turn(self):
        total_dmg = sum(m.total_incoming_damage for m in self.combat_state.alive_monsters)
        hp_loss = max(0, total_dmg - self.combat_state.player.block)
        self.combat_state.player.block = 0
        self.combat_state.player.current_hp = max(0, self.combat_state.player.current_hp - hp_loss)

        if self.combat_state.player.current_hp <= 0:
            logger.info("玩家生命归零，战斗失败。")
            self.combat_over = True
            self.game_finished = True
            return

        self.combat_state.turn += 1
        self.combat_state.player.energy = self.combat_state.player.max_energy
        self.combat_state.hand = [
            Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=6),
            Card(index=1, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
            Card(index=2, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
            Card(index=3, id="Bash", name="Bash", cost=2, type="ATTACK", target_type="ENEMY", damage=8),
        ]


class CommunicationModDriver(BaseGameDriver):
    """
    真实 Steam CommunicationMod 管道驱动：
    通过标准 stdin/stdout 与《杀戮尖塔》进行实时双向 JSON 通信。
    遵循 CommunicationMod 标准协议：
    1. 启动后立即向 stdout 发送 "ready\n" 握手信号；
    2. 循环读取 stdin，过滤过渡动画帧（ready_for_command=false 或 available_commands 为空）；
    3. 遇到 error 帧自动发送 "state\n" 恢复状态同步；
    4. 动作指令写入 stdout 后 flush。
    """

    def __init__(self):
        self.game_finished = False
        self.current_full_state: Optional[FullGameState] = None
        self._debug_intent_retries: int = 0
        logger.info("[CommunicationMod] 向游戏发送初始就绪握手信号: ready")
        sys.stdout.write("ready\n")
        sys.stdout.flush()

    def is_game_over(self) -> bool:
        return self.game_finished

    def get_full_state(self) -> Optional[FullGameState]:
        while not self.game_finished:
            line = sys.stdin.readline()
            if not line:
                self.game_finished = True
                logger.info("[CommunicationMod] 管道读取到 EOF，通信已结束。")
                return None

            line_str = line.strip()
            if not line_str:
                continue

            try:
                raw_json = json.loads(line_str)

                # 1. 通信错误处理：发送 state 指令重新请求游戏稳定状态
                if "error" in raw_json:
                    err_msg = raw_json.get("error", "")
                    logger.warning(f"[CommunicationMod 报错]: {err_msg}，发送 state 指令恢复同步...")
                    sys.stdout.write("state\n")
                    sys.stdout.flush()
                    continue

                # 2. 检查游戏是否在主菜单
                if "in_game" in raw_json and not raw_json.get("in_game", True):
                    logger.info("[CommunicationMod] 游戏当前处于主菜单或游戏外部，等待玩家进入/开始新游戏...")
                    time.sleep(1.0)
                    continue

                # 3. 检查游戏是否已稳定就绪（过滤出牌动画、扣血动画、场景切换等过渡帧）
                ready = raw_json.get("ready_for_command", False)
                available_cmds = raw_json.get("available_commands", [])

                if not ready or not available_cmds:
                    logger.debug(f"[CommunicationMod] 等待动画完成... ready={ready}, cmds={available_cmds}")
                    continue

                # 4. 拦截未初始化怪物意图帧 (Intent.DEBUG / 伤害尚未完成计算的过渡帧)
                game_state = raw_json.get("game_state", {})
                combat_state_raw = game_state.get("combat_state") or raw_json.get("combat_state")
                in_combat = game_state.get("in_combat", False) or raw_json.get("in_combat", False)

                from .combat_tracer import CombatTracer
                tracer = CombatTracer.get_instance()

                if combat_state_raw and in_combat:
                    monsters_raw = combat_state_raw.get("monsters", [])
                    unready_reasons = []

                    def _is_monster_intent_unready(m: Dict[str, Any]) -> bool:
                        if m.get("is_gone", False) or m.get("half_dead", False) or m.get("current_hp", 0) <= 0:
                            return False
                        it = m.get("intent", "").upper().strip()
                        if it in ["DEBUG", "UNKNOWN", "NONE", ""]:
                            unready_reasons.append(f"Monster {m.get('id')} has uninit intent '{it}'")
                            return True
                        # 攻击类意图但伤害数值尚未结算（CommunicationMod 在计算前通常传 -1 或 0）
                        if "ATTACK" in it:
                            adj_dmg = m.get("move_adjusted_damage", -1)
                            base_dmg = m.get("move_base_damage", -1)
                            if (adj_dmg is None or adj_dmg <= 0) and (base_dmg is None or base_dmg <= 0):
                                unready_reasons.append(f"Monster {m.get('id')} intent '{it}' with pending dmg (adj={adj_dmg}, base={base_dmg})")
                                return True
                        return False

                    has_unready_intent = any(_is_monster_intent_unready(m) for m in monsters_raw)
                    if has_unready_intent:
                        max_retries = 10
                        wait_frames = 15
                        status_str = f"BLOCKED (Try #{self._debug_intent_retries + 1}/{max_retries}: {', '.join(unready_reasons)})"
                        tracer.log_raw_combat_frame(raw_json, debounce_status=status_str)
                        if self._debug_intent_retries < max_retries:
                            self._debug_intent_retries += 1
                            logger.warning(
                                f"[CommunicationMod] 检测到存活怪物意图尚未完全初始化 ({', '.join(unready_reasons)}), "
                                f"执行防抖等待 #{self._debug_intent_retries}/{max_retries}: 发送 'wait {wait_frames}'..."
                            )
                            sys.stdout.write(f"wait {wait_frames}\n")
                            sys.stdout.flush()
                            time.sleep(0.15)
                            continue
                        else:
                            logger.warning(f"[CommunicationMod] 怪物意图等待超时 (已达 {max_retries} 次)，继续处理当前帧。")
                            self._debug_intent_retries = 0
                    else:
                        tracer.log_raw_combat_frame(raw_json, debounce_status="PASS (All monster intents ready)")
                        self._debug_intent_retries = 0

                from .compressor import StateCompressor
                self.current_full_state = StateCompressor.from_communication_mod_full_json(raw_json)
                logger.info(
                    f"[CommunicationMod 状态更新] 界面: {self.current_full_state.screen_type} | "
                    f"层数: {self.current_full_state.floor} | "
                    f"HP: {self.current_full_state.current_hp}/{self.current_full_state.max_hp} | "
                    f"可用指令: {self.current_full_state.available_commands}"
                )
                return self.current_full_state

            except json.JSONDecodeError as e:
                logger.warning(f"[CommunicationMod] 收到非 JSON 消息: {line_str[:80]}... 异常: {e}")
                continue
            except Exception as e:
                logger.error(f"[CommunicationMod] 解析状态异常: {e}", exc_info=True)
                continue

        return None

    def send_full_action(self, action: BaseAction) -> Optional[FullGameState]:
        cmd = action.raw_command.strip().lower()
        logger.info(f"[CommunicationMod 发送指令]: {cmd}")
        sys.stdout.write(cmd + "\n")
        sys.stdout.flush()
        time.sleep(0.05)
        return self.get_full_state()


class SocketGameDriver(BaseGameDriver):
    """
    TCP Socket 游戏驱动：
    连接本地 CommunicationMod 继电器 (默认 127.0.0.1:18888)。
    适用于 MCP Server、网页端或外部调试器与运行中的 Steam 游戏进行双向异步通信。
    若未启动真实游戏，is_connected() 返回 False，允许上层优雅回退至 MockGameDriver 沙盒。
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 18888, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.file_r = None
        self.file_w = None
        self.game_finished = False
        self.current_full_state: Optional[FullGameState] = None
        self._debug_intent_retries: int = 0
        self.connect()

    def connect(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
            self.file_r = self.sock.makefile("r", encoding="utf-8")
            self.file_w = self.sock.makefile("w", encoding="utf-8")
            self.file_w.write("state\n")
            self.file_w.flush()
            logger.info(f"[SocketDriver] 成功连接至 {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.debug(f"[SocketDriver] 连接至 {self.host}:{self.port} 失败: {e}")
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
            self.sock = None
            self.file_r = None
            self.file_w = None
            return False

    def is_connected(self) -> bool:
        return self.sock is not None and not self.game_finished

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.file_r = None
        self.file_w = None

    def is_game_over(self) -> bool:
        return self.game_finished or not self.is_connected()

    def get_full_state(self, request_state: bool = True) -> Optional[FullGameState]:
        if not self.is_connected():
            return None
        if request_state:
            try:
                if self.sock:
                    self.sock.setblocking(False)
                    try:
                        while self.sock.recv(65536):
                            pass
                    except (BlockingIOError, socket.error):
                        pass
                    self.sock.setblocking(True)
                    self.file_r = self.sock.makefile("r", encoding="utf-8")
                self.file_w.write("state\n")
                self.file_w.flush()
            except Exception as e:
                logger.warning(f"[SocketDriver] 请求 state 失败: {e}")
                self.close()
                return self.current_full_state
        while not self.game_finished:
            try:
                line = self.file_r.readline()
            except Exception as e:
                logger.warning(f"[SocketDriver] 读取数据异常: {e}")
                if self.sock:
                    try:
                        self.file_r = self.sock.makefile("r", encoding="utf-8")
                    except Exception:
                        self.close()
                return self.current_full_state
            if not line:
                self.game_finished = True
                logger.info("[SocketDriver] 连接已断开 (EOF)。")
                self.close()
                return self.current_full_state

            line_str = line.strip()
            if not line_str:
                continue

            try:
                raw_json = json.loads(line_str)
                if "error" in raw_json:
                    err_msg = raw_json.get("error", "")
                    logger.warning(f"[SocketDriver 报错]: {err_msg}，发送 state 指令恢复同步...")
                    self.file_w.write("state\n")
                    self.file_w.flush()
                    continue

                if "in_game" in raw_json and not raw_json.get("in_game", True):
                    logger.info("[SocketDriver] 游戏当前处于主菜单或外部...")
                    time.sleep(1.0)
                    continue

                ready = raw_json.get("ready_for_command", False)
                available_cmds = raw_json.get("available_commands", [])
                if not ready or not available_cmds:
                    continue

                # 怪物意图防抖
                game_state = raw_json.get("game_state", {})
                combat_state_raw = game_state.get("combat_state") or raw_json.get("combat_state")
                in_combat = game_state.get("in_combat", False) or raw_json.get("in_combat", False)

                from .combat_tracer import CombatTracer
                tracer = CombatTracer.get_instance()

                if combat_state_raw and in_combat:
                    monsters_raw = combat_state_raw.get("monsters", [])
                    unready_reasons = []

                    def _is_unready(m: Dict[str, Any]) -> bool:
                        if m.get("is_gone", False) or m.get("half_dead", False) or m.get("current_hp", 0) <= 0:
                            return False
                        it = m.get("intent", "").upper().strip()
                        if it in ["DEBUG", "UNKNOWN", "NONE", ""]:
                            unready_reasons.append(f"Monster {m.get('id')} intent '{it}'")
                            return True
                        if "ATTACK" in it:
                            adj_dmg = m.get("move_adjusted_damage", -1)
                            base_dmg = m.get("move_base_damage", -1)
                            if (adj_dmg is None or adj_dmg <= 0) and (base_dmg is None or base_dmg <= 0):
                                unready_reasons.append(f"Monster {m.get('id')} pending dmg")
                                return True
                        return False

                    if any(_is_unready(m) for m in monsters_raw):
                        if self._debug_intent_retries < 10:
                            self._debug_intent_retries += 1
                            self.file_w.write("wait 15\n")
                            self.file_w.flush()
                            time.sleep(0.15)
                            continue
                        else:
                            self._debug_intent_retries = 0
                    else:
                        tracer.log_raw_combat_frame(raw_json, debounce_status="PASS (All monster intents ready)")
                        self._debug_intent_retries = 0

                from .compressor import StateCompressor
                self.current_full_state = StateCompressor.from_communication_mod_full_json(raw_json)
                return self.current_full_state

            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"[SocketDriver] 解析状态异常: {e}")
                continue

        return None

    def send_full_action(self, action: BaseAction) -> Optional[FullGameState]:
        if not self.is_connected():
            return None
        cmd = action.raw_command.strip().lower()
        logger.info(f"[SocketDriver 发送指令]: {cmd}")
        try:
            self.file_w.write(cmd + "\n")
            self.file_w.flush()
        except Exception as e:
            logger.warning(f"[SocketDriver] 发送指令异常: {e}")
            self.close()
            return self.current_full_state
        time.sleep(0.05)
        return self.get_full_state(request_state=False)


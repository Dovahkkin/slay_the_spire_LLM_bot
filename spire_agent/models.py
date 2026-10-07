from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any, Union
from pydantic import BaseModel, Field


class Power(BaseModel):
    id: str
    name: str
    amount: int = 0


class Card(BaseModel):
    index: int
    name: str
    id: str
    cost: int
    type: Literal["ATTACK", "SKILL", "POWER", "STATUS", "CURSE"]
    target_type: Literal["ENEMY", "ALL_ENEMY", "SELF", "NONE"] = "NONE"
    has_target: bool = False
    is_playable: bool = True
    damage: int = 0
    block: int = 0
    description: str = ""
    upgraded: bool = False

    @property
    def is_card_draw_or_generator(self) -> bool:
        """判断是否为过牌/衍生卡（例如战吼、战斗专注、祭品、剑柄打击），打出后需要中断连击并重新推演"""
        draw_keywords = ["draw", "抽", "battle trance", "offering", "pommel strike", "warcry", "burning pact", "havoc"]
        desc_lower = (self.description or "").lower()
        name_lower = self.name.lower()
        return any(kw in desc_lower or kw in name_lower for kw in draw_keywords)


class Monster(BaseModel):
    index: int
    id: str
    name: str
    current_hp: int
    max_hp: int
    block: int = 0
    intent: str = "UNKNOWN"
    move_damage: int = 0
    move_hits: int = 1
    powers: List[Power] = Field(default_factory=list)
    is_gone: bool = False
    half_dead: bool = False

    @property
    def total_incoming_damage(self) -> int:
        if "ATTACK" in self.intent.upper() or self.move_damage > 0:
            return max(0, self.move_damage) * max(1, self.move_hits)
        return 0

    @property
    def intent_description(self) -> str:
        it = self.intent.upper().strip()
        hits = max(1, self.move_hits)
        dmg_str = f"Attack {self.move_damage}x{hits}" if hits > 1 else f"Attack {self.move_damage}"
        if it == "ATTACK_DEBUFF":
            return f"{dmg_str} + Debuff"
        elif it == "ATTACK_DEFEND":
            return f"{dmg_str} + Defend"
        elif it == "ATTACK_BUFF":
            return f"{dmg_str} + Buff"
        elif it == "ATTACK":
            return dmg_str
        elif it == "DEFEND_DEBUFF":
            if self.move_damage > 0:
                return f"{dmg_str} + Defend + Debuff"
            return "Defend + Debuff"
        elif it == "DEFEND_BUFF":
            if self.move_damage > 0:
                return f"{dmg_str} + Defend + Buff"
            return "Defend + Buff"
        elif it == "DEFEND":
            if self.move_damage > 0:
                return f"{dmg_str} + Defend"
            return "Defend"
        elif it in ["DEBUFF", "STRONG_DEBUFF"]:
            if self.move_damage > 0:
                return f"{dmg_str} + Debuff"
            return "Debuff (No attack, 0 dmg)"
        elif it == "BUFF":
            if self.move_damage > 0:
                return f"{dmg_str} + Buff"
            return "Buff (No attack, 0 dmg)"
        elif it == "SLEEP":
            return "Sleeping (0 dmg)"
        elif it == "STUN":
            return "Stunned (0 dmg)"
        elif it == "ESCAPE":
            return "Escape (0 dmg)"
        elif it == "MAGIC":
            if self.move_damage > 0:
                return f"{dmg_str} (Magic)"
            return "Magic / Special (0 dmg)"
        elif it == "NONE":
            return "None (0 dmg)"
        elif it == "DEBUG":
            if self.move_damage > 0:
                return f"{dmg_str} (Uninitialized)"
            return "Uninitialized / Waiting"
        elif it == "UNKNOWN":
            if self.move_damage > 0:
                return f"{dmg_str} (Unknown intent)"
            return "Unknown intent"
        else:
            if self.move_damage > 0:
                return f"{dmg_str} ({self.intent})"
            return self.intent

    @property
    def is_alive(self) -> bool:
        return self.current_hp > 0 and not self.is_gone and not self.half_dead


class Player(BaseModel):
    current_hp: int
    max_hp: int
    energy: int
    max_energy: int = 3
    block: int = 0
    powers: List[Power] = Field(default_factory=list)
    relics: List[str] = Field(default_factory=list)


class Potion(BaseModel):
    index: int
    name: str
    id: str
    can_use: bool = False
    can_discard: bool = False
    requires_target: bool = False
    description: str = ""

    @property
    def is_empty(self) -> bool:
        name_clean = self.name.lower().replace(" ", "").replace("_", "")
        id_clean = self.id.lower().replace(" ", "").replace("_", "")
        if "potionslot" in name_clean or "potionslot" in id_clean:
            return True
        if not self.name or not self.id:
            return True
        if not self.can_discard:
            return True
        return False


class CombatState(BaseModel):
    """当前战斗回合的战场切片"""
    turn: int = 1
    player: Player
    monsters: List[Monster] = Field(default_factory=list)
    hand: List[Card] = Field(default_factory=list)
    potions: List[Potion] = Field(default_factory=list)
    draw_pile: List[str] = Field(default_factory=list)
    discard_pile: List[str] = Field(default_factory=list)
    exhaust_pile: List[str] = Field(default_factory=list)
    draw_pile_count: int = 0
    discard_pile_count: int = 0
    exhaust_pile_count: int = 0

    @property
    def alive_monsters(self) -> List[Monster]:
        return [m for m in self.monsters if m.is_alive]

    @property
    def playable_cards(self) -> List[Card]:
        return [c for c in self.hand if c.is_playable and c.cost <= self.player.energy]


class MapNode(BaseModel):
    x: int
    y: int
    symbol: str  # M, ?, E, R, $, T, etc.

    @property
    def description(self) -> str:
        symbol_map = {
            "M": "Monster (普通怪 - 稳妥收益)",
            "?": "Event (未知事件房)",
            "E": "Elite (精英怪 - 掉落珍贵遗物，高风险高收益)",
            "R": "Rest Site (营地火堆 - 回复30%生命或锻造升级卡牌)",
            "$": "Shop (商人商店 - 消费金币删牌或购入强力遗物)",
            "T": "Treasure (宝箱房)",
        }
        return symbol_map.get(self.symbol, f"房间 '{self.symbol}'")


class FullGameState(BaseModel):
    """通信层完整全局状态帧"""
    screen_type: str = "NONE"
    screen_state: Dict[str, Any] = Field(default_factory=dict)
    available_commands: List[str] = Field(default_factory=list)
    choice_list: List[str] = Field(default_factory=list)
    ready_for_command: bool = True
    in_game: bool = True
    floor: int = 0
    act: int = 1
    gold: int = 0
    current_hp: int = 0
    max_hp: int = 0
    deck: List[Card] = Field(default_factory=list)
    relics: List[str] = Field(default_factory=list)
    potions: List[Potion] = Field(default_factory=list)
    combat_state: Optional[CombatState] = None
    is_screen_up: bool = False

    @property
    def in_combat(self) -> bool:
        if "play" in self.available_commands or "end" in self.available_commands:
            return True
        if self.combat_state is not None:
            # 战斗内弹窗（如 HAND_SELECT / GRID）且有存活敌人时，依然属于战斗阶段
            if self.screen_type in ["HAND_SELECT", "GRID"]:
                return len(self.combat_state.alive_monsters) > 0
            if not self.is_screen_up:
                return len(self.combat_state.alive_monsters) > 0
        return False


# --- 结构化游戏指令 ---
class BaseAction(BaseModel):
    action_type: Literal["play", "potion", "end_turn", "choose", "proceed", "cancel", "confirm", "leave", "return", "skip"]
    raw_command: str


class PlayCardAction(BaseAction):
    action_type: Literal["play"] = "play"
    card_index: int  # 内部 0-indexed
    target_index: Optional[int] = None  # 内部 0-indexed
    card_name: str = ""
    card_id: str = ""

    @classmethod
    def create(
        cls,
        card_index: int,
        target_index: Optional[int] = None,
        card_name: str = "",
        card_id: str = "",
    ) -> "PlayCardAction":
        card_param = card_index + 1
        cmd = f"PLAY {card_param}" if target_index is None else f"PLAY {card_param} {target_index}"
        return cls(
            raw_command=cmd,
            card_index=card_index,
            target_index=target_index,
            card_name=card_name,
            card_id=card_id,
        )


class UsePotionAction(BaseAction):
    action_type: Literal["potion"] = "potion"
    potion_index: int
    target_index: Optional[int] = None

    @classmethod
    def create(cls, potion_index: int, target_index: Optional[int] = None) -> "UsePotionAction":
        cmd = f"POTION USE {potion_index}" if target_index is None else f"POTION USE {potion_index} {target_index}"
        return cls(raw_command=cmd, potion_index=potion_index, target_index=target_index)


class EndTurnAction(BaseAction):
    action_type: Literal["end_turn"] = "end_turn"

    @classmethod
    def create(cls) -> "EndTurnAction":
        return cls(raw_command="END")


class ChooseAction(BaseAction):
    action_type: Literal["choose"] = "choose"
    choice: str

    @classmethod
    def create(cls, choice: Any) -> "ChooseAction":
        return cls(raw_command=f"CHOOSE {choice}", choice=str(choice))


class ProceedAction(BaseAction):
    action_type: Literal["proceed"] = "proceed"

    @classmethod
    def create(cls) -> "ProceedAction":
        return cls(raw_command="PROCEED")


class CancelAction(BaseAction):
    action_type: Literal["cancel"] = "cancel"

    @classmethod
    def create(cls) -> "CancelAction":
        return cls(raw_command="CANCEL")


class ConfirmAction(BaseAction):
    action_type: Literal["confirm"] = "confirm"

    @classmethod
    def create(cls) -> "ConfirmAction":
        return cls(raw_command="CONFIRM")


class LeaveAction(BaseAction):
    action_type: Literal["leave"] = "leave"

    @classmethod
    def create(cls) -> "LeaveAction":
        return cls(raw_command="LEAVE")


class ReturnAction(BaseAction):
    action_type: Literal["return"] = "return"

    @classmethod
    def create(cls) -> "ReturnAction":
        return cls(raw_command="RETURN")


class SkipAction(BaseAction):
    action_type: Literal["skip"] = "skip"

    @classmethod
    def create(cls) -> "SkipAction":
        return cls(raw_command="SKIP")


class TurnPlan(BaseModel):
    """回合级连击规划方案"""
    reasoning: str = ""
    actions: List[Union[PlayCardAction, UsePotionAction, EndTurnAction]] = Field(default_factory=list)

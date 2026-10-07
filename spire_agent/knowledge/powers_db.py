"""
尖塔状态效果 (Buffs & Debuffs) 知识库与动态注入工具
整合官方 Wiki 全量 Buff 与 Debuff 数据，用于在每回合战斗状态中动态注入当前活跃的
非基础状态效果，避免 System Prompt 膨胀的同时为模型提供精准的机制解释与战术避坑指南。
"""

from typing import Dict, Any, Optional, List
import re

# 常驻基础状态（已在 System Prompt 中深度阐明，禁止重复动态注入以节省 Token）
EXCLUDED_BASIC_POWERS = {
    "strength", "dexterity", "vulnerable", "weak", "frail", "block"
}


def normalize_power_key(raw_id: str) -> str:
    """归一化 Power 键：去除空格、下划线、标点符号并转小写"""
    if not raw_id:
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", raw_id).lower()


# 全量 Buffs & Debuffs 知识库字典
POWERS_DATABASE: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # 1. 怪物高危 / 特有机制 Buffs
    # =========================================================================
    "ritual": {
        "name": "Ritual",
        "type": "BUFF",
        "desc": "At the end of turn, gains {amount} Strength.",
        "warning": "Scales infinitely every turn! Prioritize dealing frontloaded lethal damage."
    },
    "enrage": {
        "name": "Enrage",
        "type": "BUFF",
        "desc": "Whenever the player plays a SKILL card, gains {amount} Strength.",
        "warning": "AVOID PLAYING SKILLS! Every Skill (including Defend/Flex) permanently buffs enemy attack."
    },
    "curlup": {
        "name": "Curl Up",
        "type": "BUFF",
        "desc": "On taking attack damage for the first time, gains {amount} Block.",
        "warning": "Trigger with a low-damage attack first or burst through with huge single-hit lethal damage."
    },
    "modeshift": {
        "name": "Mode Shift",
        "type": "BUFF",
        "desc": "Shifts to Defensive Mode (gains 20 Block & Sharp Hide thorns) after taking {amount} damage.",
        "warning": "Be ready to stop multi-hit attacks once shifted to Defensive Mode."
    },
    "sharphide": {
        "name": "Sharp Hide",
        "type": "BUFF",
        "desc": "Whenever you play an Attack card, you take {amount} damage.",
        "warning": "Playing multiple low-damage attacks causes severe self-damage! Use high-damage single hits."
    },
    "thorns": {
        "name": "Thorns",
        "type": "BUFF",
        "desc": "Whenever attacked, deals {amount} damage back to the attacker.",
        "warning": "Multi-hit attacks deal massive self-damage! Focus on heavy single hits."
    },
    "metallicize": {
        "name": "Metallicize",
        "type": "BUFF",
        "desc": "At the end of turn, gains {amount} Block.",
    },
    "platedarmor": {
        "name": "Plated Armor",
        "type": "BUFF",
        "desc": "At the end of turn, gains {amount} Block. Taking unblocked attack damage reduces Plated Armor by 1.",
        "warning": "Deal unblocked damage to chip away its Plated Armor."
    },
    "regenerate": {
        "name": "Regenerate",
        "type": "BUFF",
        "desc": "At the end of turn, heals {amount} HP, then decreases stack by 1.",
    },
    "split": {
        "name": "Split",
        "type": "BUFF",
        "desc": "When reduced to 50% HP or lower, splits into two smaller slimes.",
        "warning": "Damage as close to threshold as possible before splitting to minimize offspring starting HP."
    },
    "malleable": {
        "name": "Malleable",
        "type": "BUFF",
        "desc": "On taking attack damage, gains {amount} Block. Block gained increases each time attacked this turn. Resets each turn.",
        "warning": "Avoid spamming small attacks; each subsequent attack faces higher block."
    },
    "angry": {
        "name": "Angry",
        "type": "BUFF",
        "desc": "Whenever attacked, gains {amount} Strength.",
        "warning": "Every separate attack hit permanently increases its Strength!"
    },
    "beatofdeath": {
        "name": "Beat of Death",
        "type": "BUFF",
        "desc": "Whenever you play a card, take {amount} damage.",
        "warning": "Every card played deals unavoidable damage to you; ensure enough Block before playing cards."
    },
    "timewarp": {
        "name": "Time Warp",
        "type": "BUFF",
        "desc": "Whenever you play a card, counter increases by 1. Reaching 12 immediately ends your turn and grants +2 Strength.",
        "warning": "Count your cards carefully! Do not get forced into ending turn with zero defense."
    },
    "invincible": {
        "name": "Invincible",
        "type": "BUFF",
        "desc": "Damage taken this turn is capped at {amount}.",
        "warning": "Do not waste additional attack damage once the cap is reached."
    },
    "sporecloud": {
        "name": "Spore Cloud",
        "type": "BUFF",
        "desc": "On death, applies {amount} Vulnerable to the player.",
    },
    "painfulstabs": {
        "name": "Painful Stabs",
        "type": "BUFF",
        "desc": "Attacks add Wounds into your discard pile.",
    },
    "minion": {
        "name": "Minion",
        "type": "BUFF",
        "desc": "Flees when the leader is defeated. Does not reward combat win on its own.",
    },
    "stasis": {
        "name": "Stasis",
        "type": "BUFF",
        "desc": "Contains a stolen card from your draw pile; returns to hand upon this enemy's death.",
    },
    "curiosity": {
        "name": "Curiosity",
        "type": "BUFF",
        "desc": "Whenever you play a Power card, gains {amount} Strength.",
        "warning": "Do not play low-impact Power cards against this monster."
    },
    "unawakened": {
        "name": "Unawakened",
        "type": "BUFF",
        "desc": "Has not yet awakened. Enters Phase 2 upon defeat.",
    },
    "rebirth": {
        "name": "Rebirth",
        "type": "BUFF",
        "desc": "Resurrects with 50% HP after 2 turns if other allies are still alive.",
        "warning": "Kill all enemies simultaneously or in rapid succession."
    },
    "shifting": {
        "name": "Shifting",
        "type": "BUFF",
        "desc": "Taking attack damage reduces this monster's Strength by the same amount for this turn.",
        "warning": "Attack aggressively to mitigate its incoming damage!"
    },
    "slow": {
        "name": "Slow",
        "type": "DEBUFF",
        "desc": "Receives {amount}0% more damage from attacks this turn. Playing any card increases Slow by 1.",
        "warning": "Play cheap cards first to ramp up Slow damage bonus before heavy attacks."
    },

    # =========================================================================
    # 2. 玩家铁甲核心能力 / 关键状态 Buffs
    # =========================================================================
    "barricade": {
        "name": "Barricade",
        "type": "BUFF",
        "desc": "Block is not removed at the start of your turn.",
    },
    "blur": {
        "name": "Blur",
        "type": "BUFF",
        "desc": "Block is not removed at the start of your next {amount} turn(s).",
    },
    "buffer": {
        "name": "Buffer",
        "type": "BUFF",
        "desc": "Prevents the next {amount} time(s) you would lose HP.",
    },
    "intangible": {
        "name": "Intangible",
        "type": "BUFF",
        "desc": "Reduces ALL incoming attack damage and HP loss to 1.",
    },
    "artifact": {
        "name": "Artifact",
        "type": "BUFF",
        "desc": "Negates the next {amount} debuff(s) applied.",
    },
    "flamebarrier": {
        "name": "Flame Barrier",
        "type": "BUFF",
        "desc": "Whenever attacked this turn, deals {amount} damage back to attacker.",
    },
    "combust": {
        "name": "Combust",
        "type": "BUFF",
        "desc": "At the end of your turn, lose 1 HP and deal {amount} damage to ALL enemies.",
    },
    "corruption": {
        "name": "Corruption",
        "type": "BUFF",
        "desc": "All Skills cost 0 Energy and Exhaust when played.",
    },
    "feelnopain": {
        "name": "Feel No Pain",
        "type": "BUFF",
        "desc": "Whenever a card is Exhausted, gain {amount} Block.",
    },
    "darkembrace": {
        "name": "Dark Embrace",
        "type": "BUFF",
        "desc": "Whenever a card is Exhausted, draw {amount} card(s).",
    },
    "demonform": {
        "name": "Demon Form",
        "type": "BUFF",
        "desc": "At the start of your turn, gain {amount} Strength.",
    },
    "brutality": {
        "name": "Brutality",
        "type": "BUFF",
        "desc": "At the start of your turn, lose 1 HP and draw {amount} card(s).",
    },
    "rupture": {
        "name": "Rupture",
        "type": "BUFF",
        "desc": "Whenever you lose HP from a card, gain {amount} Strength.",
    },
    "evolve": {
        "name": "Evolve",
        "type": "BUFF",
        "desc": "Whenever you draw a Status card, draw {amount} card(s).",
    },
    "firebreathing": {
        "name": "Fire Breathing",
        "type": "BUFF",
        "desc": "Whenever you draw a Status or Curse card, deal {amount} damage to ALL enemies.",
    },
    "juggernaut": {
        "name": "Juggernaut",
        "type": "BUFF",
        "desc": "Whenever you gain Block, deal {amount} damage to a random enemy.",
    },
    "berserk": {
        "name": "Berserk",
        "type": "BUFF",
        "desc": "At the start of your turn, gain {amount} Energy.",
    },
    "rage": {
        "name": "Rage",
        "type": "BUFF",
        "desc": "Whenever you play an Attack this turn, gain {amount} Block.",
    },
    "vigor": {
        "name": "Vigor",
        "type": "BUFF",
        "desc": "Your next Attack deals {amount} additional damage.",
    },
    "pennib": {
        "name": "Pen Nib",
        "type": "BUFF",
        "desc": "Every 10th Attack deals double damage (current count: {amount}/10).",
    },
    "doubledamage": {
        "name": "Double Damage",
        "type": "BUFF",
        "desc": "Your next Attack deals double damage.",
    },
    "echoform": {
        "name": "Echo Form",
        "type": "BUFF",
        "desc": "The first {amount} card(s) played each turn are played twice.",
    },
    "electro": {
        "name": "Electrodynamics",
        "type": "BUFF",
        "desc": "Lightning hits ALL enemies.",
    },
    "mantra": {
        "name": "Mantra",
        "type": "BUFF",
        "desc": "When reaching 10 Mantra, enter Divinity (gain 3 Energy and deal 3x damage).",
    },

    # =========================================================================
    # 3. 关键 / 限制性 Debuffs (玩家与敌人)
    # =========================================================================
    "entangled": {
        "name": "Entangled",
        "type": "DEBUFF",
        "desc": "You cannot play Attack cards this turn.",
        "warning": "DO NOT PLAN ATTACKS! Spend all available energy on Skills or Powers."
    },
    "nodraw": {
        "name": "No Draw",
        "type": "DEBUFF",
        "desc": "You may not draw any more cards this turn.",
    },
    "drawreduction": {
        "name": "Draw Reduction",
        "type": "DEBUFF",
        "desc": "Draw 1 less card at the start of your next {amount} turn(s).",
    },
    "hex": {
        "name": "Hex",
        "type": "DEBUFF",
        "desc": "Whenever you play a non-Attack card, add {amount} Dazed to your draw pile.",
        "warning": "Playing skills rapidly clutters your draw pile with Dazed."
    },
    "constricted": {
        "name": "Constricted",
        "type": "DEBUFF",
        "desc": "At the end of your turn, take {amount} damage.",
        "warning": "Guaranteed HP loss at end of turn; requires sufficient Block."
    },
    "confused": {
        "name": "Confused",
        "type": "DEBUFF",
        "desc": "Card costs are randomized between 0 and 3 when drawn.",
    },
    "shackled": {
        "name": "Shackled",
        "type": "DEBUFF",
        "desc": "At the end of turn, regains {amount} Strength.",
    },
    "poison": {
        "name": "Poison",
        "type": "DEBUFF",
        "desc": "At the beginning of turn, takes {amount} damage and loses 1 stack.",
    },
    "choked": {
        "name": "Choked",
        "type": "DEBUFF",
        "desc": "Whenever you play a card this turn, the targeted enemy loses {amount} HP.",
    },
    "blockreturn": {
        "name": "Block Return",
        "type": "DEBUFF",
        "desc": "Whenever you attack this enemy, gain {amount} Block.",
    },
    "bias": {
        "name": "Bias",
        "type": "DEBUFF",
        "desc": "At the start of your turn, lose {amount} Focus.",
    },
    "fasting": {
        "name": "Fasting",
        "type": "DEBUFF",
        "desc": "Gain {amount} less Energy at the start of each turn.",
    },
    "lockon": {
        "name": "Lock-On",
        "type": "DEBUFF",
        "desc": "Takes 50% more damage from Orbs for {amount} turn(s).",
    },
    "corpseexplosion": {
        "name": "Corpse Explosion",
        "type": "DEBUFF",
        "desc": "On death, deals damage equal to its Max HP to ALL other enemies.",
    },
}


def lookup_power_info(raw_id_or_name: str) -> Optional[Dict[str, Any]]:
    """查找 Power 详细定义，支持大小写与格式容错"""
    key = normalize_power_key(raw_id_or_name)
    if not key:
        return None
    return POWERS_DATABASE.get(key)


def format_active_powers(player_powers: List[Any], monsters: List[Any]) -> List[str]:
    """
    提取当前战斗中玩家与存活怪物身上具有战略意义的非基础 Powers，
    格式化为紧凑有力的解释与避坑指南（供动态注入到 Combat Prompt 中）。
    """
    formatted_lines: List[str] = []
    seen_keys = set()

    # 1. 检查玩家身上的特殊 Powers
    for p in player_powers:
        p_id = getattr(p, "id", "") or getattr(p, "name", "")
        p_name = getattr(p, "name", "") or p_id
        amount = getattr(p, "amount", 0)
        norm_key = normalize_power_key(p_id)

        if not norm_key or norm_key in EXCLUDED_BASIC_POWERS or amount == 0:
            continue

        info = lookup_power_info(norm_key)
        item_key = f"player_{norm_key}_{amount}"
        if item_key in seen_keys:
            continue
        seen_keys.add(item_key)

        if info:
            desc = info["desc"].replace("{amount}", str(amount))
            warning_part = f" [{info['warning']}]" if info.get("warning") else ""
            formatted_lines.append(f"* [{info['name']}:{amount} (Player)]: {desc}{warning_part}")
        else:
            formatted_lines.append(f"* [{p_name}:{amount} (Player)]: Active combat effect")

    # 2. 检查存活怪物身上的特殊 Powers
    for m in monsters:
        if not getattr(m, "is_alive", True):
            continue
        m_name = getattr(m, "name", "Enemy")
        m_idx = getattr(m, "index", 0)
        target_label = f"E{m_idx} {m_name}"

        for p in getattr(m, "powers", []):
            p_id = getattr(p, "id", "") or getattr(p, "name", "")
            p_name = getattr(p, "name", "") or p_id
            amount = getattr(p, "amount", 0)
            norm_key = normalize_power_key(p_id)

            if not norm_key or norm_key in EXCLUDED_BASIC_POWERS or amount == 0:
                continue

            item_key = f"{target_label}_{norm_key}_{amount}"
            if item_key in seen_keys:
                continue
            seen_keys.add(item_key)

            info = lookup_power_info(norm_key)
            if info:
                desc = info["desc"].replace("{amount}", str(amount))
                warning_part = f" [{info['warning']}]" if info.get("warning") else ""
                formatted_lines.append(f"* [{info['name']}:{amount} ({target_label})]: {desc}{warning_part}")
            else:
                formatted_lines.append(f"* [{p_name}:{amount} ({target_label})]: Active combat effect")

    return formatted_lines

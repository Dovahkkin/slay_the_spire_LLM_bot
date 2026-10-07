"""
尖塔卡牌基础数值与效果知识库 (Card Database)
解决 CommunicationMod 不发送卡牌 base damage / block / description 的协议缺陷，
为 StateCompressor 和 DamageCalculatorTool 提供真实的数值底座。
"""

from typing import Dict, Any, Optional

CARD_DATABASE: Dict[str, Dict[str, Any]] = {
    # --- Ironclad Basic ---
    "Strike_R": {"name": "Strike", "damage": 6, "upgrade_damage": 9, "block": 0, "hits": 1, "type": "ATTACK", "desc": "Deal 6 (9) damage."},
    "Defend_R": {"name": "Defend", "damage": 0, "block": 5, "upgrade_block": 8, "type": "SKILL", "desc": "Gain 5 (8) Block."},
    "Bash": {"name": "Bash", "damage": 8, "upgrade_damage": 10, "block": 0, "hits": 1, "vulnerable": 2, "upgrade_vulnerable": 3, "type": "ATTACK", "desc": "Deal 8 (10) damage. Apply 2 (3) Vulnerable."},

    # --- Ironclad Common Attacks ---
    "Anger": {"name": "Anger", "damage": 6, "upgrade_damage": 8, "hits": 1, "type": "ATTACK", "desc": "Deal 6 (8) damage. Add a copy of this card to discard pile."},
    "Body Slam": {"name": "Body Slam", "damage": 0, "body_slam": True, "type": "ATTACK", "desc": "Deal damage equal to your current Block."},
    "Clash": {"name": "Clash", "damage": 14, "upgrade_damage": 18, "hits": 1, "type": "ATTACK", "desc": "Can only be played if every card in hand is an Attack. Deal 14 (18) damage."},
    "Cleave": {"name": "Cleave", "damage": 8, "upgrade_damage": 11, "hits": 1, "target": "ALL_ENEMY", "type": "ATTACK", "desc": "Deal 8 (11) damage to ALL enemies."},
    "Clothesline": {"name": "Clothesline", "damage": 12, "upgrade_damage": 14, "hits": 1, "weak": 2, "upgrade_weak": 3, "type": "ATTACK", "desc": "Deal 12 (14) damage. Apply 2 (3) Weak."},
    "Headbutt": {"name": "Headbutt", "damage": 9, "upgrade_damage": 12, "hits": 1, "type": "ATTACK", "desc": "Deal 9 (12) damage. Place a card from discard pile on top of draw pile."},
    "Heavy Blade": {"name": "Heavy Blade", "damage": 14, "upgrade_damage": 14, "hits": 1, "str_mult": 3, "upgrade_str_mult": 5, "type": "ATTACK", "desc": "Deal 14 damage. Strength affects this card 3 (5) times."},
    "Iron Wave": {"name": "Iron Wave", "damage": 5, "upgrade_damage": 7, "block": 5, "upgrade_block": 7, "hits": 1, "type": "ATTACK", "desc": "Gain 5 (7) Block. Deal 5 (7) damage."},
    "Perfected Strike": {"name": "Perfected Strike", "damage": 6, "upgrade_damage": 6, "hits": 1, "type": "ATTACK", "desc": "Deal 6 damage + 2 (3) for every card containing 'Strike'."},
    "Pommel Strike": {"name": "Pommel Strike", "damage": 9, "upgrade_damage": 10, "hits": 1, "draw": 1, "upgrade_draw": 2, "type": "ATTACK", "desc": "Deal 9 (10) damage. Draw 1 (2) card(s)."},
    "Sword Boomerang": {"name": "Sword Boomerang", "damage": 3, "upgrade_damage": 3, "hits": 3, "upgrade_hits": 4, "target": "ALL_ENEMY", "type": "ATTACK", "desc": "Deal 3 damage to a random enemy 3 (4) times."},
    "Thunderclap": {"name": "Thunderclap", "damage": 4, "upgrade_damage": 7, "hits": 1, "target": "ALL_ENEMY", "vulnerable_all": 1, "type": "ATTACK", "desc": "Deal 4 (7) damage and apply 1 Vulnerable to ALL enemies."},
    "Twin Strike": {"name": "Twin Strike", "damage": 5, "upgrade_damage": 7, "hits": 2, "type": "ATTACK", "desc": "Deal 5 (7) damage twice."},
    "Wild Strike": {"name": "Wild Strike", "damage": 12, "upgrade_damage": 17, "hits": 1, "type": "ATTACK", "desc": "Deal 12 (17) damage. Shuffle a Wound into your draw pile."},

    # --- Ironclad Common Skills ---
    "Armaments": {"name": "Armaments", "damage": 0, "block": 5, "upgrade_block": 5, "type": "SKILL", "desc": "Gain 5 Block. Upgrade a card (all cards) in hand for combat."},
    "Flex": {"name": "Flex", "damage": 0, "strength": 2, "upgrade_strength": 4, "type": "SKILL", "desc": "Gain 2 (4) Strength. At end of turn, lose 2 (4) Strength."},
    "Havoc": {"name": "Havoc", "damage": 0, "type": "SKILL", "desc": "Play top card of draw pile and Exhaust it."},
    "Shrug It Off": {"name": "Shrug It Off", "damage": 0, "block": 8, "upgrade_block": 11, "draw": 1, "type": "SKILL", "desc": "Gain 8 (11) Block. Draw 1 card."},
    "True Grit": {"name": "True Grit", "damage": 0, "block": 7, "upgrade_block": 9, "type": "SKILL", "desc": "Gain 7 (9) Block. Exhaust a random (chosen) card from hand."},
    "Warcry": {"name": "Warcry", "damage": 0, "draw": 1, "upgrade_draw": 2, "type": "SKILL", "desc": "Draw 1 (2) card(s). Place a card from hand on top of draw pile. Exhaust."},

    # --- Ironclad Uncommon Attacks ---
    "Blood for Blood": {"name": "Blood for Blood", "damage": 18, "upgrade_damage": 22, "hits": 1, "type": "ATTACK", "desc": "Costs 1 less per HP loss this combat. Deal 18 (22) damage."},
    "Carnage": {"name": "Carnage", "damage": 20, "upgrade_damage": 28, "hits": 1, "ethereal": True, "type": "ATTACK", "desc": "Ethereal. Deal 20 (28) damage."},
    "Dropkick": {"name": "Dropkick", "damage": 5, "upgrade_damage": 8, "hits": 1, "type": "ATTACK", "desc": "Deal 5 (8) damage. If enemy is Vulnerable, gain 1 Energy and draw 1 card."},
    "Hemokinesis": {"name": "Hemokinesis", "damage": 15, "upgrade_damage": 20, "hits": 1, "type": "ATTACK", "desc": "Lose 2 HP. Deal 15 (20) damage."},
    "Pummel": {"name": "Pummel", "damage": 2, "upgrade_damage": 2, "hits": 4, "upgrade_hits": 5, "type": "ATTACK", "desc": "Deal 2 damage 4 (5) times. Exhaust."},
    "Rampage": {"name": "Rampage", "damage": 8, "upgrade_damage": 8, "hits": 1, "type": "ATTACK", "desc": "Deal 8 damage. Every time played, increase damage by 5 (8)."},
    "Reckless Charge": {"name": "Reckless Charge", "damage": 7, "upgrade_damage": 10, "hits": 1, "type": "ATTACK", "desc": "Deal 7 (10) damage. Shuffle a Dazed into draw pile."},
    "Searing Blow": {"name": "Searing Blow", "damage": 12, "upgrade_damage": 16, "hits": 1, "type": "ATTACK", "desc": "Deal 12 damage. Can be upgraded infinitely."},
    "Sever Soul": {"name": "Sever Soul", "damage": 16, "upgrade_damage": 22, "hits": 1, "type": "ATTACK", "desc": "Exhaust all non-Attack cards in hand. Deal 16 (22) damage."},
    "Uppercut": {"name": "Uppercut", "damage": 13, "upgrade_damage": 13, "hits": 1, "vulnerable": 1, "upgrade_vulnerable": 2, "weak": 1, "upgrade_weak": 2, "type": "ATTACK", "desc": "Deal 13 damage. Apply 1 (2) Vulnerable and 1 (2) Weak."},
    "Whirlwind": {"name": "Whirlwind", "damage": 5, "upgrade_damage": 8, "target": "ALL_ENEMY", "type": "ATTACK", "desc": "Deal 5 (8) damage to ALL enemies X times."},

    # --- Ironclad Uncommon Skills & Powers ---
    "Battle Trance": {"name": "Battle Trance", "draw": 3, "upgrade_draw": 4, "type": "SKILL", "desc": "Draw 3 (4) cards. You cannot draw additional cards this turn."},
    "Bloodletting": {"name": "Bloodletting", "type": "SKILL", "desc": "Lose 3 HP. Gain 2 (3) Energy."},
    "Burning Pact": {"name": "Burning Pact", "draw": 2, "upgrade_draw": 3, "type": "SKILL", "desc": "Exhaust 1 card. Draw 2 (3) cards."},
    "Disarm": {"name": "Disarm", "type": "SKILL", "desc": "Enemy loses 2 (3) Strength. Exhaust."},
    "Dual Wield": {"name": "Dual Wield", "type": "SKILL", "desc": "Create a copy (2 copies) of an Attack or Power card in hand."},
    "Entrench": {"name": "Entrench", "type": "SKILL", "desc": "Double your current Block."},
    "Flame Barrier": {"name": "Flame Barrier", "block": 12, "upgrade_block": 16, "type": "SKILL", "desc": "Gain 12 (16) Block. Whenever attacked this turn, deal 4 (6) damage to attacker."},
    "Ghostly Armor": {"name": "Ghostly Armor", "block": 10, "upgrade_block": 13, "ethereal": True, "type": "SKILL", "desc": "Ethereal. Gain 10 (13) Block."},
    "Infernal Blade": {"name": "Infernal Blade", "type": "SKILL", "desc": "Add a random Attack to hand. It costs 0 this turn. Exhaust."},
    "Inflame": {"name": "Inflame", "strength": 2, "upgrade_strength": 3, "type": "POWER", "desc": "Gain 2 (3) Strength."},
    "Intimidate": {"name": "Intimidate", "weak_all": 1, "upgrade_weak": 2, "type": "SKILL", "desc": "Apply 1 (2) Weak to ALL enemies. Exhaust."},
    "Metallicize": {"name": "Metallicize", "type": "POWER", "desc": "At the end of your turn, gain 3 (4) Block."},
    "Power Through": {"name": "Power Through", "block": 15, "upgrade_block": 20, "type": "SKILL", "desc": "Add 2 Wounds into hand. Gain 15 (20) Block."},
    "Rage": {"name": "Rage", "type": "SKILL", "desc": "Whenever you play an Attack this turn, gain 3 (5) Block."},
    "Second Wind": {"name": "Second Wind", "type": "SKILL", "desc": "Exhaust all non-Attack cards in hand. Gain 5 (7) Block for each."},
    "Seeing Red": {"name": "Seeing Red", "type": "SKILL", "desc": "Gain 2 Energy. Exhaust."},
    "Sentinel": {"name": "Sentinel", "block": 5, "upgrade_block": 8, "type": "SKILL", "desc": "Gain 5 (8) Block. If exhausted, gain 2 (3) Energy."},
    "Shockwave": {"name": "Shockwave", "vulnerable_all": 3, "upgrade_vulnerable": 5, "weak_all": 3, "upgrade_weak": 5, "type": "SKILL", "desc": "Apply 3 (5) Vulnerable and Weak to ALL enemies. Exhaust."},
    "Combust": {"name": "Combust", "type": "POWER", "desc": "At the end of your turn, lose 1 HP and deal 5 (7) damage to ALL enemies."},
    "Dark Embrace": {"name": "Dark Embrace", "type": "POWER", "desc": "Whenever a card is Exhausted, draw 1 card."},
    "Evolve": {"name": "Evolve", "type": "POWER", "desc": "Whenever you draw a Status card, draw 1 (2) card(s)."},
    "Feel No Pain": {"name": "Feel No Pain", "type": "POWER", "desc": "Whenever a card is Exhausted, gain 3 (4) Block."},
    "Fire Breathing": {"name": "Fire Breathing", "type": "POWER", "desc": "Whenever you draw a Status or Curse card, deal 6 (10) damage to ALL enemies."},
    "Rupture": {"name": "Rupture", "type": "POWER", "desc": "Whenever you lose HP from a card, gain 1 (2) Strength."},
    "Spot Weakness": {"name": "Spot Weakness", "strength": 3, "upgrade_strength": 4, "type": "SKILL", "desc": "If enemy intends to attack, gain 3 (4) Strength."},

    # --- Ironclad Rare Cards ---
    "Barricade": {"name": "Barricade", "type": "POWER", "desc": "Block no longer expires at start of turn."},
    "Berserk": {"name": "Berserk", "type": "POWER", "desc": "Gain 2 (1) Vulnerable. At start of turn, gain 1 Energy."},
    "Bludgeon": {"name": "Bludgeon", "damage": 32, "upgrade_damage": 42, "hits": 1, "type": "ATTACK", "desc": "Deal 32 (42) damage."},
    "Brutality": {"name": "Brutality", "type": "POWER", "desc": "At start of turn, lose 1 HP and draw 1 card."},
    "Corruption": {"name": "Corruption", "type": "POWER", "desc": "Skills cost 0. Whenever you play a Skill, Exhaust it."},
    "Demon Form": {"name": "Demon Form", "type": "POWER", "desc": "At start of turn, gain 2 (3) Strength."},
    "Double Tap": {"name": "Double Tap", "type": "SKILL", "desc": "This turn, your next 1 (2) Attack(s) is played twice."},
    "Exhume": {"name": "Exhume", "type": "SKILL", "desc": "Choose an Exhausted card and put it into hand. Exhaust."},
    "Feed": {"name": "Feed", "damage": 10, "upgrade_damage": 12, "hits": 1, "type": "ATTACK", "desc": "Deal 10 (12) damage. If Fatal, raise Max HP by 3 (4). Exhaust."},
    "Fiend Fire": {"name": "Fiend Fire", "damage": 7, "upgrade_damage": 10, "type": "ATTACK", "desc": "Exhaust all cards in hand. Deal 7 (10) damage for each."},
    "Immolate": {"name": "Immolate", "damage": 21, "upgrade_damage": 28, "hits": 1, "target": "ALL_ENEMY", "type": "ATTACK", "desc": "Deal 21 (28) damage to ALL enemies. Add a Burn to discard pile."},
    "Impervious": {"name": "Impervious", "block": 30, "upgrade_block": 40, "type": "SKILL", "desc": "Gain 30 (40) Block. Exhaust."},
    "Juggernaut": {"name": "Juggernaut", "type": "POWER", "desc": "Whenever you gain Block, deal 5 (7) damage to a random enemy."},
    "Limit Break": {"name": "Limit Break", "type": "SKILL", "desc": "Double your Strength. (Exhaust if not upgraded)."},
    "Offering": {"name": "Offering", "draw": 3, "upgrade_draw": 5, "type": "SKILL", "desc": "Lose 6 HP. Gain 2 Energy. Draw 3 (5) cards. Exhaust."},
    "Reaper": {"name": "Reaper", "damage": 4, "upgrade_damage": 5, "hits": 1, "target": "ALL_ENEMY", "type": "ATTACK", "desc": "Deal 4 (5) damage to ALL enemies. Heal unblocked damage dealt. Exhaust."},

    # --- Common Colorless & Special ---
    "Bite": {"name": "Bite", "damage": 7, "upgrade_damage": 8, "hits": 1, "type": "ATTACK", "desc": "Deal 7 (8) damage. Heal 2 (3) HP."},
    "RitualDagger": {"name": "Ritual Dagger", "damage": 15, "upgrade_damage": 15, "hits": 1, "type": "ATTACK", "desc": "Deal 15 damage. If Fatal, permanently increase damage by 3 (5). Exhaust."},
    "Apparition": {"name": "Apparition", "block": 0, "type": "SKILL", "desc": "Gain 1 Intangible. Exhaust. (Ethereal if not upgraded)."},
    "HandOfGreed": {"name": "Hand of Greed", "damage": 20, "upgrade_damage": 25, "hits": 1, "type": "ATTACK", "desc": "Deal 20 (25) damage. If Fatal, gain 20 (25) Gold."},

    # --- Neutral Status & Curses (Damage/Block 0) ---
    "Slimed": {"name": "Slimed", "damage": 0, "block": 0, "type": "STATUS", "desc": "Exhaust."},
    "Wound": {"name": "Wound", "damage": 0, "block": 0, "type": "STATUS", "desc": "Unplayable."},
    "Dazed": {"name": "Dazed", "damage": 0, "block": 0, "type": "STATUS", "desc": "Unplayable. Ethereal."},
    "Burn": {"name": "Burn", "damage": 0, "block": 0, "type": "STATUS", "desc": "Unplayable. At end of turn, take 2 (4) damage."},
    "Void": {"name": "Void", "damage": 0, "block": 0, "type": "STATUS", "desc": "Unplayable. When drawn, lose 1 Energy. Ethereal."},
}


def lookup_card_stats(card_id: str, card_name: str = "", upgraded: bool = False) -> Dict[str, Any]:
    """
    根据 card_id 或 card_name 检索卡牌真实数值与效果。
    若卡牌在数据库中匹配，返回真实 base damage, base block, hits 以及描述。
    """
    # 优先精确匹配 ID
    entry = CARD_DATABASE.get(card_id)

    # 次选不分大小写/去除下划线匹配
    if not entry:
        c_clean = card_id.lower().replace("_r", "").replace("_", "").replace(" ", "")
        for k, v in CARD_DATABASE.items():
            k_clean = k.lower().replace("_r", "").replace("_", "").replace(" ", "")
            if c_clean == k_clean or (card_name and card_name.lower() == v["name"].lower()):
                entry = v
                break

    if not entry:
        return {"damage": 0, "block": 0, "hits": 1, "description": ""}

    dmg = entry.get("upgrade_damage" if upgraded else "damage", entry.get("damage", 0))
    blk = entry.get("upgrade_block" if upgraded else "block", entry.get("block", 0))
    hits = entry.get("upgrade_hits" if upgraded else "hits", entry.get("hits", 1))
    desc = entry.get("desc", "")

    return {
        "damage": dmg,
        "block": blk,
        "hits": hits,
        "description": desc,
        "raw_entry": entry,
    }

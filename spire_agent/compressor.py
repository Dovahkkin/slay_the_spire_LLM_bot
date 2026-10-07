import re
from collections import OrderedDict
from typing import Dict, Any, List, Optional, Tuple
from .models import CombatState, Player, Monster, Card, Potion, Power, FullGameState
from .knowledge.cards_db import lookup_card_stats
from .knowledge.powers_db import format_active_powers
from .knowledge.monsters_db import format_monster_dossiers



class StateCompressor:
    """
    状态压缩器：
    将庞大冗余的 Slay the Spire 游戏状态压缩为高语义密度、低 Token 的紧凑 DSL 文本。
    供大模型做战略和战术推演。
    """

    @staticmethod
    def compress_combat(state: CombatState) -> str:
        lines: List[str] = []
        lines.append(f"=== COMBAT TURN {state.turn} ===")

        # 1. Player
        p = state.player
        p_powers = [f"{pw.name}:{pw.amount}" for pw in p.powers if pw.amount != 0]
        p_powers_str = f"[{', '.join(p_powers)}]" if p_powers else "none"
        relics_str = f"[{', '.join(p.relics[:6])}]" if p.relics else "none"

        lines.append(
            f"PLAYER: HP {p.current_hp}/{p.max_hp} | Energy {p.energy}/{p.max_energy} | Block {p.block} | Powers: {p_powers_str} | Relics: {relics_str}"
        )

        # 2. Monsters
        lines.append("ENEMIES:")
        for m in state.alive_monsters:
            m_powers = [f"{pw.name}:{pw.amount}" for pw in m.powers if pw.amount != 0]
            m_powers_str = f"[{', '.join(m_powers)}]" if m_powers else "none"

            lines.append(
                f"- [E{m.index}] {m.name} (ID: {m.id}): HP {m.current_hp}/{m.max_hp} | Block {m.block} | Intent: {m.intent_description} | Powers: {m_powers_str}"
            )

        # Threat calculation
        total_incoming_attack = sum(m.total_incoming_damage for m in state.alive_monsters)
        net_damage = max(0, total_incoming_attack - p.block)

        unready_intent_monsters = [
            m for m in state.alive_monsters
            if m.intent.upper().strip() in ["DEBUG", "UNKNOWN", "NONE", ""]
            or "UNINITIALIZED" in m.intent_description.upper()
        ]
        attack_intent_monsters = [
            m for m in state.alive_monsters
            if "ATTACK" in m.intent.upper() and m.total_incoming_damage == 0 and m not in unready_intent_monsters
        ]

        if unready_intent_monsters:
            names = ", ".join([f"E{m.index} ({m.name}: {m.intent_description})" for m in unready_intent_monsters])
            if total_incoming_attack == 0:
                threat_str = f"INCOMING THREAT: UNKNOWN (Intent not ready, DO NOT assume 0 threat! Unready: {names})"
            else:
                threat_str = (
                    f"INCOMING THREAT: >= {total_incoming_attack} dmg (Current Block: {p.block}) "
                    f"[WARNING: Intent not ready for {names}, DO NOT assume uninitialized enemies deal 0 threat!]"
                )
        elif total_incoming_attack == 0:
            if attack_intent_monsters:
                names = ", ".join([f"E{m.index} ({m.name}: {m.intent})" for m in attack_intent_monsters])
                threat_str = f"INCOMING THREAT: 0 dmg [WARNING: {names} has ATTACK intent with uncalculated damage! Do NOT assume 0 threat!]"
            else:
                threat_str = "INCOMING THREAT: 0 dmg (No incoming attack)"
        elif net_damage > 0:
            threat_str = f"INCOMING THREAT: {total_incoming_attack} dmg (Current Block: {p.block} -> UNBLOCKED: {net_damage} HP damage!)"
        else:
            threat_str = f"INCOMING THREAT: {total_incoming_attack} dmg (Current Block: {p.block} -> FULLY BLOCKED)"
        lines.append(threat_str)

        # 3. Monster Tactical Dossier (Dynamic Knowledge Injection)
        monster_dossiers = format_monster_dossiers(state.alive_monsters)
        if monster_dossiers:
            lines.append("MONSTER_TACTICAL_DOSSIER:")
            for md in monster_dossiers:
                lines.append(f"  {md}")

        # 4. Active Status Effects (Dynamic Knowledge Injection)
        active_powers = format_active_powers(p.powers, state.alive_monsters)
        if active_powers:
            lines.append("ACTIVE_STATUS_EFFECTS:")
            for ap in active_powers:
                lines.append(f"  {ap}")

        # 4. Playable Cards
        lines.append("PLAYABLE_CARDS:")
        playable = state.playable_cards
        if not playable:
            lines.append("  (No playable cards with current energy)")
        else:
            for c in playable:
                effects: List[str] = []
                if c.damage > 0:
                    effects.append(f"Deal {c.damage} dmg")
                if c.block > 0:
                    effects.append(f"Gain {c.block} blk")
                if c.description:
                    effects.append(c.description)
                eff_str = ", ".join(effects) if effects else "Special effect"
                target_str = f"Target: {c.target_type}"
                draw_tag = " [DRAW/GENERATE]" if c.is_card_draw_or_generator else ""
                lines.append(f"* [c{c.index}] {c.name} ({c.cost}E, {c.type}){draw_tag} -> {eff_str} ({target_str})")

        # 4. Unplayable Cards
        unplayable = [c for c in state.hand if c not in playable]
        if unplayable:
            lines.append("UNPLAYABLE_CARDS:")
            for c in unplayable:
                lines.append(f"- [c{c.index}] {c.name} ({c.cost}E) -> Not enough energy")

        # 5. Potions
        usable_potions = [p for p in state.potions if p.can_use]
        if usable_potions:
            pot_strs = [f"[p{p.index}: {p.name}]" for p in usable_potions]
            lines.append(f"POTIONS: {', '.join(pot_strs)}")

        # 6. Card Piles (Draw / Discard / Exhaust)
        from collections import Counter
        lines.append("CARD_PILES:")

        if state.draw_pile:
            d_counts = Counter(state.draw_pile)
            d_summary = [f"{name} x{cnt}" if cnt > 1 else name for name, cnt in d_counts.most_common()]
            lines.append(f"- DRAW_PILE ({len(state.draw_pile)} cards, UNORDERED pool): [{', '.join(d_summary)}]")
        else:
            lines.append(f"- DRAW_PILE ({state.draw_pile_count} cards, UNORDERED pool): empty")

        if state.discard_pile:
            dc_counts = Counter(state.discard_pile)
            dc_summary = [f"{name} x{cnt}" if cnt > 1 else name for name, cnt in dc_counts.most_common()]
            lines.append(f"- DISCARD_PILE ({len(state.discard_pile)} cards): [{', '.join(dc_summary)}]")
        else:
            lines.append(f"- DISCARD_PILE ({state.discard_pile_count} cards): empty")

        if state.exhaust_pile:
            ex_counts = Counter(state.exhaust_pile)
            ex_summary = [f"{name} x{cnt}" if cnt > 1 else name for name, cnt in ex_counts.most_common()]
            lines.append(f"- EXHAUST_PILE ({len(state.exhaust_pile)} cards): [{', '.join(ex_summary)}]")
        else:
            lines.append(f"- EXHAUST_PILE ({state.exhaust_pile_count} cards): none")

        return "\n".join(lines)

    @staticmethod
    def get_card_brief_effect(card: Card) -> str:
        """
        提取单张卡牌的高密度紧凑效果标签（专用于已有牌库画像）
        """
        stats = lookup_card_stats(card.id, card.name, upgraded=card.upgraded)
        raw = stats.get("raw_entry", {})
        dmg = card.damage if card.damage > 0 else stats.get("damage", 0)
        blk = card.block if card.block > 0 else stats.get("block", 0)

        parts: List[str] = []

        if raw.get("body_slam"):
            parts.append("Dmg=Block")
        elif dmg > 0:
            target = raw.get("target", "")
            hits = raw.get("upgrade_hits" if card.upgraded else "hits", raw.get("hits", 1))
            if target == "ALL_ENEMY":
                if card.cost < 0:
                    parts.append(f"{dmg} dmg/E AOE")
                else:
                    parts.append(f"{dmg} dmg AOE")
            elif hits > 1:
                parts.append(f"{dmg}x{hits} dmg")
            else:
                parts.append(f"{dmg} dmg")

        if blk > 0:
            parts.append(f"{blk} blk")

        vuln = raw.get("upgrade_vulnerable" if card.upgraded else "vulnerable")
        if vuln:
            parts.append(f"{vuln} Vuln")

        weak = raw.get("upgrade_weak" if card.upgraded else "weak")
        if weak:
            parts.append(f"{weak} Weak")

        draw = raw.get("upgrade_draw" if card.upgraded else "draw")
        if draw:
            parts.append(f"Draw {draw}")

        str_val = raw.get("upgrade_strength" if card.upgraded else "strength")
        if str_val:
            parts.append(f"+{str_val} Str")

        if raw.get("str_mult"):
            mult = raw.get("upgrade_str_mult" if card.upgraded else "str_mult", 3)
            parts.append(f"Str x{mult}")

        if raw.get("ethereal"):
            parts.append("Ethereal")

        if not parts:
            desc = stats.get("description") or card.description or ""
            clean_d = " ".join(desc.replace("NL", " ").replace("Deal ", "").replace("Gain ", "").split())
            clean_d = re.sub(r"![A-Z]!", "", clean_d).strip(". ")
            if clean_d:
                parts.append(clean_d[:30])
            else:
                parts.append("Standard")

        return ", ".join(parts)

    @staticmethod
    def clean_card_description(c: Card) -> str:
        """
        清洗卡牌描述，优先使用知识库规范描述，并消除游戏原生变量占位符
        """
        stats = lookup_card_stats(c.id, c.name, upgraded=c.upgraded)
        db_desc = stats.get("description", "")
        if db_desc:
            return db_desc

        desc = (c.description or "").strip()
        if not desc:
            effs = []
            if c.damage > 0:
                effs.append(f"Deal {c.damage} dmg")
            if c.block > 0:
                effs.append(f"Gain {c.block} blk")
            return ", ".join(effs) if effs else "Standard effect"

        # 替换 CommunicationMod 占位符与换行
        desc = desc.replace("NL", " ").replace("  ", " ")
        if c.damage > 0:
            desc = desc.replace("!D!", str(c.damage))
        if c.block > 0:
            desc = desc.replace("!B!", str(c.block))
        desc = re.sub(r"![A-Z]!", "", desc).strip()
        return desc

    @staticmethod
    def compress_deck_summary(deck: List[Card]) -> List[str]:
        """
        生成无截断的结构化卡组画像：
        - 统计卡组总量、攻击/技能/能力/诅咒数量及升级比例；
        - 按卡牌类型分类，并按卡牌名称和升级状态聚合计数；
        - 标明费用、伤害/格挡/关键效果简述。
        """
        if not deck:
            return ["CURRENT DECK (0 cards): empty"]

        total = len(deck)
        upgraded_count = sum(1 for c in deck if getattr(c, "upgraded", False))

        attacks = [c for c in deck if c.type == "ATTACK"]
        skills = [c for c in deck if c.type == "SKILL"]
        powers = [c for c in deck if c.type == "POWER"]
        curses = [c for c in deck if c.type in ["CURSE", "STATUS"]]

        header = (
            f"CURRENT DECK STATUS ({total} cards | "
            f"{len(attacks)} Attacks, {len(skills)} Skills, {len(powers)} Powers"
            + (f", {len(curses)} Curses/Status" if curses else "")
            + f" | Upgrades: {upgraded_count}/{total}):"
        )

        lines = [header]

        def format_card_group(group: List[Card], group_label: str) -> Optional[str]:
            if not group:
                return None

            counts: Dict[Tuple[str, str, str], int] = OrderedDict()
            for c in group:
                display_name = f"{c.name}+" if getattr(c, "upgraded", False) else c.name
                cost_str = f"{c.cost}E" if c.cost >= 0 else "XE"
                summary = StateCompressor.get_card_brief_effect(c)
                key = (display_name, cost_str, summary)
                counts[key] = counts.get(key, 0) + 1

            group_items = []
            for (name, cost, summary), cnt in counts.items():
                cnt_str = f" x{cnt}" if cnt > 1 else ""
                group_items.append(f"{name}{cnt_str} [{cost}] ({summary})")

            return f"- {group_label} ({len(group)}): " + "; ".join(group_items)

        att_line = format_card_group(attacks, "ATTACKS")
        if att_line:
            lines.append(att_line)

        ski_line = format_card_group(skills, "SKILLS")
        if ski_line:
            lines.append(ski_line)

        pow_line = format_card_group(powers, "POWERS")
        if pow_line:
            lines.append(pow_line)

        cur_line = format_card_group(curses, "CURSES/STATUS")
        if cur_line:
            lines.append(cur_line)

        return lines

    @staticmethod
    def compress_card_reward(
        deck: List[Card],
        relics: List[str],
        offered_cards: List[Card],
        can_skip: bool = True,
    ) -> str:
        lines: List[str] = []
        lines.append("=== CARD REWARD SELECTION ===")

        # 结构化牌库画像（完整展示，无 Top 10 截断，含费用、升级状态与紧凑机制标签）
        deck_lines = StateCompressor.compress_deck_summary(deck)
        lines.extend(deck_lines)

        relics_str = ", ".join(relics[:8]) if relics else "none"
        lines.append(f"RELICS: [{relics_str}]")

        lines.append("\nOFFERED CARDS:")
        for idx, c in enumerate(offered_cards):
            cost_str = f"{c.cost}E" if c.cost >= 0 else "XE"
            clean_desc = StateCompressor.clean_card_description(c)
            lines.append(f"* [card_{idx}] {c.name} ({cost_str}, {c.type}) -> {clean_desc}")

        if can_skip:
            lines.append("* [skip] Skip card reward (avoid diluting deck)")

        return "\n".join(lines)

    @staticmethod
    def compress_map_selection(
        current_hp: int,
        max_hp: int,
        gold: int,
        floor: int,
        act: int,
        next_nodes: List[Any],
        boss_available: bool = False,
    ) -> str:
        lines: List[str] = []
        lines.append(f"=== MAP ROUTE NAVIGATION (Act {act}, Floor {floor}) ===")
        hp_pct = int((current_hp / max_hp * 100)) if max_hp > 0 else 0
        lines.append(f"PLAYER STATUS: HP {current_hp}/{max_hp} ({hp_pct}%) | Gold {gold}G")

        lines.append("AVAILABLE PATHS:")
        if boss_available:
            lines.append("* [boss] ACT BOSS ROOM (Climax battle)")
        else:
            for idx, node in enumerate(next_nodes):
                symbol = getattr(node, "symbol", node.get("symbol", "?") if isinstance(node, dict) else "?")
                desc = getattr(node, "description", symbol)
                lines.append(f"* [node_{idx}] {desc} (coords: x={getattr(node, 'x', '?')}, y={getattr(node, 'y', '?')})")

        return "\n".join(lines)

    @staticmethod
    def compress_event(
        event_id: str,
        body_text: str,
        options: List[Dict[str, Any]],
        current_hp: int,
        max_hp: int,
        gold: int,
        floor: int,
        deck: List[Card],
        relics: List[str],
    ) -> str:
        lines: List[str] = []
        lines.append(f"=== EVENT ENCOUNTER (Floor {floor}) ===")
        lines.append(f"EVENT_ID: {event_id}")
        relic_str = ", ".join(relics[:8]) if relics else "none"
        hp_pct = int(current_hp / max_hp * 100) if max_hp > 0 else 100
        lines.append(f"PLAYER STATUS: HP {current_hp}/{max_hp} ({hp_pct}%) | Gold {gold}G | Deck Size: {len(deck)} | Relics: [{relic_str}]")
        if body_text:
            clean_body = " ".join(body_text.strip().split())
            lines.append(f"NARRATIVE: {clean_body}")

        lines.append("OPTIONS:")
        for idx, opt in enumerate(options):
            label = opt.get("label", f"Option {idx}")
            disabled = opt.get("disabled", False)
            status_tag = " (DISABLED)" if disabled else " (AVAILABLE)"
            lines.append(f"- [{idx}]: {label}{status_tag}")

        return "\n".join(lines)

    @staticmethod
    def compress_shop(
        gold: int,
        cards: List[Dict[str, Any]],
        relics: List[Dict[str, Any]],
        potions: List[Dict[str, Any]],
        purge_available: bool,
        purge_cost: int,
        floor: int,
        deck: List[Card],
        current_relics: List[str],
        potion_slots_open: int,
    ) -> str:
        lines: List[str] = []
        lines.append(f"=== MERCHANT SHOP (Floor {floor}) ===")
        relic_str = ", ".join(current_relics[:8]) if current_relics else "none"
        lines.append(
            f"STATUS: Gold {gold}G | Deck Size: {len(deck)} | Potion Slots Open: {potion_slots_open} | Relics: [{relic_str}]"
        )

        # 1. 删牌服务
        if purge_available:
            p_tag = "AVAILABLE" if gold >= purge_cost else "UNAFFORDABLE (Insufficient Gold)"
            lines.append(f"CARD REMOVAL SERVICE: {purge_cost}G ({p_tag}) -> Remove 1 basic or curse card from deck")
        else:
            lines.append("CARD REMOVAL SERVICE: USED / UNAVAILABLE")

        # 2. 遗物
        lines.append("RELICS ON SALE:")
        if not relics:
            lines.append("  (None)")
        else:
            for idx, r in enumerate(relics):
                name = r.get("name", r.get("id", f"Relic_{idx}"))
                price = r.get("price", 999)
                desc = r.get("description", "")
                tag = "AFFORDABLE" if gold >= price else "UNAFFORDABLE"
                desc_str = f" -> {desc}" if desc else ""
                lines.append(f"- [relic_{idx}]: {name} ({price}G, {tag}){desc_str}")

        # 3. 卡牌
        lines.append("CARDS ON SALE:")
        if not cards:
            lines.append("  (None)")
        else:
            for idx, c in enumerate(cards):
                name = c.get("name", c.get("id", f"Card_{idx}"))
                price = c.get("price", 999)
                cost = c.get("cost", 1)
                ctype = c.get("type", "SKILL")
                tag = "AFFORDABLE" if gold >= price else "UNAFFORDABLE"
                desc = c.get("raw_description", "")
                desc_str = f" -> {desc}" if desc else ""
                lines.append(f"- [card_{idx}]: {name} ({cost}E, {ctype}) - {price}G ({tag}){desc_str}")

        # 4. 药水
        lines.append("POTIONS ON SALE:")
        if not potions:
            lines.append("  (None)")
        else:
            for idx, p in enumerate(potions):
                name = p.get("name", p.get("id", f"Potion_{idx}"))
                price = p.get("price", 999)
                can_buy = gold >= price and potion_slots_open > 0
                tag = "AFFORDABLE" if can_buy else ("NO SLOTS" if potion_slots_open <= 0 else "UNAFFORDABLE")
                lines.append(f"- [potion_{idx}]: {name} ({price}G, {tag})")

        return "\n".join(lines)

    @staticmethod
    def compress_rest(
        current_hp: int,
        max_hp: int,
        floor: int,
        act: int,
        rest_options: List[str],
        deck: List[Card],
        relics: List[str],
    ) -> str:
        lines: List[str] = []
        lines.append(f"=== REST SITE / CAMPFIRE (Floor {floor} | Act {act}) ===")
        hp_pct = int(current_hp / max_hp * 100) if max_hp > 0 else 100
        relic_str = ", ".join(relics[:8]) if relics else "none"
        heal_amt = int(max_hp * 0.3)
        projected_hp = min(max_hp, current_hp + heal_amt)
        lines.append(
            f"PLAYER STATUS: HP {current_hp}/{max_hp} ({hp_pct}%) | Deck Size: {len(deck)} | Relics: [{relic_str}]"
        )

        unupgraded_count = sum(
            1 for c in deck if not getattr(c, "upgraded", False) and getattr(c, "type", "") not in ["CURSE", "STATUS"]
        )
        upgraded_count = sum(1 for c in deck if getattr(c, "upgraded", False))
        lines.append(f"DECK STATUS: {upgraded_count} upgraded cards, {unupgraded_count} unupgraded candidates")

        lines.append("AVAILABLE ACTIONS:")
        action_descriptions = {
            "REST": f"Heal 30% Max HP (+{heal_amt} HP -> {projected_hp}/{max_hp})",
            "SMITH": "Upgrade a card from your deck (Boost key card value/damage/block)",
            "DIG": "Dig for a random Relic (from Shovel relic)",
            "LIFT": "Gain +1 permanent Strength (from Girya relic, up to 3 times)",
            "TOKE": "Purge/Remove a card from deck (from Peace Pipe relic)",
            "RECALL": "Obtain Ruby Key piece (Required for Act 4 Heart)",
        }

        for idx, opt in enumerate(rest_options):
            opt_upper = str(opt).upper()
            desc = action_descriptions.get(opt_upper, f"Custom action: {opt}")
            lines.append(f"- [{idx}]: {opt_upper} -> {desc}")

        return "\n".join(lines)

    @classmethod
    def from_communication_mod_json(cls, raw: Dict[str, Any]) -> CombatState:
        game_state = raw.get("game_state", raw)
        combat_state = game_state.get("combat_state") or raw.get("combat_state") or raw

        raw_player = combat_state.get("player", {})
        player_powers = [
            Power(id=pw.get("id", ""), name=pw.get("name", pw.get("id", "")), amount=pw.get("amount", 0))
            for pw in raw_player.get("powers", [])
        ]
        relics = [r.get("name", r.get("id", "")) for r in game_state.get("relics", [])]

        player = Player(
            current_hp=raw_player.get("current_hp", 0),
            max_hp=raw_player.get("max_hp", 0),
            energy=raw_player.get("energy", 0),
            block=raw_player.get("block", 0),
            powers=player_powers,
            relics=relics,
        )

        monsters: List[Monster] = []
        for idx, m in enumerate(combat_state.get("monsters", [])):
            m_powers = [
                Power(id=pw.get("id", ""), name=pw.get("name", pw.get("id", "")), amount=pw.get("amount", 0))
                for pw in m.get("powers", [])
            ]
            monsters.append(
                Monster(
                    index=idx,
                    id=m.get("id", ""),
                    name=m.get("name", f"Monster_{idx}"),
                    current_hp=m.get("current_hp", 0),
                    max_hp=m.get("max_hp", 0),
                    block=m.get("block", 0),
                    intent=m.get("intent", "UNKNOWN"),
                    move_damage=max(0, m.get("move_adjusted_damage", m.get("move_base_damage", 0))),
                    move_hits=m.get("move_hits", 1),
                    powers=m_powers,
                    is_gone=m.get("is_gone", False),
                    half_dead=m.get("half_dead", False),
                )
            )

        hand: List[Card] = []
        for idx, c in enumerate(combat_state.get("hand", [])):
            c_id = c.get("id", "")
            c_name = c.get("name", f"Card_{idx}")
            upgraded = c.get("upgrades", 0) > 0

            # 从 cards_db 知识库回填真实数值（补齐 CommunicationMod 协议缺失）
            stats = lookup_card_stats(c_id, c_name, upgraded=upgraded)
            dmg = c.get("damage") if c.get("damage") is not None and c.get("damage") > 0 else stats["damage"]
            blk = c.get("block") if c.get("block") is not None and c.get("block") > 0 else stats["block"]
            desc = c.get("raw_description") or stats["description"]
            c_type = c.get("type") or stats.get("type", "SKILL")

            raw_target = str(c.get("target", "")).upper()
            raw_entry = stats.get("raw_entry", {})
            db_target = str(raw_entry.get("target", "")).upper()
            is_aoe = raw_target in ["ALL_ENEMY", "ALL"] or db_target in ["ALL_ENEMY", "ALL"]

            if is_aoe:
                target_type = "ALL_ENEMY"
                has_target = False
            elif c.get("has_target", False) or raw_target in ["ENEMY", "SELF_AND_ENEMY"] or db_target in ["ENEMY", "SELF_AND_ENEMY"]:
                target_type = "ENEMY"
                has_target = True
            elif raw_target == "SELF" or db_target == "SELF":
                target_type = "SELF"
                has_target = False
            else:
                target_type = "NONE"
                has_target = False

            if c_type == "ATTACK" and not is_aoe:
                has_target = True
                target_type = "ENEMY"

            hand.append(
                Card(
                    index=idx,
                    id=c_id,
                    name=c_name,
                    cost=c.get("cost", 1),
                    type=c_type,
                    target_type=target_type,
                    has_target=has_target,
                    is_playable=c.get("is_playable", True),
                    damage=dmg,
                    block=blk,
                    description=desc,
                    upgraded=upgraded,
                )
            )

        potions: List[Potion] = []
        for idx, pot in enumerate(game_state.get("potions", [])):
            potions.append(
                Potion(
                    index=idx,
                    id=pot.get("id", ""),
                    name=pot.get("name", f"Potion_{idx}"),
                    can_use=pot.get("can_use", False),
                    can_discard=pot.get("can_discard", False),
                    requires_target=pot.get("requires_target", False),
                )
            )

        draw_pile_cards = [
            c.get("name", c.get("id", ""))
            for c in combat_state.get("draw_pile", [])
            if c.get("name") or c.get("id")
        ]
        discard_pile_cards = [
            c.get("name", c.get("id", ""))
            for c in combat_state.get("discard_pile", [])
            if c.get("name") or c.get("id")
        ]
        exhaust_pile_cards = [
            c.get("name", c.get("id", ""))
            for c in combat_state.get("exhaust_pile", [])
            if c.get("name") or c.get("id")
        ]

        return CombatState(
            turn=combat_state.get("turn", 1),
            player=player,
            monsters=monsters,
            hand=hand,
            potions=potions,
            draw_pile=draw_pile_cards,
            discard_pile=discard_pile_cards,
            exhaust_pile=exhaust_pile_cards,
            draw_pile_count=len(combat_state.get("draw_pile", [])),
            discard_pile_count=len(combat_state.get("discard_pile", [])),
            exhaust_pile_count=len(combat_state.get("exhaust_pile", [])),
        )

    @classmethod
    def from_communication_mod_full_json(cls, raw: Dict[str, Any]) -> FullGameState:
        game_state = raw.get("game_state", raw)
        screen_type = game_state.get("screen_type", "NONE")
        screen_state = game_state.get("screen_state", {})

        deck: List[Card] = []
        for idx, c in enumerate(game_state.get("deck", [])):
            c_id = c.get("id", "")
            c_name = c.get("name", f"Card_{idx}")
            upgraded = c.get("upgrades", 0) > 0
            stats = lookup_card_stats(c_id, c_name, upgraded=upgraded)
            dmg = c.get("damage") if c.get("damage") is not None and c.get("damage") > 0 else stats["damage"]
            blk = c.get("block") if c.get("block") is not None and c.get("block") > 0 else stats["block"]
            desc = c.get("raw_description") or stats["description"]

            deck.append(
                Card(
                    index=idx,
                    id=c_id,
                    name=c_name,
                    cost=c.get("cost", 1),
                    type=c.get("type", "SKILL"),
                    damage=dmg,
                    block=blk,
                    description=desc,
                    upgraded=upgraded,
                )
            )

        relics = [r.get("name", r.get("id", "")) for r in game_state.get("relics", [])]
        potions: List[Potion] = [
            Potion(
                index=idx,
                id=pot.get("id", ""),
                name=pot.get("name", f"Potion_{idx}"),
                can_use=pot.get("can_use", False),
                can_discard=pot.get("can_discard", False),
                requires_target=pot.get("requires_target", False),
            )
            for idx, pot in enumerate(game_state.get("potions", []))
        ]

        combat_state = None
        if "combat_state" in game_state and game_state.get("combat_state"):
            combat_state = cls.from_communication_mod_json(raw)

        return FullGameState(
            screen_type=screen_type,
            screen_state=screen_state,
            available_commands=raw.get("available_commands", []),
            choice_list=game_state.get("choice_list", []),
            ready_for_command=raw.get("ready_for_command", True),
            in_game=raw.get("in_game", True),
            floor=game_state.get("floor", 0),
            act=game_state.get("act", 1),
            gold=game_state.get("gold", 0),
            current_hp=game_state.get("current_hp", 0),
            max_hp=game_state.get("max_hp", 0),
            deck=deck,
            relics=relics,
            potions=potions,
            combat_state=combat_state,
            is_screen_up=game_state.get("is_screen_up", False),
        )

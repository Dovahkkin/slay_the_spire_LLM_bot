from typing import Dict, Any, List, Optional
from .base import BaseTool, ToolResult
from ..models import CombatState, Card, Monster


class DamageCalculatorTool(BaseTool):
    """
    精准伤害与格挡试算器：
    根据给定的出牌顺序和目标怪物，精准计算真实输出、格挡获得量、剩余能量以及怪物是否阵亡。
    自动考虑力量、敏捷、易伤（1.5倍）、虚弱（0.75倍）与护甲抵扣。
    """

    @property
    def name(self) -> str:
        return "calculate_card_sequence"

    @property
    def description(self) -> str:
        return (
            "精准试算按指定顺序打出一组手牌后的战斗效果。"
            "返回包括：总消耗能量、产生总伤害、获得总护甲、目标怪物扣除护甲后的剩余生命值，以及是否能斩杀该目标。"
        )

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "card_indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "准备依次打出的手牌索引列表 (从 0 开始)",
                },
                "target_enemy_index": {
                    "type": "integer",
                    "description": "单体攻击的目标敌人索引 (默认为 0)",
                    "default": 0,
                },
            },
            "required": ["card_indices"],
        }

    def execute(self, params: Dict[str, Any], context: Optional[CombatState] = None) -> ToolResult:
        if not context:
            return ToolResult(success=False, data={}, error="缺少战场 CombatState 上下文，无法试算。")

        card_indices: List[int] = params.get("card_indices", [])
        target_idx: int = params.get("target_enemy_index", 0)

        # 校验目标怪物
        target_m = next((m for m in context.alive_monsters if m.index == target_idx), None)
        if not target_m and context.alive_monsters:
            target_m = context.alive_monsters[0]

        if not target_m:
            return ToolResult(success=False, data={}, error="场上无存活敌人。")

        # 初始状态
        cur_energy = context.player.energy
        cur_player_block = context.player.block
        target_hp = target_m.current_hp
        target_block = target_m.block

        # 提取玩家力量
        p_strength = sum(pw.amount for pw in context.player.powers if pw.id == "Strength")
        p_dexterity = sum(pw.amount for pw in context.player.powers if pw.id == "Dexterity")
        p_is_weak = any(pw.id == "Weak" and pw.amount > 0 for pw in context.player.powers)

        # 目标状态
        target_is_vuln = any(pw.id == "Vulnerable" and pw.amount > 0 for pw in target_m.powers)

        total_damage_dealt = 0
        total_block_gained = 0
        total_cost = 0
        simulated_steps = []

        hand_map = {c.index: c for c in context.hand}

        for c_idx in card_indices:
            card = hand_map.get(c_idx)
            if not card:
                return ToolResult(success=False, data={}, error=f"手牌中不存在索引为 {c_idx} 的卡牌。")

            total_cost += card.cost

            # 模拟活动肌肉 (Flex) 力量增加
            c_name_lower = card.name.lower()
            if "flex" in c_name_lower:
                p_strength += (4 if card.upgraded else 2)

            # 格挡计算
            card_block = 0
            if card.block > 0:
                card_block = max(0, card.block + p_dexterity)
                cur_player_block += card_block
                total_block_gained += card_block

            # 伤害计算
            card_damage = 0
            if card.damage > 0:
                base = card.damage + p_strength
                if p_is_weak:
                    base = int(base * 0.75)
                if target_is_vuln:
                    base = int(base * 1.5)
                card_damage = max(0, base)

                # 破盾与扣血
                absorbed = min(target_block, card_damage)
                target_block -= absorbed
                hp_loss = card_damage - absorbed
                target_hp = max(0, target_hp - hp_loss)
                total_damage_dealt += card_damage

                # 若卡牌附加易伤 (如痛击 Bash)
                if "vulnerable" in (card.description or "").lower() or card.id == "Bash":
                    target_is_vuln = True

            simulated_steps.append({
                "card": card.name,
                "cost": card.cost,
                "damage_dealt": card_damage,
                "block_gained": card_block,
                "target_remaining_hp": target_hp,
                "target_remaining_block": target_block,
            })

        energy_valid = total_cost <= cur_energy
        is_lethal = target_hp <= 0

        data = {
            "valid_energy": energy_valid,
            "energy_needed": total_cost,
            "energy_available": cur_energy,
            "total_damage": total_damage_dealt,
            "total_block_gained": total_block_gained,
            "resulting_player_block": cur_player_block,
            "target_final_hp": target_hp,
            "target_final_block": target_block,
            "target_killed": is_lethal,
            "steps": simulated_steps,
        }

        return ToolResult(success=True, data=data)

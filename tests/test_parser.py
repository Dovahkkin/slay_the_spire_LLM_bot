import unittest
from spire_agent.models import CombatState, Player, Monster, Card, PlayCardAction, EndTurnAction, UsePotionAction, Potion
from spire_agent.combat_session import CombatSession, AmbiguousTargetError
from spire_agent.compressor import StateCompressor
from llm_client import SpireLLMClient


class TestPlanParser(unittest.TestCase):
    def setUp(self):
        self.p = Player(current_hp=80, max_hp=80, energy=3, block=0)
        self.m0 = Monster(index=0, id="Louse", name="Red Louse", current_hp=12, max_hp=12, block=0, intent="ATTACK", move_damage=6, move_hits=1)
        self.m1 = Monster(index=1, id="Louse", name="Green Louse", current_hp=11, max_hp=11, block=0, intent="ATTACK", move_damage=7, move_hits=1)
        self.cards = [
            Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=1, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=2, id="Defend_R", name="Defend", cost=1, type="SKILL", block=5),
            Card(index=3, id="Bash", name="Bash", cost=2, type="ATTACK", damage=8),
        ]
        self.multi_enemy_state = CombatState(turn=1, player=self.p, monsters=[self.m0, self.m1], hand=self.cards)
        self.single_enemy_state = CombatState(turn=1, player=self.p, monsters=[self.m0], hand=self.cards)
        self.client = SpireLLMClient()
        self.session = CombatSession(self.client)

    def test_parse_card_name_strike(self):
        text = "推演说明：打出两张打击消灭左侧敌人。\n```plan\nPLAY Strike 0\nPLAY Strike 0\nEND\n```"
        plan = self.session._parse_plan_from_text(text, self.multi_enemy_state)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.actions), 3)
        self.assertIsInstance(plan.actions[0], PlayCardAction)
        self.assertEqual(plan.actions[0].card_index, 0)
        self.assertEqual(plan.actions[0].target_index, 0)
        self.assertIsInstance(plan.actions[1], PlayCardAction)
        self.assertEqual(plan.actions[1].card_index, 1)
        self.assertEqual(plan.actions[1].target_index, 0)
        self.assertIsInstance(plan.actions[2], EndTurnAction)

    def test_parse_c_prefix_and_bracket(self):
        text = "```plan\nPLAY [c0] [E0]\nPLAY [c1] [E1]\nEND\n```"
        plan = self.session._parse_plan_from_text(text, self.multi_enemy_state)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.actions), 3)
        self.assertEqual(plan.actions[0].card_index, 0)
        self.assertEqual(plan.actions[0].target_index, 0)
        self.assertEqual(plan.actions[1].card_index, 1)
        self.assertEqual(plan.actions[1].target_index, 1)

    def test_single_enemy_missing_target_auto_defaults(self):
        # 仅有 1 个存活敌人时，单体攻击卡缺失目标自动默认兜底至 E0
        text = "```plan\nPLAY Strike\nEND\n```"
        plan = self.session._parse_plan_from_text(text, self.single_enemy_state)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.actions), 2)
        self.assertEqual(plan.actions[0].target_index, 0)
        self.assertEqual(plan.actions[0].raw_command, "PLAY 1 0")

    def test_multi_enemy_missing_target_raises_ambiguous_error(self):
        # 存在 2 个以上存活敌人时，单体攻击卡缺失目标抛出 AmbiguousTargetError 异常，以便向大模型反馈重选
        text = "```plan\nPLAY Strike\nEND\n```"
        with self.assertRaises(AmbiguousTargetError):
            self.session._parse_plan_from_text(text, self.multi_enemy_state)

    def test_chinese_card_name(self):
        text = "```plan\nPLAY 打击 0\nPLAY 防御\nEND\n```"
        plan = self.session._parse_plan_from_text(text, self.multi_enemy_state)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.actions), 3)
        self.assertEqual(plan.actions[0].card_index, 0)
        self.assertEqual(plan.actions[1].card_index, 2)
        self.assertIsNone(plan.actions[1].target_index)

    def test_aoe_card_multi_enemy_does_not_raise_ambiguous_error(self):
        # 存在 2 个以上存活敌人时，打出 AOE 群攻卡（如 Thunderclap / Cleave）不需要指定目标，不应抛出 AmbiguousTargetError
        aoe_card = Card(index=4, id="Thunderclap", name="Thunderclap", cost=1, type="ATTACK", target_type="ALL_ENEMY", damage=4)
        state_with_aoe = CombatState(
            turn=1,
            player=self.p,
            monsters=[self.m0, self.m1],
            hand=self.cards + [aoe_card],
        )
        text = "```plan\nPLAY Thunderclap\nEND\n```"
        plan = self.session._parse_plan_from_text(text, state_with_aoe)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.actions), 2)
        self.assertEqual(plan.actions[0].card_index, 4)
        self.assertIsNone(plan.actions[0].target_index)
        self.assertEqual(plan.actions[0].raw_command, "PLAY 5")

    def test_communication_mod_json_thunderclap_is_aoe(self):
        # 即使 CommunicationMod 的手牌 json 缺失 target 字段且 has_target=False，
        # StateCompressor 也应结合 cards_db 知识库将 Thunderclap 正确识别为 ALL_ENEMY 且 has_target=False
        raw_json = {
            "in_combat": True,
            "turn": 1,
            "player": {"current_hp": 80, "max_hp": 80, "energy": 3, "block": 0, "powers": [], "relics": []},
            "monsters": [
                {"id": "FungiBeast", "name": "Fungi Beast", "current_hp": 22, "max_hp": 22, "block": 0, "intent": "ATTACK", "move_adjusted_damage": 6, "powers": []},
                {"id": "FungiBeast", "name": "Fungi Beast", "current_hp": 25, "max_hp": 25, "block": 0, "intent": "ATTACK", "move_adjusted_damage": 6, "powers": []},
            ],
            "hand": [
                {"id": "Thunderclap", "name": "Thunderclap", "cost": 1, "type": "ATTACK", "has_target": False},
                {"id": "Cleave", "name": "Cleave", "cost": 1, "type": "ATTACK", "has_target": False},
                {"id": "Strike_R", "name": "Strike", "cost": 1, "type": "ATTACK", "has_target": True},
            ]
        }
        state = StateCompressor.from_communication_mod_json(raw_json)
        self.assertEqual(state.hand[0].name, "Thunderclap")
        self.assertEqual(state.hand[0].target_type, "ALL_ENEMY")
        self.assertFalse(state.hand[0].has_target)

        self.assertEqual(state.hand[1].name, "Cleave")
        self.assertEqual(state.hand[1].target_type, "ALL_ENEMY")
        self.assertFalse(state.hand[1].has_target)

        self.assertEqual(state.hand[2].name, "Strike")
        self.assertEqual(state.hand[2].target_type, "ENEMY")
        self.assertTrue(state.hand[2].has_target)

    def test_parse_use_potion_buff(self):
        # 测试自身增益类药水（无目标）
        pot = Potion(index=0, id="FlexPotion", name="Flex Potion", can_use=True, requires_target=False)
        state_with_pot = CombatState(
            turn=1,
            player=self.p,
            monsters=[self.m0, self.m1],
            hand=self.cards,
            potions=[pot]
        )
        text = "```plan\nUSE p0\nPLAY Strike 0\nEND\n```"
        plan = self.session._parse_plan_from_text(text, state_with_pot)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.actions), 3)
        self.assertIsInstance(plan.actions[0], UsePotionAction)
        self.assertEqual(plan.actions[0].potion_index, 0)
        self.assertIsNone(plan.actions[0].target_index)
        self.assertEqual(plan.actions[0].raw_command, "POTION USE 0")
        self.assertIsInstance(plan.actions[1], PlayCardAction)
        self.assertEqual(plan.actions[1].card_index, 0)

    def test_parse_use_potion_targeted(self):
        # 测试指定目标类药水（如火焰药水）
        fire_pot = Potion(index=1, id="FirePotion", name="Fire Potion", can_use=True, requires_target=True)
        state_with_fire = CombatState(
            turn=1,
            player=self.p,
            monsters=[self.m0, self.m1],
            hand=self.cards,
            potions=[Potion(index=0, id="Slot", name="Slot", can_use=False), fire_pot]
        )
        text = "```plan\nUSE p1 E1\nEND\n```"
        plan = self.session._parse_plan_from_text(text, state_with_fire)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.actions), 2)
        self.assertIsInstance(plan.actions[0], UsePotionAction)
        self.assertEqual(plan.actions[0].potion_index, 1)
        self.assertEqual(plan.actions[0].target_index, 1)
        self.assertEqual(plan.actions[0].raw_command, "POTION USE 1 1")

    def test_parse_potion_syntax_variations(self):
        # 兼容 POTION USE 0 / POTION 0 / USE 0 多种别名语法
        pot = Potion(index=0, id="FlexPotion", name="Flex Potion", can_use=True, requires_target=False)
        state = CombatState(turn=1, player=self.p, monsters=[self.m0], hand=self.cards, potions=[pot])
        
        for cmd_line in ["POTION USE 0", "POTION 0", "USE 0", "USE [p0]"]:
            text = f"```plan\n{cmd_line}\nEND\n```"
            plan = self.session._parse_plan_from_text(text, state)
            self.assertIsNotNone(plan)
            self.assertIsInstance(plan.actions[0], UsePotionAction)
            self.assertEqual(plan.actions[0].potion_index, 0)


if __name__ == "__main__":
    unittest.main()

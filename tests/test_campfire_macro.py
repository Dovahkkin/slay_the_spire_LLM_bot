import unittest
from unittest.mock import MagicMock
from spire_agent.models import FullGameState, Card, ChooseAction, ProceedAction
from spire_agent.compressor import StateCompressor
from spire_agent.macro_session import MacroSession
from spire_agent.agent import SpireAgent
from llm_client import SpireLLMClient


class TestCampfireMacro(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock(spec=SpireLLMClient)
        self.mock_client.is_available = True
        self.macro = MacroSession(llm_client=self.mock_client)
        self.cards = [
            Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=1, id="Defend_R", name="Defend", cost=1, type="SKILL", block=5),
            Card(index=2, id="Whirlwind", name="Whirlwind", cost=-1, type="ATTACK", damage=5),
            Card(index=3, id="Inflame", name="Inflame", cost=1, type="POWER"),
        ]

    def test_compress_rest_output(self):
        """测试营地压缩状态文本生成正确性"""
        text = StateCompressor.compress_rest(
            current_hp=56,
            max_hp=80,
            floor=6,
            act=1,
            rest_options=["REST", "SMITH", "DIG"],
            deck=self.cards,
            relics=["Burning Blood", "Shovel"],
        )
        self.assertIn("=== REST SITE / CAMPFIRE (Floor 6 | Act 1) ===", text)
        self.assertIn("HP 56/80 (70%)", text)
        self.assertIn("REST -> Heal 30%", text)
        self.assertIn("SMITH -> Upgrade a card", text)
        self.assertIn("DIG -> Dig for a random Relic", text)

    def test_decide_rest_llm_choice(self):
        """测试大模型自主决定营地行动（如锻造 SMITH）"""
        state = FullGameState(
            screen_type="REST",
            floor=6,
            act=1,
            current_hp=65,
            max_hp=80,
            deck=self.cards,
            screen_state={"rest_options": ["rest", "smith"], "has_rested": False},
            available_commands=["choose"],
        )
        self.mock_client.run_react_turn.return_value = (
            "We have high HP (65/80) and need to upgrade Whirlwind for upcoming Elite.\n"
            "```action\nCHOOSE smith\n```"
        )
        action = self.macro.decide_rest(state)
        self.assertIsInstance(action, ChooseAction)
        self.assertEqual(action.choice, "smith")

    def test_decide_rest_special_relic_dig(self):
        """测试拥有铲子遗物时，模型可选择 DIG 挖宝"""
        state = FullGameState(
            screen_type="REST",
            floor=10,
            act=1,
            current_hp=70,
            max_hp=80,
            deck=self.cards,
            screen_state={"rest_options": ["rest", "smith", "dig"], "has_rested": False},
            available_commands=["choose"],
        )
        self.mock_client.run_react_turn.return_value = (
            "With 70 HP and Shovel available, digging for a free relic provides maximum scaling value.\n"
            "```action\nCHOOSE dig\n```"
        )
        action = self.macro.decide_rest(state)
        self.assertIsInstance(action, ChooseAction)
        self.assertEqual(action.choice, "dig")

    def test_decide_rest_single_option_fast_path(self):
        """测试营地仅有单选项时的 0-token 直通"""
        state = FullGameState(
            screen_type="REST",
            floor=6,
            act=1,
            current_hp=80,
            max_hp=80,
            screen_state={"rest_options": ["smith"], "has_rested": False},
            available_commands=["choose"],
        )
        action = self.macro.decide_rest(state)
        self.assertEqual(action.choice, "smith")
        self.mock_client.run_react_turn.assert_not_called()

    def test_decide_rest_heuristic_fallback(self):
        """测试无模型或异常时的营地启发式保底"""
        self.mock_client.is_available = False
        # 低血量 (< 45%) 必须回血
        low_hp_state = FullGameState(
            screen_type="REST",
            floor=6,
            act=1,
            current_hp=20,
            max_hp=80,
            screen_state={"rest_options": ["rest", "smith"], "has_rested": False},
            available_commands=["choose"],
        )
        action = self.macro.decide_rest(low_hp_state)
        self.assertEqual(action.choice, "rest")

        # 拥有铲子且健康血量 (>= 75%) 优先挖宝
        dig_state = FullGameState(
            screen_type="REST",
            floor=6,
            act=1,
            current_hp=70,
            max_hp=80,
            screen_state={"rest_options": ["rest", "smith", "dig"], "has_rested": False},
            available_commands=["choose"],
        )
        action = self.macro.decide_rest(dig_state)
        self.assertEqual(action.choice, "dig")

        # 正常中等血量优先锻造
        normal_state = FullGameState(
            screen_type="REST",
            floor=6,
            act=1,
            current_hp=50,
            max_hp=80,
            screen_state={"rest_options": ["rest", "smith"], "has_rested": False},
            available_commands=["choose"],
        )
        action = self.macro.decide_rest(normal_state)
        self.assertEqual(action.choice, "smith")

    def test_decide_smith_card_llm(self):
        """测试大模型自主选择锻造升级卡牌（优先选旋风斩）"""
        self.mock_client.run_react_turn.return_value = (
            "Whirlwind+ increases base damage from 5 to 8 per energy, granting superior AoE clear.\n"
            "```action\nCHOOSE 2\n```"
        )
        action = self.macro.decide_smith_card(self.cards, prompt="Select a card to upgrade.")
        self.assertIsInstance(action, ChooseAction)
        self.assertEqual(action.choice, "2")

    def test_decide_smith_card_heuristic_avoids_strikes(self):
        """测试启发式保底选卡升级：绝不优先升级打击/防御，优先升级核心牌"""
        self.mock_client.is_available = False
        action = self.macro.decide_smith_card(self.cards, prompt="Select a card to upgrade.")
        # 候选卡: [0] Strike, [1] Defend, [2] Whirlwind, [3] Inflame
        # Whirlwind 或 Inflame 评分均为 100，排在打击(10)/防御(20)前面
        chosen_idx = int(action.choice)
        chosen_card = self.cards[chosen_idx]
        self.assertIn(chosen_card.name, ["Whirlwind", "Inflame"])
        self.assertNotIn(chosen_card.name, ["Strike", "Defend"])

    def test_agent_routing_rest_and_grid(self):
        """测试 SpireAgent 对 REST 营地与 GRID 锻造/删牌的精准分流"""
        agent = SpireAgent()
        agent.macro_session = MagicMock()

        # 1. REST 界面分流至 decide_rest
        rest_state = FullGameState(
            screen_type="REST",
            screen_state={"rest_options": ["rest", "smith"], "has_rested": False},
            available_commands=["choose"],
        )
        agent.decide_screen_action(rest_state)
        agent.macro_session.decide_rest.assert_called_once_with(rest_state)

        # 2. GRID 升级界面 (prompt: 'Select a card to upgrade') 分流至 decide_smith_card
        grid_upgrade_state = FullGameState(
            screen_type="GRID",
            screen_state={
                "prompt": "Select a card to upgrade",
                "cards": [
                    {"id": "Strike_R", "name": "Strike", "cost": 1, "type": "ATTACK"},
                    {"id": "Bash", "name": "Bash", "cost": 2, "type": "ATTACK"},
                ],
            },
            available_commands=["choose"],
        )
        agent.decide_screen_action(grid_upgrade_state)
        agent.macro_session.decide_smith_card.assert_called_once()

        # 3. GRID 删牌界面 (prompt: 'Choose a card to remove') 分流至 decide_deck_purge_card
        grid_purge_state = FullGameState(
            screen_type="GRID",
            screen_state={
                "prompt": "Choose a card to remove from your deck",
                "cards": [
                    {"id": "Strike_R", "name": "Strike", "cost": 1, "type": "ATTACK"},
                ],
            },
            available_commands=["choose"],
        )
        agent.decide_screen_action(grid_purge_state)
        agent.macro_session.decide_deck_purge_card.assert_called_once()


if __name__ == "__main__":
    unittest.main()

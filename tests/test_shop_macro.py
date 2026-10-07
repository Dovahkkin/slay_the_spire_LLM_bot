import unittest
from unittest.mock import MagicMock
from spire_agent.models import FullGameState, Card, ChooseAction, LeaveAction, Potion
from spire_agent.compressor import StateCompressor
from spire_agent.macro_session import MacroSession


class TestShopMacro(unittest.TestCase):
    def setUp(self):
        self.mock_llm = MagicMock()
        self.mock_llm.is_available = True
        self.macro_session = MacroSession(self.mock_llm)

    def test_compress_shop(self):
        cards = [
            {"id": "Carnage", "name": "Carnage", "cost": 2, "price": 75, "type": "ATTACK", "raw_description": "Deal 20 dmg."},
            {"id": "Apotheosis", "name": "Apotheosis", "cost": 2, "price": 180, "type": "SKILL", "raw_description": "Upgrade all cards."},
        ]
        relics = [
            {"id": "Vajra", "name": "Vajra", "price": 150, "description": "Gain 1 Strength."},
        ]
        potions = [
            {"id": "FirePotion", "name": "Fire Potion", "price": 50},
        ]
        deck = [Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK")]

        compressed = StateCompressor.compress_shop(
            gold=160,
            cards=cards,
            relics=relics,
            potions=potions,
            purge_available=True,
            purge_cost=75,
            floor=8,
            deck=deck,
            current_relics=["Burning Blood"],
            potion_slots_open=1,
        )

        self.assertIn("=== MERCHANT SHOP (Floor 8) ===", compressed)
        self.assertIn("Gold 160G", compressed)
        self.assertIn("CARD REMOVAL SERVICE: 75G (AVAILABLE)", compressed)
        self.assertIn("Vajra (150G, AFFORDABLE)", compressed)
        self.assertIn("Carnage (2E, ATTACK) - 75G (AFFORDABLE)", compressed)
        self.assertIn("Apotheosis (2E, SKILL) - 180G (UNAFFORDABLE)", compressed)
        self.assertIn("Fire Potion (50G, AFFORDABLE)", compressed)

    def test_shop_fast_path_leave_when_broke(self):
        """金币不足以购买任何商品且无法删牌时，应快速离开商店，不浪费 LLM 调用"""
        state = FullGameState(
            screen_type="SHOP_SCREEN",
            screen_state={
                "cards": [{"name": "Carnage", "price": 75}],
                "relics": [{"name": "Vajra", "price": 150}],
                "potions": [{"name": "Potion", "price": 50}],
                "purge_available": False,
                "purge_cost": 75,
            },
            choice_list=["carnage", "vajra", "potion"],
            available_commands=["leave"],
            gold=20,  # 只有 20 块，买不起任何东西
        )

        action = self.macro_session.decide_shop(state)
        self.assertIsInstance(action, LeaveAction)
        self.assertEqual(self.mock_llm.run_react_turn.call_count, 0)

    def test_shop_buy_relic(self):
        """金币充裕时，大模型输出 BUY RELIC 0 购买遗物"""
        state = FullGameState(
            screen_type="SHOP_SCREEN",
            screen_state={
                "cards": [{"name": "Strike", "price": 50}],
                "relics": [{"name": "Vajra", "price": 150}],
                "potions": [],
                "purge_available": True,
                "purge_cost": 75,
            },
            choice_list=["strike", "vajra", "purge"],
            available_commands=["choose", "leave"],
            gold=200,
        )

        self.mock_llm.run_react_turn.return_value = (
            "当前金币 200G，Vajra (150G) 提供常驻力量收益，优先购买。\n```action\nBUY RELIC 0\n```"
        )

        action = self.macro_session.decide_shop(state)
        self.assertIsInstance(action, ChooseAction)
        # 应准确映射到 choice_list 中的 vajra 索引 (1) 或名称
        self.assertIn(action.choice, ["1", 1, "vajra", "Vajra"])
        self.assertEqual(self.macro_session.shop_purchase_count, 1)

    def test_shop_purge_service(self):
        """大模型选择执行单次删牌服务"""
        state = FullGameState(
            screen_type="SHOP_SCREEN",
            screen_state={
                "cards": [],
                "relics": [],
                "potions": [],
                "purge_available": True,
                "purge_cost": 75,
            },
            choice_list=["purge"],
            available_commands=["choose", "leave"],
            gold=100,
        )

        self.mock_llm.run_react_turn.return_value = (
            "卡组基础打击过多，优先购买删牌服务精炼卡组。\n```action\nPURGE\n```"
        )

        action = self.macro_session.decide_shop(state)
        self.assertIsInstance(action, ChooseAction)
        self.assertEqual(action.choice, "0")

    def test_shop_react_retry_on_unaffordable(self):
        """当模型试图购买超出金币预算的商品时，错误信息应回传模型进行下一轮 ReAct 纠错"""
        state = FullGameState(
            screen_type="SHOP_SCREEN",
            screen_state={
                "cards": [{"name": "Spot Weakness", "price": 60}],
                "relics": [{"name": "Calipers", "price": 280}],
                "potions": [],
                "purge_available": False,
            },
            choice_list=["spot weakness", "calipers"],
            available_commands=["choose", "leave"],
            gold=80,  # 买不起 Calipers (280)
        )

        # 第 1 轮企图购买 Calipers；第 2 轮在接收报错后纠正为买不起，选择买 Spot Weakness
        self.mock_llm.run_react_turn.side_effect = [
            "我想买 Calipers 遗物。\n```action\nBUY RELIC 0\n```",
            "预算不足，那我买 Spot Weakness。\n```action\nBUY CARD 0\n```",
        ]

        action = self.macro_session.decide_shop(state)
        self.assertIsInstance(action, ChooseAction)
        self.assertEqual(self.mock_llm.run_react_turn.call_count, 2)

    def test_deck_purge_curse_priority(self):
        """非战斗全卡组删牌界面中，优先删除诅咒牌"""
        cards = [
            Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK"),
            Card(index=1, id="Pain", name="Pain", cost=0, type="CURSE"),
            Card(index=2, id="Defend_R", name="Defend", cost=1, type="SKILL"),
        ]

        action = self.macro_session.decide_deck_purge_card(cards)
        self.assertIsInstance(action, ChooseAction)
        # 应该优先选择 Pain 诅咒 (索引 1)
        self.assertEqual(action.choice, "1")

    def test_deck_purge_strike_priority(self):
        """无诅咒时，常规流派优先删除基础打击"""
        cards = [
            Card(index=0, id="Defend_R", name="Defend", cost=1, type="SKILL"),
            Card(index=1, id="Strike_R", name="Strike", cost=1, type="ATTACK"),
        ]

        action = self.macro_session.decide_deck_purge_card(cards)
        self.assertIsInstance(action, ChooseAction)
        # 应该选择 Strike (索引 1)
        self.assertEqual(action.choice, "1")


if __name__ == "__main__":
    unittest.main()

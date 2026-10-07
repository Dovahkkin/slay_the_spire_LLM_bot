import unittest
from unittest.mock import MagicMock
from spire_agent.models import FullGameState, Card, ChooseAction, LeaveAction
from spire_agent.macro_session import MacroSession
from spire_agent.agent import SpireAgent
from llm_client import SpireLLMClient


class TestMacroRoomHistory(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock(spec=SpireLLMClient)
        self.mock_client.is_available = True
        self.macro = MacroSession(llm_client=self.mock_client)
        self.cards = [
            Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=1, id="Bash", name="Bash", cost=2, type="ATTACK", damage=8),
        ]

    def test_campfire_to_smith_room_history_persistence(self):
        """测试在同一营地房间内，从决定锻造 (decide_rest) 到选择卡牌 (decide_smith_card) 会话记忆连贯"""
        # 1. 营地休整选择锻造
        rest_state = FullGameState(
            screen_type="REST",
            floor=6,
            act=1,
            current_hp=60,
            max_hp=80,
            deck=self.cards,
            screen_state={"rest_options": ["rest", "smith"], "has_rested": False},
            available_commands=["choose"],
        )
        self.mock_client.run_react_turn.return_value = (
            "We have healthy HP (60/80). Upgrading Bash for 3 turns vulnerable.\n"
            "```action\nCHOOSE smith\n```"
        )
        action_rest = self.macro.decide_rest(rest_state)
        self.assertEqual(action_rest.choice, "smith")

        # 验证此时 macro.messages 包含了系统提示、用户提示和模型的助手回复
        self.assertEqual(len(self.macro.messages), 3)
        self.assertEqual(self.macro.messages[0]["role"], "system")
        self.assertEqual(self.macro.messages[1]["role"], "user")
        self.assertEqual(self.macro.messages[2]["role"], "assistant")
        self.assertIn("CHOOSE smith", self.macro.messages[2]["content"])

        # 2. 紧接着在同一层进入锻造选卡界面
        self.mock_client.run_react_turn.return_value = (
            "Upgrading Bash increases damage and Vulnerable duration.\n"
            "```action\nCHOOSE 1\n```"
        )
        action_smith = self.macro.decide_smith_card(self.cards, prompt="Select a card to upgrade", floor=6)
        self.assertEqual(action_smith.choice, "1")

        # 验证会话记忆保留了之前的决策历史，消息总数增长为 5 条
        self.assertEqual(len(self.macro.messages), 5)
        self.assertEqual(self.macro.messages[3]["role"], "user")
        self.assertIn("CAMPFIRE SMITHING", self.macro.messages[3]["content"])
        self.assertEqual(self.macro.messages[4]["role"], "assistant")
        self.assertIn("CHOOSE 1", self.macro.messages[4]["content"])

    def test_floor_change_resets_room_context(self):
        """测试进入新楼层时自动重置房间对话记忆"""
        # Floor 6 营地决策
        rest_state = FullGameState(
            screen_type="REST",
            floor=6,
            act=1,
            current_hp=60,
            max_hp=80,
            deck=self.cards,
            screen_state={"rest_options": ["rest", "smith"], "has_rested": False},
            available_commands=["choose"],
        )
        self.mock_client.run_react_turn.return_value = "```action\nCHOOSE smith\n```"
        self.macro.decide_rest(rest_state)
        self.assertEqual(len(self.macro.messages), 3)

        # 进入 Floor 7，执行新决策（例如事件）
        event_state = FullGameState(
            screen_type="EVENT",
            floor=7,
            act=1,
            current_hp=60,
            max_hp=80,
            deck=self.cards,
            screen_state={
                "event_id": "Accursed Blacksmith",
                "body_text": "A blacksmith offers to forge.",
                "options": [{"label": "Forge", "disabled": False}, {"label": "Leave", "disabled": False}],
            },
            available_commands=["choose"],
        )
        self.mock_client.run_react_turn.return_value = "```action\nCHOOSE 0\n```"
        self.macro.decide_event(event_state)

        # 验证旧楼层的营地对话已被重置，当前仅包含 Floor 7 的事件对话
        self.assertEqual(len(self.macro.messages), 3)
        self.assertIn("Accursed Blacksmith", self.macro.messages[1]["content"])

    def test_agent_grid_upgrade_detection_without_prompt(self):
        """测试当 CommunicationMod 的 prompt 为空时，通过 for_upgrade 和 pending_campfire_smith 正确识别锻造界面"""
        agent = SpireAgent()
        agent.macro_session = MagicMock()

        # 1. 模拟在营地选择 smith
        rest_state = FullGameState(
            screen_type="REST",
            floor=6,
            act=1,
            screen_state={"rest_options": ["rest", "smith"], "has_rested": False},
            available_commands=["choose"],
        )
        agent.macro_session.decide_rest.return_value = ChooseAction.create("smith")
        agent.decide_screen_action(rest_state)
        self.assertTrue(agent.pending_campfire_smith)

        # 2. 游戏打开 GRID 界面，prompt 为空串，但有 pending_campfire_smith
        grid_state_empty_prompt = FullGameState(
            screen_type="GRID",
            floor=6,
            act=1,
            screen_state={
                "prompt": "",  # CommunicationMod 经常在此处为空
                "for_upgrade": True,  # CommunicationMod 原生字段
                "cards": [
                    {"id": "Strike_R", "name": "Strike", "cost": 1, "type": "ATTACK"},
                    {"id": "Bash", "name": "Bash", "cost": 2, "type": "ATTACK"},
                ],
            },
            available_commands=["choose"],
        )
        agent.decide_screen_action(grid_state_empty_prompt)

        # 必须正确路由至 decide_smith_card，而不是误入删牌 decide_deck_purge_card！
        agent.macro_session.decide_smith_card.assert_called_once()
        agent.macro_session.decide_deck_purge_card.assert_not_called()
        self.assertFalse(agent.pending_campfire_smith)

    def test_shop_sequential_purchase_history(self):
        """测试商店多轮连续消费时，房间对话记忆保持连续"""
        shop_state_1 = FullGameState(
            screen_type="SHOP_SCREEN",
            floor=8,
            act=1,
            gold=300,
            deck=self.cards,
            relics=[],
            potions=[],
            screen_state={
                "cards": [],
                "relics": [{"id": "Vajra", "name": "Vajra", "price": 150}],
                "potions": [],
                "purge_available": True,
                "purge_cost": 75,
            },
            choice_list=["vajra", "purge"],
            available_commands=["choose"],
        )
        self.mock_client.run_react_turn.return_value = (
            "Buy Vajra for passive strength.\n"
            "```action\nBUY RELIC 0\n```"
        )
        act1 = self.macro.decide_shop(shop_state_1)
        self.assertIsInstance(act1, ChooseAction)
        self.assertEqual(len(self.macro.messages), 3)

        # 第二轮购买：买了 Vajra 后还剩 150G，选择删牌
        shop_state_2 = FullGameState(
            screen_type="SHOP_SCREEN",
            floor=8,
            act=1,
            gold=150,
            deck=self.cards,
            relics=["Vajra"],
            potions=[],
            screen_state={
                "cards": [],
                "relics": [],
                "potions": [],
                "purge_available": True,
                "purge_cost": 75,
            },
            choice_list=["purge"],
            available_commands=["choose"],
        )
        self.mock_client.run_react_turn.return_value = (
            "Purge a basic strike with remaining gold.\n"
            "```action\nPURGE\n```"
        )
        act2 = self.macro.decide_shop(shop_state_2)
        self.assertIsInstance(act2, ChooseAction)
        self.assertEqual(len(self.macro.messages), 5)
        self.assertIn("BUY RELIC 0", self.macro.messages[2]["content"])
        self.assertIn("PURGE", self.macro.messages[4]["content"])


if __name__ == "__main__":
    unittest.main()

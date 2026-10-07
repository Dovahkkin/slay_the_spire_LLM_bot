import unittest
from unittest.mock import MagicMock
from spire_agent.models import FullGameState, CombatState, Player, Monster, Card, ChooseAction, PlayCardAction
from spire_agent.agent import SpireAgent
from spire_agent.driver import MockGameDriver
from llm_client import SpireLLMClient
from main import run_game_loop


class TestArmamentsHandSelect(unittest.TestCase):
    def setUp(self):
        self.player = Player(current_hp=50, max_hp=80, energy=3, block=0)
        self.monster = Monster(index=0, id="JawWorm", name="Jaw Worm", current_hp=40, max_hp=42, block=0, intent="ATTACK", move_damage=12)
        self.hand = [
            Card(index=0, id="Armaments", name="Armaments", cost=1, type="SKILL", block=5, description="Gain 5 Block. Upgrade a card in your hand for the rest of combat."),
            Card(index=1, id="Bash", name="Bash", cost=2, type="ATTACK", damage=8, description="Deal 8 damage. Apply 2 Vulnerable."),
            Card(index=2, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
        ]
        self.combat_state = CombatState(turn=1, player=self.player, monsters=[self.monster], hand=self.hand)

    def test_in_combat_property_during_hand_select(self):
        # 验证在 HAND_SELECT 状态下，如果处于战斗中，in_combat 依然为 True
        state = FullGameState(
            screen_type="HAND_SELECT",
            screen_state={
                "hand": [
                    {"name": "Bash", "id": "Bash", "cost": 2, "type": "ATTACK", "damage": 8, "block": 0, "upgrades": 0},
                    {"name": "Strike", "id": "Strike_R", "cost": 1, "type": "ATTACK", "damage": 6, "block": 0, "upgrades": 0},
                ],
                "max_cards": 1,
            },
            combat_state=self.combat_state,
            available_commands=["choose"],
            is_screen_up=True,
        )
        self.assertTrue(state.in_combat)

    def test_decide_screen_action_reads_hand_key_and_formats_prompt(self):
        agent = SpireAgent()
        mock_llm = MagicMock(spec=SpireLLMClient)
        mock_llm.is_available = True
        mock_llm.run_react_turn.return_value = "我认为应该优先升级重击Bash，提升易伤回合与伤害。\n```action\nCHOOSE 0\n```"
        agent.combat_session.llm_client = mock_llm

        # 模拟刚才打出的卡牌为 Armaments
        agent.last_played_card = self.hand[0]

        state = FullGameState(
            screen_type="HAND_SELECT",
            screen_state={
                "hand": [
                    {"name": "Bash", "id": "Bash", "cost": 2, "type": "ATTACK", "damage": 8, "block": 0, "upgrades": 0},
                    {"name": "Strike", "id": "Strike_R", "cost": 1, "type": "ATTACK", "damage": 6, "block": 0, "upgrades": 0},
                ],
                "max_cards": 1,
            },
            combat_state=self.combat_state,
            available_commands=["choose"],
            is_screen_up=True,
        )

        action = agent.decide_screen_action(state)
        self.assertIsInstance(action, ChooseAction)
        self.assertEqual(action.choice, "0")
        self.assertEqual(action.raw_command, "CHOOSE 0")

        # 验证推演提示词中包含了针对 Armaments 的升级说明
        call_args = mock_llm.run_react_turn.call_args[0][0]
        user_msg = call_args[-2]["content"]
        self.assertIn("Upgrade a card", user_msg)
        self.assertIn("Armaments", user_msg)
        self.assertIn("Bash", user_msg)

    def test_safe_fallback_never_sends_invalid_confirm(self):
        agent = SpireAgent()
        mock_llm = MagicMock(spec=SpireLLMClient)
        mock_llm.is_available = False
        agent.combat_session.llm_client = mock_llm

        # 模拟极端情况：screen_state 为空，available_commands 只有 choose
        state = FullGameState(
            screen_type="HAND_SELECT",
            screen_state={},
            combat_state=self.combat_state,
            available_commands=["choose"],
            is_screen_up=True,
        )

        action = agent.decide_screen_action(state)
        # 绝不能发送 CONFIRM！必须是 CHOOSE
        self.assertIsInstance(action, ChooseAction)
        self.assertEqual(action.raw_command, "CHOOSE 0")

    def test_end_to_end_armaments_loop(self):
        # 沙盒模拟运行完整循环：打出 Armaments -> 自动进入 HAND_SELECT -> 选卡升级 -> 回到战斗
        driver = MockGameDriver("cultist")
        # 将手牌替换为包含 Armaments 的卡牌组
        driver.combat_state.hand = [
            Card(index=0, id="Armaments", name="Armaments", cost=1, type="SKILL", block=5, description="Gain 5 Block. Upgrade a card in your hand."),
            Card(index=1, id="Bash", name="Bash", cost=2, type="ATTACK", damage=8),
        ]

        agent = SpireAgent()
        mock_llm = MagicMock(spec=SpireLLMClient)
        mock_llm.is_available = True
        mock_llm.run_react_turn.side_effect = [
            # 1. 制定第一回合常规连招
            "首先打出武装 Armaments 升级手牌，并获得格挡。\n```plan\nPLAY Armaments\nEND\n```",
            # 2. 触发 HAND_SELECT 时的选牌
            "在手牌中选择升级强力单体伤害牌 Bash。\n```action\nCHOOSE 0\n```",
            # 3. 回到战斗后的后续出牌
            "打出升级后的痛击。\n```plan\nPLAY Bash\nEND\n```",
            # 4. 后续回合
            "```plan\nEND\n```",
            "```plan\nEND\n```"
        ]
        agent.combat_session.llm_client = mock_llm

        # 运行主循环至多 6 步，确保不会无限死循环
        run_game_loop(driver=driver, agent=agent, max_steps=6)

        # 验证 driver 最终没有卡在 HAND_SELECT，且战斗能够正常推进
        self.assertNotEqual(driver.phase, "hand_select")


if __name__ == "__main__":
    unittest.main()

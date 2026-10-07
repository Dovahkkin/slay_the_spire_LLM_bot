import unittest
from unittest.mock import MagicMock
from spire_agent.models import CombatState, Player, Monster, Card
from spire_agent.combat_session import CombatSession
from llm_client import SpireLLMClient


class TestCombatSessionHistory(unittest.TestCase):
    def setUp(self):
        self.p = Player(current_hp=80, max_hp=80, energy=3, block=0)
        self.m0 = Monster(
            index=0,
            id="Louse",
            name="Red Louse",
            current_hp=12,
            max_hp=12,
            block=0,
            intent="ATTACK",
            move_damage=6,
            move_hits=1,
        )
        self.cards = [
            Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=1, id="Defend_R", name="Defend", cost=1, type="SKILL", block=5),
        ]
        self.state_turn1 = CombatState(turn=1, player=self.p, monsters=[self.m0], hand=self.cards)
        self.state_turn2 = CombatState(turn=2, player=self.p, monsters=[self.m0], hand=self.cards)

        self.mock_client = MagicMock(spec=SpireLLMClient)
        self.mock_client.is_available = True
        self.session = CombatSession(self.mock_client)

    def test_intra_combat_history_accumulation(self):
        """测试单场战斗多回合对话历史持续追加"""
        # Turn 1
        self.mock_client.run_react_turn.return_value = "```plan\nPLAY Strike 0\nEND\n```"
        plan1 = self.session.plan_turn(self.state_turn1)
        self.assertIsNotNone(plan1)

        # 验证 Turn 1 后 messages 包含: system, user(Turn 1), assistant(Turn 1)
        self.assertEqual(len(self.session.messages), 3)
        self.assertEqual(self.session.messages[0]["role"], "system")
        self.assertEqual(self.session.messages[1]["role"], "user")
        self.assertIn("COMBAT TURN 1", self.session.messages[1]["content"])
        self.assertEqual(self.session.messages[2]["role"], "assistant")
        self.assertIn("PLAY Strike 0", self.session.messages[2]["content"])

        # Turn 2: 应在原有历史基础上累加
        self.mock_client.run_react_turn.return_value = "```plan\nPLAY Defend\nEND\n```"
        plan2 = self.session.plan_turn(self.state_turn2)
        self.assertIsNotNone(plan2)

        # 验证 Turn 2 后 messages 扩展为 5 条且前 3 条完整保留
        self.assertEqual(len(self.session.messages), 5)
        self.assertEqual(self.session.messages[3]["role"], "user")
        self.assertIn("COMBAT TURN 2", self.session.messages[3]["content"])
        self.assertEqual(self.session.messages[4]["role"], "assistant")
        self.assertIn("PLAY Defend", self.session.messages[4]["content"])

    def test_combat_reflection_receives_history_and_resets(self):
        """测试战斗结束复盘带入整场历史，随后 reset 彻底清空"""
        self.mock_client.run_react_turn.return_value = "```plan\nPLAY Strike 0\nEND\n```"
        self.session.plan_turn(self.state_turn1)
        self.assertEqual(len(self.session.messages), 3)

        # 模拟战斗结束生成反思
        self.mock_client.run_react_turn.return_value = "第一回合输出爆发充足，快速斩杀。"
        self.session.on_combat_end(final_hp=80, max_hp=80, floor=1)

        # 验证 run_react_turn 在反思时收到了包含 Turn 1 历史的消息列表（加上反思 prompt）
        last_call_messages = self.mock_client.run_react_turn.call_args[1].get("messages")
        self.assertIsNotNone(last_call_messages)
        self.assertEqual(len(last_call_messages), 4)
        self.assertEqual(last_call_messages[-1]["role"], "user")
        self.assertIn("post-combat tactical reflection", last_call_messages[-1]["content"])

        # 验证 on_combat_end 最终触发 reset，彻底清空 messages
        self.assertEqual(len(self.session.messages), 0)
        self.assertEqual(self.session.current_combat_turn, 0)

    def test_in_combat_card_selection_preserves_context(self):
        """测试战斗中二次选牌（战吼/头槌）写入战斗上下文"""
        self.mock_client.run_react_turn.return_value = "```plan\nPLAY Strike 0\nEND\n```"
        self.session.plan_turn(self.state_turn1)
        self.assertEqual(len(self.session.messages), 3)

        # 触发选卡
        self.mock_client.run_react_turn.return_value = "I choose card #1.\n```action\nCHOOSE 1\n```"
        action = self.session.decide_in_combat_card_selection(
            screen_type="HAND_SELECT",
            prompt="Choose a card to put on top",
            cards=self.cards,
        )
        self.assertEqual(action.choice, "1")

        # 验证选卡对话已追加到历史
        self.assertEqual(len(self.session.messages), 5)
        self.assertEqual(self.session.messages[3]["role"], "user")
        self.assertIn("IN-COMBAT CARD SELECTION", self.session.messages[3]["content"])
        self.assertEqual(self.session.messages[4]["role"], "assistant")
        self.assertIn("CHOOSE 1", self.session.messages[4]["content"])

    def test_history_truncation_safeguard(self):
        """测试战斗超过 30 条交互时的自动安全截断"""
        # 手动预填 32 条历史
        self.session.current_combat_turn = 1
        self.session.messages = [{"role": "system", "content": "SYSTEM_PROMPT"}] + [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg_{i}"}
            for i in range(32)
        ]
        self.assertEqual(len(self.session.messages), 33)

        # 执行下一回合规划 (Turn 2)
        self.mock_client.run_react_turn.return_value = "```plan\nPLAY Strike 0\nEND\n```"
        self.session.plan_turn(self.state_turn2)

        # 截断后保留: system(1) + 最后10条 + 本轮user(1) + 本轮assistant(1) = 13 条
        self.assertEqual(len(self.session.messages), 13)
        self.assertEqual(self.session.messages[0]["content"], "SYSTEM_PROMPT")

    def test_new_combat_resets_messages(self):
        """测试新一场战斗开始时（即使没有触发 reset，turn 降低时）会自动清空重开"""
        # 战斗 1 打到 Turn 3
        self.session.current_combat_turn = 3
        self.session.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]

        # 异常情况下直接进入下一场战斗 Turn 1
        self.mock_client.run_react_turn.return_value = "```plan\nPLAY Strike 0\nEND\n```"
        self.session.plan_turn(self.state_turn1)

        # 应当被识别为新战斗，清空旧历史，仅包含新的 system, user, assistant
        self.assertEqual(len(self.session.messages), 3)
        self.assertIn("COMBAT TURN 1", self.session.messages[1]["content"])


    def test_ambiguous_target_retry_conversation_flow(self):
        """测试多怪未指定目标重试时，错误反馈与纠正交互被正确追加到对话流中"""
        m1 = Monster(
            index=1,
            id="Louse",
            name="Green Louse",
            current_hp=11,
            max_hp=11,
            block=0,
            intent="ATTACK",
            move_damage=7,
            move_hits=1,
        )
        multi_enemy_state = CombatState(turn=1, player=self.p, monsters=[self.m0, m1], hand=self.cards)

        # 第一次返回歧义指令，第二次在收到错误反馈后输出修正指令
        self.mock_client.run_react_turn.side_effect = [
            "```plan\nPLAY Strike\nEND\n```",
            "```plan\nPLAY Strike 0\nEND\n```",
        ]

        plan = self.session.plan_turn(multi_enemy_state)
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.actions), 2)

        # 对话流应包含: system, user(Turn 1), assistant(flawed), user(error feedback), assistant(corrected)
        self.assertEqual(len(self.session.messages), 5)
        self.assertEqual(self.session.messages[0]["role"], "system")
        self.assertEqual(self.session.messages[1]["role"], "user")
        self.assertEqual(self.session.messages[2]["role"], "assistant")
        self.assertIn("PLAY Strike\nEND", self.session.messages[2]["content"])
        self.assertEqual(self.session.messages[3]["role"], "user")
        self.assertIn("Command Syntax Error", self.session.messages[3]["content"])
        self.assertEqual(self.session.messages[4]["role"], "assistant")
        self.assertIn("PLAY Strike 0\nEND", self.session.messages[4]["content"])


if __name__ == "__main__":
    unittest.main()


import unittest
from unittest.mock import MagicMock
from spire_agent.models import FullGameState, Card, ChooseAction, ProceedAction
from spire_agent.compressor import StateCompressor
from spire_agent.macro_session import MacroSession


class TestEventMacro(unittest.TestCase):
    def setUp(self):
        self.mock_llm = MagicMock()
        self.mock_llm.is_available = True
        self.macro_session = MacroSession(self.mock_llm)

    def test_compress_event(self):
        options = [
            {"label": "[ Max HP +8 ]", "disabled": False},
            {"label": "[ Lose 10 HP ] Obtain Rare Card", "disabled": False},
            {"label": "[ Pay 100 Gold ] (Locked)", "disabled": True},
        ]
        deck = [Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK")]
        compressed = StateCompressor.compress_event(
            event_id="Neow Event",
            body_text="Greetings mortal...",
            options=options,
            current_hp=80,
            max_hp=80,
            gold=99,
            floor=0,
            deck=deck,
            relics=["Burning Blood"],
        )

        self.assertIn("=== EVENT ENCOUNTER (Floor 0) ===", compressed)
        self.assertIn("EVENT_ID: Neow Event", compressed)
        self.assertIn("HP 80/80 (100%)", compressed)
        self.assertIn("Greetings mortal...", compressed)
        self.assertIn("[0]: [ Max HP +8 ] (AVAILABLE)", compressed)
        self.assertIn("[1]: [ Lose 10 HP ] Obtain Rare Card (AVAILABLE)", compressed)
        self.assertIn("[2]: [ Pay 100 Gold ] (Locked) (DISABLED)", compressed)

    def test_event_fast_path_single_option(self):
        """当仅有 1 个可用选项（如推进剧情/离开）时，应快速通过，不调用 LLM"""
        state = FullGameState(
            screen_type="EVENT",
            screen_state={
                "event_id": "Big Fish",
                "body_text": "You leave the fish alone.",
                "options": [
                    {"label": "[ Leave ]", "disabled": False},
                    {"label": "[ Eat ]", "disabled": True},
                ],
            },
            available_commands=["choose"],
        )

        action = self.macro_session.decide_event(state)
        self.assertEqual(action.raw_command, "CHOOSE 0")
        self.assertEqual(self.mock_llm.run_react_turn.call_count, 0)

    def test_event_no_options_proceed(self):
        """当没有可用选项时，应发送 PROCEED"""
        state = FullGameState(
            screen_type="EVENT",
            screen_state={
                "event_id": "Dialogue Event",
                "options": [{"label": "Locked", "disabled": True}],
            },
            available_commands=["proceed"],
        )

        action = self.macro_session.decide_event(state)
        self.assertIsInstance(action, ProceedAction)
        self.assertEqual(self.mock_llm.run_react_turn.call_count, 0)

    def test_event_llm_valid_choice(self):
        """有多个可用选项时，大模型给出合法选择"""
        state = FullGameState(
            screen_type="EVENT",
            screen_state={
                "event_id": "Neow Event",
                "body_text": "Choose a blessing",
                "options": [
                    {"label": "[ Max HP +8 ]", "disabled": False},
                    {"label": "[ 100 Gold ]", "disabled": False},
                    {"label": "[ Lose 18 HP ] Obtain Rare Card", "disabled": False},
                ],
            },
            available_commands=["choose"],
            current_hp=80,
            max_hp=80,
        )

        self.mock_llm.run_react_turn.return_value = (
            "满血状态容错高，愿意失去 18 点生命搏取一张强力稀有卡。\n```action\nCHOOSE 2\n```"
        )

        action = self.macro_session.decide_event(state)
        self.assertEqual(action.raw_command, "CHOOSE 2")
        self.assertEqual(self.mock_llm.run_react_turn.call_count, 1)

    def test_event_react_retry_on_invalid_format(self):
        """模型初次输出格式错误时，应将错误反馈回模型进行第二轮 ReAct 纠错"""
        state = FullGameState(
            screen_type="EVENT",
            screen_state={
                "event_id": "Neow Event",
                "options": [
                    {"label": "[ Max HP +8 ]", "disabled": False},
                    {"label": "[ 100 Gold ]", "disabled": False},
                ],
            },
            available_commands=["choose"],
        )

        # 第 1 轮：无 action 块；第 2 轮：纠正为 CHOOSE 1
        self.mock_llm.run_react_turn.side_effect = [
            "我觉得拿 100 金币挺好的，买东西方便。",
            "好的，遵循规范输出：\n```action\nCHOOSE 1\n```",
        ]

        action = self.macro_session.decide_event(state)
        self.assertEqual(action.raw_command, "CHOOSE 1")
        self.assertEqual(self.mock_llm.run_react_turn.call_count, 2)

    def test_event_react_retry_on_disabled_option(self):
        """模型选择了被禁用的选项时，应将禁用报错反馈回模型进行纠错"""
        state = FullGameState(
            screen_type="EVENT",
            screen_state={
                "event_id": "Golden Idol",
                "options": [
                    {"label": "[ Take Idol ]", "disabled": False},
                    {"label": "[ Leave ]", "disabled": False},
                    {"label": "[ Special Bonus ]", "disabled": True},
                ],
            },
            available_commands=["choose"],
        )

        # 第 1 轮：选了禁用的 #2；第 2 轮：纠正为选 #1 离开
        self.mock_llm.run_react_turn.side_effect = [
            "我选择特殊奖励。\n```action\nCHOOSE 2\n```",
            "发现选项 2 不可选，改为离开。\n```action\nCHOOSE 1\n```",
        ]

        action = self.macro_session.decide_event(state)
        self.assertEqual(action.raw_command, "CHOOSE 1")
        self.assertEqual(self.mock_llm.run_react_turn.call_count, 2)

    def test_event_fallback_when_retries_exhausted(self):
        """当模型重试全部耗尽仍输出非法内容时，应安全保底选择（优先选包含离开的选项）"""
        state = FullGameState(
            screen_type="EVENT",
            screen_state={
                "event_id": "Dangerous Shrine",
                "options": [
                    {"label": "[ Sacrifice 50 HP ]", "disabled": False},
                    {"label": "[ 离开 ]", "disabled": False},
                ],
            },
            available_commands=["choose"],
        )

        # 连续输出胡言乱语
        self.mock_llm.run_react_turn.return_value = "我不选，我要跳过！"

        action = self.macro_session.decide_event(state)
        # 选项 1 是 "[ 离开 ]"，保底机制应优先命中离开选项
        self.assertEqual(action.raw_command, "CHOOSE 1")
        self.assertEqual(self.mock_llm.run_react_turn.call_count, 3)  # 初次 + 2 次重试


if __name__ == "__main__":
    unittest.main()

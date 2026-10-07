import sys
import os
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from spire_agent.blackboard import RunBlackboard
from spire_agent.models import (
    CombatState,
    Player,
    Monster,
    Card,
    FullGameState,
    ChooseAction,
)
from spire_agent.combat_session import CombatSession
from spire_agent.macro_session import MacroSession
from spire_agent.agent import SpireAgent


class DummyLLMClient:
    def __init__(self, mock_reply=""):
        self.is_available = True
        self.mock_reply = mock_reply

    def run_react_turn(self, messages, **kwargs):
        return self.mock_reply


class TestBlackboardIntegration(unittest.TestCase):
    def setUp(self):
        self.test_memo_path = Path(__file__).parent / "test_run_memo.md"
        if self.test_memo_path.exists():
            self.test_memo_path.unlink()
        self.blackboard = RunBlackboard(file_path=str(self.test_memo_path))

    def tearDown(self):
        if self.test_memo_path.exists():
            self.test_memo_path.unlink()

    def test_combat_to_macro_dataflow(self):
        # 1. 模拟战斗会话
        combat_client = DummyLLMClient("打得很好，无伤通过，输出足够。")
        combat_session = CombatSession(
            llm_client=combat_client,
            enable_tools=False,
            blackboard=self.blackboard,
        )

        # 战斗第 1 回合
        combat_state = CombatState(
            turn=1,
            player=Player(current_hp=75, max_hp=80, energy=3, block=0),
            monsters=[Monster(index=0, id="GremlinNob", name="Gremlin Nob", current_hp=82, max_hp=82, block=0, intent="ATTACK")],
            hand=[Card(index=0, id="Strike_R", name="Strike", type="ATTACK", cost=1, damage=6)],
        )
        plan = combat_session.plan_turn(combat_state)
        self.assertEqual(combat_session.combat_start_hp, 75)
        self.assertEqual(combat_session.encounter_name, "Gremlin Nob")

        # 战斗胜利，结算 HP 为 65 (战损 10)
        combat_session.on_combat_end(final_hp=65, max_hp=80, floor=6)

        # 验证黑板已记录战况
        self.assertIsNotNone(self.blackboard.latest_combat)
        self.assertEqual(self.blackboard.latest_combat.hp_lost, 10)
        self.assertEqual(self.blackboard.latest_combat.floor, 6)
        self.assertEqual(self.blackboard.latest_combat.encounter, "Gremlin Nob")

        # 验证 run_memo.md 文件已持久化落盘
        self.assertTrue(self.test_memo_path.exists())
        with open(self.test_memo_path, "r", encoding="utf-8") as f:
            disk_content = f.read()
        self.assertIn("Gremlin Nob", disk_content)
        self.assertIn("战损 10 HP", disk_content)

        # 2. 模拟宏观选牌会话读取战况并更新流派
        macro_reply = (
            "分析：刚刚打完 Nob 掉了 10 血，攻击力已够但极度缺乏防守，选择耸肩无视补齐防御。\n"
            "```memo\n"
            "ARCHETYPE: 力量战 (High Strength)\n"
            "WIN_CON: 发光+弱点堆力量，重刃斩杀\n"
            "PLAY_GUIDE: 起手下发光，重刃留作终结；面对高伤敌人算满防御\n"
            "DRAFTING_FOCUS: 寻找耸肩无视与收割\n"
            "```\n"
            "```action\n"
            "CHOOSE 0\n"
            "```"
        )
        macro_client = DummyLLMClient(macro_reply)
        macro_session = MacroSession(llm_client=macro_client, blackboard=self.blackboard)

        offered = [
            Card(index=0, id="Shrug_It_Off", name="Shrug It Off", type="SKILL", cost=1, block=8),
            Card(index=1, id="Iron_Wave", name="Iron Wave", type="ATTACK", cost=1, damage=5, block=5),
        ]
        deck = [Card(index=0, id="Strike_R", name="Strike", type="ATTACK", cost=1)]
        action = macro_session.decide_card_reward(deck, [], offered)

        self.assertIsInstance(action, ChooseAction)
        self.assertEqual(str(action.choice), "0")

        # 验证黑板宏观规划已由大模型更新
        self.assertEqual(self.blackboard.archetype, "力量战 (High Strength)")
        self.assertIn("发光+弱点", self.blackboard.win_con)
        self.assertIn("耸肩无视", self.blackboard.drafting_focus)

        # 验证下一场战斗读取到的作战锦囊
        briefing = self.blackboard.get_combat_briefing()
        self.assertIn("力量战 (High Strength)", briefing)
        self.assertIn("起手下发光", briefing)

        print("\n[SUCCESS] TestBlackboardIntegration passed completely!")


if __name__ == "__main__":
    unittest.main()

import unittest
from spire_agent import (
    CombatState,
    Player,
    Monster,
    Card,
    Power,
    MockGameDriver,
    SpireAgent,
    PlayCardAction,
    EndTurnAction,
)
from spire_agent.tools import (
    SpireToolRegistry,
    DamageCalculatorTool,
    MonsterDossierTool,
)
from main import run_game_loop


class TestLLMSpireAgent(unittest.TestCase):

    def setUp(self):
        self.player = Player(
            current_hp=50,
            max_hp=80,
            energy=3,
            block=5,
            powers=[Power(id="Strength", name="Strength", amount=2)],
        )
        self.monster = Monster(
            index=0,
            id="GremlinNob",
            name="Gremlin Nob",
            current_hp=45,
            max_hp=86,
            block=0,
            intent="ATTACK",
            move_damage=14,
            move_hits=1,
        )
        self.cards = [
            Card(index=0, id="Flex", name="Flex", cost=0, type="SKILL", target_type="SELF", description="Gain 2 Strength."),
            Card(index=1, id="Bash", name="Bash", cost=2, type="ATTACK", target_type="ENEMY", damage=8, description="Deal 8 damage. Apply 2 Vulnerable."),
            Card(index=2, id="Strike_R", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=6),
            Card(index=3, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
        ]
        self.state = CombatState(
            turn=1,
            player=self.player,
            monsters=[self.monster],
            hand=self.cards,
        )

    def test_damage_calculator_tool(self):
        """测试伤害精确试算工具：验证力量与易伤叠加"""
        calc = DamageCalculatorTool()
        # 试算 [Flex(0费加2力), Bash(2费打8+2+2=12, 上易伤), Strike(1费打6+2+2=10 * 1.5 = 15)]
        res = calc.execute({"card_indices": [0, 1, 2], "target_enemy_index": 0}, context=self.state)
        self.assertTrue(res.success)
        data = res.data
        self.assertTrue(data["valid_energy"])
        self.assertEqual(data["energy_needed"], 3)
        # 总伤害: Bash(12) + Strike(15) = 27
        self.assertEqual(data["total_damage"], 27)
        self.assertEqual(data["target_final_hp"], 45 - 27)

    def test_monster_dossier_tool(self):
        """测试怪物对策知识库工具：地精大块头禁忌"""
        dossier = MonsterDossierTool()
        res = dossier.execute({"monster_id": "GremlinNob"})
        self.assertTrue(res.success)
        data = res.data
        self.assertIn("Gremlin Nob", data["name"])
        self.assertIn("DO NOT play", data["tactics"])

    def test_tool_registry_active_tools(self):
        """测试工具注册表：已移除粗糙 candidate combos 工具，怪物工具默认禁用转为 RAG 注入，保留试算器"""
        registry_default = SpireToolRegistry(enable_calculator=True, enable_all_tools=True)
        self.assertIsNone(registry_default.get_tool("lookup_monster_tactics"))
        self.assertIsNotNone(registry_default.get_tool("calculate_card_sequence"))
        self.assertIsNone(registry_default.get_tool("generate_candidate_combos"))

        # 显式开启怪物工具时仍可被使用（保证平滑兼容）
        registry_with_monster = SpireToolRegistry(enable_calculator=True, enable_all_tools=True, enable_monster_tool=True)
        self.assertIsNotNone(registry_with_monster.get_tool("lookup_monster_tactics"))

    def test_combat_plan_generation(self):
        """测试回合连招规划方案生成与执行格式"""
        agent = SpireAgent()
        plan = agent.plan_combat_turn(self.state)
        self.assertIsNotNone(plan)
        self.assertTrue(len(plan.actions) >= 1)
        # 最后一个动作应为结束回合
        self.assertIsInstance(plan.actions[-1], EndTurnAction)

    def test_mock_sandbox_full_run_lethal(self):
        """测试 Mock 残血战局全流程：斩杀怪物 -> 拾取战利品 -> 选牌 -> 地图导航"""
        driver = MockGameDriver(scenario="lethal")
        agent = SpireAgent()
        run_game_loop(agent, driver, max_steps=20)
        self.assertTrue(driver.is_game_over(), "残血战局应在几步内顺利通关！")

    def test_combat_session_reset_on_end(self):
        """测试战斗结束后临时上下文被彻底清空"""
        agent = SpireAgent()
        # 模拟进入战斗
        agent.combat_session.messages.append({"role": "user", "content": "temp"})
        self.assertEqual(len(agent.combat_session.messages), 1)
        # 战斗胜利调用 on_combat_end
        agent.on_combat_end()
        self.assertEqual(len(agent.combat_session.messages), 0, "战斗结束后必须彻底清空临时上下文！")

    def test_in_combat_card_selection_hand_select(self):
        """测试战吼/头槌二次选牌弹窗交由 Agent 处理"""
        from spire_agent import FullGameState, ChooseAction
        agent = SpireAgent()
        hand_select_state = FullGameState(
            screen_type="HAND_SELECT",
            screen_state={
                "prompt": "Select a card to put on top of your draw pile",
                "cards": [
                    {"id": "Strike_R", "name": "Strike", "raw_description": "Deal 6 damage."},
                    {"id": "Defend_R", "name": "Defend", "raw_description": "Gain 5 block."},
                ],
            },
            available_commands=["choose"],
        )
        action = agent.decide_screen_action(hand_select_state)
        self.assertIsInstance(action, ChooseAction)


if __name__ == "__main__":
    unittest.main()


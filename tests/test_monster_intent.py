import unittest
import io
import json
from unittest.mock import patch
from spire_agent.models import Monster, Player, CombatState, Card
from spire_agent.compressor import StateCompressor
from spire_agent.driver import CommunicationModDriver


class TestMonsterIntent(unittest.TestCase):
    def test_intent_description_composite(self):
        # 1. 组合意图 (Attack + Debuff / Defend / Buff)
        m_atk_debuff = Monster(
            index=0, id="SpikeSlime_L", name="Large Spike Slime",
            current_hp=60, max_hp=60, intent="ATTACK_DEBUFF", move_damage=16, move_hits=1
        )
        self.assertEqual(m_atk_debuff.intent_description, "Attack 16 + Debuff")
        self.assertEqual(m_atk_debuff.total_incoming_damage, 16)

        m_multi_debuff = Monster(
            index=0, id="BookOfStabbing", name="Book of Stabbing",
            current_hp=160, max_hp=160, intent="ATTACK_DEBUFF", move_damage=7, move_hits=3
        )
        self.assertEqual(m_multi_debuff.intent_description, "Attack 7x3 + Debuff")
        self.assertEqual(m_multi_debuff.total_incoming_damage, 21)

        m_atk_def = Monster(
            index=0, id="ShelledParasite", name="Shelled Parasite",
            current_hp=70, max_hp=70, intent="ATTACK_DEFEND", move_damage=10, move_hits=1
        )
        self.assertEqual(m_atk_def.intent_description, "Attack 10 + Defend")
        self.assertEqual(m_atk_def.total_incoming_damage, 10)

        m_atk_buff = Monster(
            index=0, id="Cultist", name="Cultist",
            current_hp=50, max_hp=50, intent="ATTACK_BUFF", move_damage=6, move_hits=1
        )
        self.assertEqual(m_atk_buff.intent_description, "Attack 6 + Buff")
        self.assertEqual(m_atk_buff.total_incoming_damage, 6)

    def test_intent_description_pure_and_edge_cases(self):
        # 2. 纯 DEBUFF / BUFF / DEFEND
        m_debuff = Monster(
            index=0, id="Lagavulin", name="Lagavulin",
            current_hp=100, max_hp=100, intent="DEBUFF", move_damage=0
        )
        self.assertEqual(m_debuff.intent_description, "Debuff (No attack, 0 dmg)")
        self.assertEqual(m_debuff.total_incoming_damage, 0)

        m_strong_debuff = Monster(
            index=0, id="Snecko", name="Snecko",
            current_hp=120, max_hp=120, intent="STRONG_DEBUFF", move_damage=0
        )
        self.assertEqual(m_strong_debuff.intent_description, "Debuff (No attack, 0 dmg)")
        self.assertEqual(m_strong_debuff.total_incoming_damage, 0)

        m_buff = Monster(
            index=0, id="Cultist", name="Cultist",
            current_hp=50, max_hp=50, intent="BUFF", move_damage=0
        )
        self.assertEqual(m_buff.intent_description, "Buff (No attack, 0 dmg)")
        self.assertEqual(m_buff.total_incoming_damage, 0)

        # 3. 意图名未标 ATTACK 但附带 move_damage 的容错处理
        m_debuff_with_dmg = Monster(
            index=0, id="ModdedMonster", name="Modded Monster",
            current_hp=50, max_hp=50, intent="DEBUFF", move_damage=12, move_hits=1
        )
        self.assertEqual(m_debuff_with_dmg.intent_description, "Attack 12 + Debuff")
        self.assertEqual(m_debuff_with_dmg.total_incoming_damage, 12)

        # 4. 其他状态 (DEBUG, SLEEP, STUN, ESCAPE, MAGIC)
        m_sleep = Monster(index=0, id="Lagavulin", name="Lagavulin", current_hp=100, max_hp=100, intent="SLEEP")
        self.assertEqual(m_sleep.intent_description, "Sleeping (0 dmg)")
        self.assertEqual(m_sleep.total_incoming_damage, 0)

        m_stun = Monster(index=0, id="Guardian", name="The Guardian", current_hp=200, max_hp=200, intent="STUN")
        self.assertEqual(m_stun.intent_description, "Stunned (0 dmg)")
        self.assertEqual(m_stun.total_incoming_damage, 0)

        m_debug = Monster(index=0, id="Slime", name="Slime", current_hp=60, max_hp=60, intent="DEBUG", move_damage=0)
        self.assertEqual(m_debug.intent_description, "Uninitialized / Waiting")
        self.assertEqual(m_debug.total_incoming_damage, 0)

    def test_compress_combat_with_composite_intent(self):
        player = Player(current_hp=50, max_hp=80, energy=3, block=5)
        slime = Monster(
            index=0, id="SpikeSlime_L", name="Large Spike Slime",
            current_hp=60, max_hp=60, intent="ATTACK_DEBUFF", move_damage=16, move_hits=1
        )
        state = CombatState(turn=1, player=player, monsters=[slime], hand=[])

        prompt = StateCompressor.compress_combat(state)

        # 验证提示词中包含完整的意图信息 "Attack 16 + Debuff"
        self.assertIn("Intent: Attack 16 + Debuff", prompt)
        # 验证威胁计算正确识别并计算 16 伤害 (而不是被误判为 0 或丢失)
        self.assertIn("INCOMING THREAT: 16 dmg", prompt)
        self.assertIn("UNBLOCKED: 11 HP damage!", prompt)

    def test_from_communication_mod_json_clamping(self):
        raw_json = {
            "in_combat": True,
            "turn": 1,
            "player": {"current_hp": 80, "max_hp": 80, "energy": 3, "block": 0, "powers": [], "relics": []},
            "monsters": [
                {
                    "id": "SpikeSlime_L",
                    "name": "Large Spike Slime",
                    "current_hp": 64,
                    "max_hp": 64,
                    "block": 0,
                    "intent": "ATTACK_DEBUFF",
                    "move_adjusted_damage": 16,
                    "move_hits": 1,
                    "powers": []
                },
                {
                    "id": "Lagavulin",
                    "name": "Lagavulin",
                    "current_hp": 110,
                    "max_hp": 110,
                    "block": 0,
                    "intent": "DEBUFF",
                    "move_adjusted_damage": -1,  # CommunicationMod 传 -1 表示无伤害
                    "move_hits": 1,
                    "powers": []
                }
            ],
            "hand": []
        }
        state = StateCompressor.from_communication_mod_json(raw_json)
        self.assertEqual(len(state.monsters), 2)
        # 第一个怪物: 16 伤害
        self.assertEqual(state.monsters[0].move_damage, 16)
        self.assertEqual(state.monsters[0].intent_description, "Attack 16 + Debuff")
        self.assertEqual(state.monsters[0].total_incoming_damage, 16)

        # 第二个怪物: -1 被 clamp 为 0
        self.assertEqual(state.monsters[1].move_damage, 0)
        self.assertEqual(state.monsters[1].intent_description, "Debuff (No attack, 0 dmg)")
        self.assertEqual(state.monsters[1].total_incoming_damage, 0)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_communication_driver_debug_intent_interception(self, mock_stdout):
        # 模拟两帧输入：
        # 第 1 帧: ready_for_command=True, 但怪物意图为 DEBUG
        # 第 2 帧: 怪物意图结算为 ATTACK_DEBUFF
        frame_debug = json.dumps({
            "ready_for_command": True,
            "available_commands": ["play", "end"],
            "in_game": True,
            "in_combat": True,
            "screen_type": "NONE",
            "floor": 1,
            "game_state": {
                "screen_type": "NONE",
                "current_hp": 80,
                "max_hp": 80,
                "combat_state": {
                    "monsters": [
                        {"id": "SpikeSlime_L", "intent": "DEBUG", "current_hp": 64, "is_gone": False, "half_dead": False}
                    ]
                }
            },
            "combat_state": {
                "turn": 1,
                "player": {"current_hp": 80, "max_hp": 80, "energy": 3, "block": 0, "powers": [], "relics": []},
                "monsters": [
                    {"id": "SpikeSlime_L", "intent": "DEBUG", "current_hp": 64, "is_gone": False, "half_dead": False}
                ],
                "hand": []
            }
        })
        frame_settled = json.dumps({
            "ready_for_command": True,
            "available_commands": ["play", "end"],
            "in_game": True,
            "in_combat": True,
            "screen_type": "NONE",
            "floor": 1,
            "game_state": {
                "screen_type": "NONE",
                "current_hp": 80,
                "max_hp": 80,
                "combat_state": {
                    "monsters": [
                        {"id": "SpikeSlime_L", "intent": "ATTACK_DEBUFF", "move_adjusted_damage": 16, "current_hp": 64, "is_gone": False, "half_dead": False}
                    ]
                }
            },
            "combat_state": {
                "turn": 1,
                "player": {"current_hp": 80, "max_hp": 80, "energy": 3, "block": 0, "powers": [], "relics": []},
                "monsters": [
                    {"id": "SpikeSlime_L", "intent": "ATTACK_DEBUFF", "move_adjusted_damage": 16, "current_hp": 64, "is_gone": False, "half_dead": False}
                ],
                "hand": []
            }
        })

        mock_stdin = io.StringIO(f"{frame_debug}\n{frame_settled}\n")
        with patch("sys.stdin", mock_stdin):
            driver = CommunicationModDriver()
            state = driver.get_full_state()

            # 验证 driver 拦截了 DEBUG 帧，并向 stdout 发送了 "wait 15\n"
            output = mock_stdout.getvalue()
            self.assertIn("wait 15\n", output)

            # 验证最终返回的状态帧是结算后的帧
            self.assertIsNotNone(state)
            self.assertIsNotNone(state.combat_state)
            self.assertEqual(state.combat_state.monsters[0].intent, "ATTACK_DEBUFF")
            self.assertEqual(state.combat_state.monsters[0].move_damage, 16)

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_communication_driver_pending_damage_intent_interception(self, mock_stdout):
        # 模拟开局第一帧：怪物为 ATTACK_DEBUFF，但伤害字段尚未结算（为 -1），第二帧结算为 7
        frame_pending = json.dumps({
            "ready_for_command": True,
            "available_commands": ["play", "end"],
            "in_game": True,
            "in_combat": True,
            "screen_type": "NONE",
            "floor": 14,
            "game_state": {
                "screen_type": "NONE",
                "current_hp": 48,
                "max_hp": 80,
                "combat_state": {
                    "monsters": [
                        {"id": "SlaverBlue", "name": "Blue Slaver", "intent": "ATTACK_DEBUFF", "move_adjusted_damage": -1, "move_base_damage": -1, "current_hp": 50, "is_gone": False, "half_dead": False}
                    ]
                }
            },
            "combat_state": {
                "turn": 1,
                "player": {"current_hp": 48, "max_hp": 80, "energy": 3, "block": 0, "powers": [], "relics": []},
                "monsters": [
                    {"id": "SlaverBlue", "name": "Blue Slaver", "intent": "ATTACK_DEBUFF", "move_adjusted_damage": -1, "move_base_damage": -1, "current_hp": 50, "is_gone": False, "half_dead": False}
                ],
                "hand": []
            }
        })
        frame_settled = json.dumps({
            "ready_for_command": True,
            "available_commands": ["play", "end"],
            "in_game": True,
            "in_combat": True,
            "screen_type": "NONE",
            "floor": 14,
            "game_state": {
                "screen_type": "NONE",
                "current_hp": 48,
                "max_hp": 80,
                "combat_state": {
                    "monsters": [
                        {"id": "SlaverBlue", "name": "Blue Slaver", "intent": "ATTACK_DEBUFF", "move_adjusted_damage": 7, "move_base_damage": 7, "current_hp": 50, "is_gone": False, "half_dead": False}
                    ]
                }
            },
            "combat_state": {
                "turn": 1,
                "player": {"current_hp": 48, "max_hp": 80, "energy": 3, "block": 0, "powers": [], "relics": []},
                "monsters": [
                    {"id": "SlaverBlue", "name": "Blue Slaver", "intent": "ATTACK_DEBUFF", "move_adjusted_damage": 7, "move_base_damage": 7, "current_hp": 50, "is_gone": False, "half_dead": False}
                ],
                "hand": []
            }
        })

        mock_stdin = io.StringIO(f"{frame_pending}\n{frame_settled}\n")
        with patch("sys.stdin", mock_stdin):
            driver = CommunicationModDriver()
            state = driver.get_full_state()

            # 验证 driver 成功拦截了 pending 帧并发送了 "wait 15\n"
            output = mock_stdout.getvalue()
            self.assertIn("wait 15\n", output)

            # 验证最终返回的状态帧是结算后的 7 点伤害
            self.assertIsNotNone(state)
            self.assertIsNotNone(state.combat_state)
            self.assertEqual(state.combat_state.monsters[0].move_damage, 7)

    def test_compress_combat_warning_on_zero_damage_attack(self):
        # 若怪物有攻击意图但伤害数值为 0，INCOMING THREAT 必须包含警告，防止模型误判为纯安全回合
        player = Player(current_hp=48, max_hp=80, energy=3, block=0)
        m = Monster(
            index=0, id="SlaverBlue", name="Blue Slaver",
            current_hp=50, max_hp=50, intent="ATTACK_DEBUFF", move_damage=0
        )
        state = CombatState(turn=1, player=player, monsters=[m], hand=[])
        prompt = StateCompressor.compress_combat(state)

        self.assertIn("WARNING: E0 (Blue Slaver: ATTACK_DEBUFF) has ATTACK intent with uncalculated damage!", prompt)
        self.assertNotIn("(No incoming attack)", prompt)

    def test_compress_combat_unknown_threat_on_debug_intent(self):
        # 若极端情况下依然超时为 DEBUG/Uninitialized，压缩器严禁输出 0 dmg (No incoming attack)
        player = Player(current_hp=48, max_hp=80, energy=3, block=0)
        m = Monster(
            index=0, id="SlaverBlue", name="Blue Slaver",
            current_hp=50, max_hp=50, intent="DEBUG", move_damage=0
        )
        state = CombatState(turn=1, player=player, monsters=[m], hand=[])
        prompt = StateCompressor.compress_combat(state)

        self.assertIn("INCOMING THREAT: UNKNOWN (Intent not ready, DO NOT assume 0 threat!", prompt)
        self.assertNotIn("(No incoming attack)", prompt)

    def test_compress_combat_unknown_threat_on_unknown_intent(self):
        # 若怪物意图为 UNKNOWN，压缩器也必须提示 UNKNOWN 威胁
        player = Player(current_hp=48, max_hp=80, energy=3, block=0)
        m = Monster(
            index=0, id="SlaverBlue", name="Blue Slaver",
            current_hp=50, max_hp=50, intent="UNKNOWN", move_damage=0
        )
        state = CombatState(turn=1, player=player, monsters=[m], hand=[])
        prompt = StateCompressor.compress_combat(state)

        self.assertIn("INCOMING THREAT: UNKNOWN (Intent not ready, DO NOT assume 0 threat!", prompt)
        self.assertNotIn("(No incoming attack)", prompt)


if __name__ == "__main__":
    unittest.main()

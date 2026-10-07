import unittest
from spire_agent.models import CombatState, Player, Monster, Card, Power
from spire_agent.compressor import StateCompressor
from spire_agent.knowledge.monsters_db import (
    lookup_monster_dossier,
    format_monster_dossiers,
    load_monsters_knowledge,
)


class TestMonsterDatabaseAndRAG(unittest.TestCase):
    def setUp(self):
        self.player = Player(
            current_hp=70,
            max_hp=80,
            energy=3,
            max_energy=3,
            block=0,
            powers=[],
            relics=["Burning Blood"],
        )

    def test_lookup_exact_and_fuzzy(self):
        # 1. 精确 Key 查找 (GremlinNob)
        nob = lookup_monster_dossier("GremlinNob")
        self.assertIsNotNone(nob)
        self.assertEqual(nob["name"], "Gremlin Nob")
        self.assertIn("Enrage", nob["key_mechanics"])
        self.assertIn("DO NOT play non-lethal Skill", nob["tactics"])

        # 2. 别名/名称查找 (Lagavulin)
        laga = lookup_monster_dossier("Lagavulin", "Lagavulin")
        self.assertIsNotNone(laga)
        self.assertIn("siphons soul", laga["key_mechanics"].lower())

        # 3. 常见衍生/后缀模糊命中 (SpikeSlime_L -> SpikeSlime)
        slime = lookup_monster_dossier("SpikeSlime_L", "Spike Slime (L)")
        self.assertIsNotNone(slime)
        self.assertIn("split", slime["key_mechanics"].lower())

    def test_format_dossiers_deduplication(self):
        """测试同种怪物（如 3 只邪教徒）自动去重，避免 Token 冗余膨胀"""
        monsters = [
            Monster(index=0, id="Cultist", name="Cultist", current_hp=50, max_hp=50),
            Monster(index=1, id="Cultist", name="Cultist", current_hp=48, max_hp=50),
            Monster(index=2, id="Cultist", name="Cultist", current_hp=50, max_hp=50),
        ]
        dossiers = format_monster_dossiers(monsters)
        self.assertEqual(len(dossiers), 3)  # - [Cultist] header + MECHANICS + TACTICS
        self.assertTrue(dossiers[0].startswith("- [Cultist]"))

    def test_kv_cache_stability_invariant_sorting_and_stats(self):
        """测试 KV Cache 稳定性：无论怪物索引如何变动、血量格挡如何变化，条目均按规范字母序排列，且不含动态浮动数值"""
        # Turn 1: 哨兵 A 与 哨兵 B
        m_sentry = Monster(index=0, id="Sentry", name="Sentry", current_hp=40, max_hp=40, block=0)
        m_nob = Monster(index=1, id="GremlinNob", name="Gremlin Nob", current_hp=80, max_hp=80, block=0)

        dossiers_turn_1 = format_monster_dossiers([m_sentry, m_nob])

        # Turn 2: 怪物顺序在数组中颠倒，血量被扣减，增加了临时格挡
        m_sentry_damaged = Monster(index=0, id="Sentry", name="Sentry", current_hp=12, max_hp=40, block=15)
        m_nob_damaged = Monster(index=1, id="GremlinNob", name="Gremlin Nob", current_hp=45, max_hp=80, block=8)

        # 数组顺序颠倒: [Nob, Sentry]
        dossiers_turn_2 = format_monster_dossiers([m_nob_damaged, m_sentry_damaged])

        # 验证生成的输出在字节级绝对 100% 相同（保证 KV Cache 击中率）
        self.assertEqual(dossiers_turn_1, dossiers_turn_2)
        # Gremlin Nob 应排在 Sentry 前面 (G < S)
        self.assertIn("[Gremlin Nob]", dossiers_turn_1[0])

    def test_summon_and_spawn_tagging(self):
        """测试战斗中动态召唤/分裂怪物打上召唤标记"""
        dagger = Monster(index=1, id="Dagger", name="Dagger", current_hp=20, max_hp=20)
        repto = Monster(index=0, id="Reptomancer", name="Reptomancer", current_hp=190, max_hp=190)

        dossiers = format_monster_dossiers([repto, dagger])
        dagger_line = [line for line in dossiers if "[Snake Dagger]" in line][0]
        self.assertIn("⚠️ [SUMMON/SPAWN]", dagger_line)

    def test_compressor_dynamic_injection(self):
        """测试 StateCompressor 在战斗 DSL 中成功动态注入 MONSTER_TACTICAL_DOSSIER"""
        monster = Monster(index=0, id="GremlinNob", name="Gremlin Nob", current_hp=82, max_hp=82)
        card = Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6, can_use=True)

        combat_state = CombatState(
            player=self.player,
            monsters=[monster],
            hand=[card],
            draw_pile=[],
            discard_pile=[],
            exhaust_pile=[],
            turn=1,
        )

        dsl = StateCompressor.compress_combat(combat_state)
        self.assertIn("MONSTER_TACTICAL_DOSSIER:", dsl)
        self.assertIn("[Gremlin Nob]", dsl)
        self.assertIn("MECHANICS:", dsl)
        self.assertIn("TACTICS:", dsl)
        self.assertIn("DO NOT play non-lethal Skill", dsl)

    def test_compressor_dynamic_summon_injection_on_split(self):
        """测试开局大史莱姆 -> 分裂后小史莱姆的动态情报注入"""
        # 回合 1：大史莱姆
        slime_boss = Monster(index=0, id="SlimeBoss", name="Slime Boss", current_hp=140, max_hp=140)
        state_turn1 = CombatState(
            player=self.player,
            monsters=[slime_boss],
            hand=[],
            draw_pile=[],
            discard_pile=[],
            exhaust_pile=[],
            turn=1,
        )
        dsl_t1 = StateCompressor.compress_combat(state_turn1)
        self.assertIn("[Slime Boss]", dsl_t1)
        self.assertIn("Split", dsl_t1)

        # 回合 2：分裂出 2 只中史莱姆 (SpikeSlime_L, AcidSlime_L)
        spike = Monster(index=0, id="SpikeSlime_L", name="Spike Slime (L)", current_hp=28, max_hp=28)
        acid = Monster(index=1, id="AcidSlime_L", name="Acid Slime (L)", current_hp=28, max_hp=28)
        state_turn2 = CombatState(
            player=self.player,
            monsters=[spike, acid],
            hand=[],
            draw_pile=[],
            discard_pile=[],
            exhaust_pile=[],
            turn=2,
        )
        dsl_t2 = StateCompressor.compress_combat(state_turn2)
        self.assertIn("MONSTER_TACTICAL_DOSSIER:", dsl_t2)
        self.assertIn("Spike Slime", dsl_t2)
        self.assertIn("Acid Slime", dsl_t2)


if __name__ == "__main__":
    unittest.main()

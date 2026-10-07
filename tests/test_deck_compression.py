import unittest
from spire_agent.models import Card
from spire_agent.compressor import StateCompressor


class TestDeckCompression(unittest.TestCase):
    def setUp(self):
        self.strike = Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6)
        self.strike_plus = Card(index=1, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=9, upgraded=True)
        self.defend = Card(index=2, id="Defend_R", name="Defend", cost=1, type="SKILL", block=5)
        self.bash = Card(index=3, id="Bash", name="Bash", cost=2, type="ATTACK", damage=8)
        self.bash_plus = Card(index=4, id="Bash", name="Bash", cost=2, type="ATTACK", damage=10, upgraded=True)
        self.whirlwind = Card(index=5, id="Whirlwind", name="Whirlwind", cost=-1, type="ATTACK", damage=5)
        self.battle_trance = Card(index=6, id="Battle Trance", name="Battle Trance", cost=0, type="SKILL")
        self.shrug = Card(index=7, id="Shrug It Off", name="Shrug It Off", cost=1, type="SKILL", block=8)
        self.inflame = Card(index=8, id="Inflame", name="Inflame", cost=1, type="POWER")
        self.wound = Card(index=9, id="Wound", name="Wound", cost=-2, type="STATUS")

    def test_get_card_brief_effect(self):
        """测试提取单卡精炼标签（费用、伤害、格挡、易伤、过牌、力量等）"""
        self.assertEqual(StateCompressor.get_card_brief_effect(self.strike), "6 dmg")
        self.assertEqual(StateCompressor.get_card_brief_effect(self.strike_plus), "9 dmg")
        self.assertEqual(StateCompressor.get_card_brief_effect(self.defend), "5 blk")
        self.assertEqual(StateCompressor.get_card_brief_effect(self.bash), "8 dmg, 2 Vuln")
        self.assertEqual(StateCompressor.get_card_brief_effect(self.bash_plus), "10 dmg, 3 Vuln")
        self.assertEqual(StateCompressor.get_card_brief_effect(self.whirlwind), "5 dmg/E AOE")
        self.assertEqual(StateCompressor.get_card_brief_effect(self.battle_trance), "Draw 3")
        self.assertEqual(StateCompressor.get_card_brief_effect(self.shrug), "8 blk, Draw 1")
        self.assertEqual(StateCompressor.get_card_brief_effect(self.inflame), "+2 Str")
        self.assertIn("Unplayable", StateCompressor.get_card_brief_effect(self.wound))

    def test_compress_deck_summary_no_cutoff_and_structured(self):
        """测试结构化牌库画像：分类归纳、升级状态、无 Top 10 截断"""
        # 构建一个拥有 14 张牌（含 4 种打击、2 种痛击、技能与能力）的牌库
        deck = [
            self.strike, self.strike, self.strike, self.strike,
            self.strike_plus,
            self.bash, self.bash_plus,
            self.defend, self.defend, self.defend,
            self.battle_trance, self.shrug,
            self.inflame,
            self.wound,
        ]
        lines = StateCompressor.compress_deck_summary(deck)
        summary_text = "\n".join(lines)

        # 验证全局统计头部
        self.assertIn("CURRENT DECK STATUS (14 cards | 7 Attacks, 5 Skills, 1 Powers, 1 Curses/Status | Upgrades: 2/14)", summary_text)

        # 验证分类
        self.assertIn("- ATTACKS (7):", summary_text)
        self.assertIn("Strike x4 [1E] (6 dmg)", summary_text)
        self.assertIn("Strike+ [1E] (9 dmg)", summary_text)
        self.assertIn("Bash [2E] (8 dmg, 2 Vuln)", summary_text)
        self.assertIn("Bash+ [2E] (10 dmg, 3 Vuln)", summary_text)

        self.assertIn("- SKILLS (5):", summary_text)
        self.assertIn("Defend x3 [1E] (5 blk)", summary_text)
        self.assertIn("Battle Trance [0E] (Draw 3)", summary_text)
        self.assertIn("Shrug It Off [1E] (8 blk, Draw 1)", summary_text)

        self.assertIn("- POWERS (1):", summary_text)
        self.assertIn("Inflame [1E] (+2 Str)", summary_text)

        self.assertIn("- CURSES/STATUS (1):", summary_text)
        self.assertIn("Wound", summary_text)

    def test_clean_card_description(self):
        """测试清洗卡牌占位符如 !D!, !B!, NL"""
        raw_card = Card(
            index=0,
            id="UnknownCustom",
            name="Custom Card",
            cost=1,
            type="ATTACK",
            damage=12,
            block=6,
            description="Deal !D! damage. NL Gain !B! Block. NL Exhaust.",
        )
        cleaned = StateCompressor.clean_card_description(raw_card)
        self.assertNotIn("!D!", cleaned)
        self.assertNotIn("!B!", cleaned)
        self.assertNotIn("NL", cleaned)
        self.assertIn("Deal 12 damage.", cleaned)
        self.assertIn("Gain 6 Block.", cleaned)
        self.assertIn("Exhaust.", cleaned)

    def test_compress_card_reward_enriched(self):
        """测试战利品选牌界面完整输入生成"""
        deck = [self.strike, self.defend, self.bash_plus, self.inflame]
        offered = [
            Card(index=0, id="Carnage", name="Carnage", cost=2, type="ATTACK", damage=20),
            Card(index=1, id="Feel No Pain", name="Feel No Pain", cost=1, type="POWER"),
        ]
        text = StateCompressor.compress_card_reward(
            deck=deck,
            relics=["Burning Blood", "Vajra"],
            offered_cards=offered,
            can_skip=True,
        )

        self.assertIn("=== CARD REWARD SELECTION ===", text)
        self.assertIn("CURRENT DECK STATUS (4 cards | 2 Attacks, 1 Skills, 1 Powers | Upgrades: 1/4):", text)
        self.assertIn("Bash+ [2E] (10 dmg, 3 Vuln)", text)
        self.assertIn("RELICS: [Burning Blood, Vajra]", text)
        self.assertIn("OFFERED CARDS:", text)
        self.assertIn("* [card_0] Carnage (2E, ATTACK) -> Ethereal. Deal 20 (28) damage.", text)
        self.assertIn("* [card_1] Feel No Pain (1E, POWER) -> Whenever a card is Exhausted, gain 3 (4) Block.", text)
        self.assertIn("* [skip] Skip card reward", text)


if __name__ == "__main__":
    unittest.main()

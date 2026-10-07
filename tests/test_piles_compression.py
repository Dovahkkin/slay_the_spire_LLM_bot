import unittest
from spire_agent.models import CombatState, Player, Monster, Card
from spire_agent.compressor import StateCompressor


class TestPilesCompression(unittest.TestCase):
    def test_compress_combat_piles_with_cards(self):
        player = Player(current_hp=80, max_hp=80, energy=3, block=0)
        monster = Monster(index=0, id="Cultist", name="Cultist", current_hp=50, max_hp=50, intent="ATTACK", move_damage=6, move_hits=1)
        hand = [
            Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", damage=6),
        ]
        draw_pile = ["Strike", "Defend", "Strike", "Defend", "Bash"]
        discard_pile = ["Flex", "Carnage"]
        exhaust_pile = ["Offering"]

        state = CombatState(
            turn=1,
            player=player,
            monsters=[monster],
            hand=hand,
            draw_pile=draw_pile,
            discard_pile=discard_pile,
            exhaust_pile=exhaust_pile,
            draw_pile_count=5,
            discard_pile_count=2,
            exhaust_pile_count=1,
        )

        compressed = StateCompressor.compress_combat(state)

        # 验证 CARD_PILES 标记
        self.assertIn("CARD_PILES:", compressed)

        # 验证 DRAW_PILE 包含 UNORDERED pool 提示和同名卡聚合
        self.assertIn("DRAW_PILE (5 cards, UNORDERED pool):", compressed)
        self.assertIn("Strike x2", compressed)
        self.assertIn("Defend x2", compressed)
        self.assertIn("Bash", compressed)

        # 验证 DISCARD_PILE
        self.assertIn("DISCARD_PILE (2 cards):", compressed)
        self.assertIn("Flex", compressed)
        self.assertIn("Carnage", compressed)

        # 验证 EXHAUST_PILE
        self.assertIn("EXHAUST_PILE (1 cards): [Offering]", compressed)

    def test_compress_combat_empty_piles(self):
        player = Player(current_hp=80, max_hp=80, energy=3, block=0)
        monster = Monster(index=0, id="Cultist", name="Cultist", current_hp=50, max_hp=50)
        hand = [Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK")]

        state = CombatState(
            turn=1,
            player=player,
            monsters=[monster],
            hand=hand,
            draw_pile=[],
            discard_pile=[],
            exhaust_pile=[],
            draw_pile_count=0,
            discard_pile_count=0,
            exhaust_pile_count=0,
        )

        compressed = StateCompressor.compress_combat(state)
        self.assertIn("DRAW_PILE (0 cards, UNORDERED pool): empty", compressed)
        self.assertIn("DISCARD_PILE (0 cards): empty", compressed)
        self.assertIn("EXHAUST_PILE (0 cards): none", compressed)


if __name__ == "__main__":
    unittest.main()

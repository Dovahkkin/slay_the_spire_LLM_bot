import unittest
from spire_agent.models import CombatState, Player, Monster, Card, Power
from spire_agent.compressor import StateCompressor
from spire_agent.knowledge.powers_db import (
    lookup_power_info,
    normalize_power_key,
    format_active_powers,
    EXCLUDED_BASIC_POWERS,
)


class TestPowersDatabase(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_power_key("Curl Up"), "curlup")
        self.assertEqual(normalize_power_key("Mode Shift"), "modeshift")
        self.assertEqual(normalize_power_key("Mode_Shift"), "modeshift")
        self.assertEqual(normalize_power_key("Flame-Barrier"), "flamebarrier")
        self.assertEqual(normalize_power_key("ENRAGE"), "enrage")

    def test_lookup_power_info(self):
        nob_enrage = lookup_power_info("Enrage")
        self.assertIsNotNone(nob_enrage)
        self.assertEqual(nob_enrage["name"], "Enrage")
        self.assertIn("SKILL", nob_enrage["desc"])
        self.assertIn("AVOID PLAYING SKILLS", nob_enrage["warning"])

        louse_curl = lookup_power_info("curl_up")
        self.assertIsNotNone(louse_curl)
        self.assertEqual(louse_curl["name"], "Curl Up")

        player_flame = lookup_power_info("Flame Barrier")
        self.assertIsNotNone(player_flame)
        self.assertIn("deals {amount} damage back", player_flame["desc"])

        entangled = lookup_power_info("Entangled")
        self.assertIsNotNone(entangled)
        self.assertEqual(entangled["type"], "DEBUFF")
        self.assertIn("cannot play Attack", entangled["desc"])

    def test_basic_powers_excluded(self):
        # Strength, Dexterity, Vulnerable, Weak, Frail, Block should not be dynamically injected
        p_powers = [
            Power(id="Strength", name="Strength", amount=3),
            Power(id="Dexterity", name="Dexterity", amount=2),
            Power(id="Frail", name="Frail", amount=1),
        ]
        m_powers = [
            Power(id="Vulnerable", name="Vulnerable", amount=2),
            Power(id="Weak", name="Weak", amount=1),
        ]
        monster = Monster(
            index=0,
            id="Louse",
            name="Red Louse",
            current_hp=15,
            max_hp=15,
            powers=m_powers
        )

        formatted = format_active_powers(p_powers, [monster])
        self.assertEqual(formatted, [], "Basic powers must be excluded from dynamic injection")

    def test_special_powers_formatted_correctly(self):
        p_powers = [
            Power(id="Flame Barrier", name="Flame Barrier", amount=4),
            Power(id="Entangled", name="Entangled", amount=1),
            Power(id="Strength", name="Strength", amount=2),  # Excluded
        ]
        m_powers = [
            Power(id="Enrage", name="Enrage", amount=2),
            Power(id="Vulnerable", name="Vulnerable", amount=1),  # Excluded
        ]
        monster = Monster(
            index=0,
            id="GremlinNob",
            name="Gremlin Nob",
            current_hp=80,
            max_hp=80,
            powers=m_powers
        )

        formatted = format_active_powers(p_powers, [monster])
        self.assertEqual(len(formatted), 3)

        # Check Player Flame Barrier
        flame_line = [line for line in formatted if "Flame Barrier" in line][0]
        self.assertIn("deals 4 damage back", flame_line)
        self.assertIn("(Player)", flame_line)

        # Check Player Entangled
        entangled_line = [line for line in formatted if "Entangled" in line][0]
        self.assertIn("cannot play Attack cards", entangled_line)
        self.assertIn("DO NOT PLAN ATTACKS", entangled_line)

        # Check Monster Enrage
        enrage_line = [line for line in formatted if "Enrage" in line][0]
        self.assertIn("gains 2 Strength", enrage_line)
        self.assertIn("AVOID PLAYING SKILLS", enrage_line)
        self.assertIn("(E0 Gremlin Nob)", enrage_line)

    def test_compressor_integration_without_special_powers(self):
        player = Player(
            current_hp=80,
            max_hp=80,
            energy=3,
            block=0,
            powers=[Power(id="Strength", name="Strength", amount=1)]
        )
        monster = Monster(
            index=0,
            id="JawWorm",
            name="Jaw Worm",
            current_hp=40,
            max_hp=40,
            move_damage=11,
            powers=[]
        )
        card = Card(
            index=0,
            id="Strike_R",
            name="Strike",
            cost=1,
            type="ATTACK",
            damage=6
        )
        state = CombatState(
            player=player,
            monsters=[monster],
            hand=[card],
            turn=1
        )

        compressed = StateCompressor.compress_combat(state)
        # Should NOT contain ACTIVE_STATUS_EFFECTS block
        self.assertNotIn("ACTIVE_STATUS_EFFECTS:", compressed)

    def test_compressor_integration_with_special_powers(self):
        player = Player(
            current_hp=70,
            max_hp=80,
            energy=3,
            block=0,
            powers=[Power(id="Flame Barrier", name="Flame Barrier", amount=4)]
        )
        monster = Monster(
            index=0,
            id="GremlinNob",
            name="Gremlin Nob",
            current_hp=82,
            max_hp=82,
            move_damage=14,
            powers=[Power(id="Enrage", name="Enrage", amount=2)]
        )
        card = Card(
            index=0,
            id="Strike_R",
            name="Strike",
            cost=1,
            type="ATTACK",
            damage=6
        )
        state = CombatState(
            player=player,
            monsters=[monster],
            hand=[card],
            turn=2
        )

        compressed = StateCompressor.compress_combat(state)
        self.assertIn("ACTIVE_STATUS_EFFECTS:", compressed)
        self.assertIn("Flame Barrier:4 (Player)", compressed)
        self.assertIn("Enrage:2 (E0 Gremlin Nob)", compressed)
        self.assertIn("AVOID PLAYING SKILLS", compressed)


if __name__ == "__main__":
    unittest.main()

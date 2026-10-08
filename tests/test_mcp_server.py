"""
Unit tests for Slay the Spire MCP Server
Verifies tool endpoints: get_game_state, calculate_damage, play_card, end_turn, choose_option, proceed, solver_health.
"""

import os
import unittest
from spire_agent.mcp_server import (
    get_game_state,
    calculate_damage,
    play_card,
    end_turn,
    choose_option,
    proceed,
    cancel_or_skip,
    reset_scenario,
    solver_health,
)


class TestMCPServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._old_driver_env = os.environ.get("SPIRE_DRIVER")
        os.environ["SPIRE_DRIVER"] = "mock"

    @classmethod
    def tearDownClass(cls):
        if cls._old_driver_env is None:
            os.environ.pop("SPIRE_DRIVER", None)
        else:
            os.environ["SPIRE_DRIVER"] = cls._old_driver_env

    def setUp(self):
        reset_scenario("cultist")

    def test_solver_health(self):
        res = solver_health()
        self.assertIn("ONLINE", res)
        self.assertIn("FastMCP", res)

    def test_get_game_state_combat(self):
        res = get_game_state()
        self.assertIn("COMBAT TURN 1", res)
        self.assertIn("Cultist", res)
        self.assertIn("HAND CARDS", res)

    def test_calculate_damage_and_lethal(self):
        # Cultist has 48 HP, not lethal
        calc_res = calculate_damage([0, 1])
        self.assertIn("精准伤害推演核算结果", calc_res)
        self.assertIn("未能直接斩杀", calc_res)

        # Switch to lethal scenario
        reset_scenario("lethal")
        calc_lethal = calculate_damage([1, 0])
        self.assertIn("LETHAL SUCCESSFUL", calc_lethal)

    def test_play_card_flow(self):
        res = play_card(0)  # Strike
        self.assertIn("[SUCCESS]", res)
        self.assertIn("Strike", res)
        # Cultist took 6 damage (48 -> 42)
        self.assertIn("42/48", res)

    def test_end_turn_flow(self):
        res = end_turn()
        self.assertIn("[SUCCESS]", res)
        self.assertIn("COMBAT TURN 2", res)

    def test_combat_victory_to_reward(self):
        reset_scenario("lethal")
        play_card(1, 0)  # Bash
        res = play_card(0, 0)  # Strike kills Gremlin
        self.assertIn("[SCREEN: COMBAT_REWARD]", res)
        self.assertIn("GOLD", res)

        # Claim gold reward
        claim_res = choose_option(0)
        self.assertIn("[SUCCESS]", claim_res)

    def test_card_reward_and_skip(self):
        reset_scenario("card_reward")
        state_str = get_game_state()
        self.assertIn("[SCREEN: CARD_REWARD]", state_str)
        self.assertIn("Carnage", state_str)

        skip_res = cancel_or_skip()
        self.assertIn("[SUCCESS]", skip_res)
        self.assertIn("[SCREEN: MAP]", skip_res)


if __name__ == "__main__":
    unittest.main()

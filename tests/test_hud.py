import unittest
import time
from spire_agent.hud import SpireHud, DummyHud


class TestSpireHud(unittest.TestCase):
    def test_dummy_hud_interface(self):
        hud = DummyHud()
        hud.update_blackboard(archetype="力量战", win_con="重刃斩杀")
        hud.update_thinking(thought="计算伤害中...", action="PLAY 0 0")
        hud.say(thought="兼容测试", action="END_TURN")
        hud.close()

    def test_spire_hud_lifecycle(self):
        hud = SpireHud()
        time.sleep(0.3)
        hud.update_blackboard(
            archetype="完美打击流 (Perfected Strike)",
            win_con="堆叠打击单卡暴力碾压",
            play_guide="大额平砍快速斩杀",
            drafting_focus="抓取柄击、双重打击",
            postmortem={
                "floor": 6,
                "encounter": "大红 Gremlin Nob",
                "turns": 3,
                "hp_lost": 12,
                "remaining_hp": 68,
                "max_hp": 80,
                "summary": "暴力强秒，战损可控",
            },
        )
        hud.update_thinking(
            thought="敌人意图蓄力，本回合全力输出斩杀",
            action="PERFECTED_STRIKE -> E0 ➔ STRIKE -> E0",
            status="第 6 层 | HP: 68/80 | 能量: 3/3",
            badge="⚡ 致命斩杀",
            badge_color="#ff4757",
        )
        time.sleep(0.3)
        hud.close()


if __name__ == "__main__":
    unittest.main()

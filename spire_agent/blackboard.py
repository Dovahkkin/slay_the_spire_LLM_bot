import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("spire_agent.blackboard")


@dataclass
class CombatPostmortem:
    floor: int
    encounter: str
    turns: int
    hp_lost: int
    remaining_hp: int
    max_hp: int
    summary: str


class RunBlackboard:
    """
    杀戮尖塔 Agent 共享战略黑板 (Shared Strategic Blackboard)
    
    设计理念（共享文件系统 / 黑板模式）：
    - MacroSession (宏观大脑) 与 CombatSession (战术先锋) 的通信中枢；
    - 宏观大脑在选牌/商店/锻造后，在此撰写与更新【当前流派定位与作战锦囊】；
    - 战术先锋在每回合战斗打响时读取锦囊；战斗结束后将【实战战损与牌组短板反思】写回黑板；
    - 实时持久化为项目根目录的 run_memo.md，供开发者直观监控与排查。
    """

    def __init__(self, file_path: Optional[str] = None, hud: Optional[Any] = None):
        self.file_path = Path(file_path or (Path(__file__).parent.parent / "run_memo.md"))
        self.hud = hud
        
        # 宏观战略规划
        self.archetype: str = "Starter Deck / Early Transition"
        self.win_con: str = "Leverage frontloaded physical attack cards (Carnage, Cleave, Heavy Blade) to establish damage advantage and survive Act 1 elites."
        self.play_guide: str = "Prioritize calculating lethal; avoid over-blocking. Full block when incoming threat is high, all-out attack when enemy buffs/debuffs."
        self.drafting_focus: str = "Find premium single-target burst attacks and AoE clear cards to prepare for Act 1 elites."

        # 战术战后反馈
        self.latest_combat: Optional[CombatPostmortem] = None
        self.combat_history: List[CombatPostmortem] = []

        # 初始化时尝试从本地加载已有的黑板记录
        self.load()
        self.notify_hud()

    def notify_hud(self):
        """通知 HUD 悬浮窗更新黑板显示内容"""
        if not self.hud:
            return
        post_info = None
        if self.latest_combat:
            post_info = {
                "floor": self.latest_combat.floor,
                "encounter": self.latest_combat.encounter,
                "turns": self.latest_combat.turns,
                "hp_lost": self.latest_combat.hp_lost,
                "remaining_hp": self.latest_combat.remaining_hp,
                "max_hp": self.latest_combat.max_hp,
                "summary": self.latest_combat.summary,
            }
        try:
            self.hud.update_blackboard(
                archetype=self.archetype,
                win_con=self.win_con,
                play_guide=self.play_guide,
                drafting_focus=self.drafting_focus,
                postmortem=post_info,
            )
        except Exception as e:
            logger.debug(f"[Blackboard] 通知 HUD 异常: {e}")

    def update_macro_memo(
        self,
        archetype: str,
        win_con: str,
        play_guide: str,
        drafting_focus: str,
    ):
        """宏观会话选牌或调整战略后调用：更新作战锦囊"""
        self.archetype = archetype.strip() or self.archetype
        self.win_con = win_con.strip() or self.win_con
        self.play_guide = play_guide.strip() or self.play_guide
        self.drafting_focus = drafting_focus.strip() or self.drafting_focus
        logger.info(f"[Blackboard] 宏观战略备忘已更新: [{self.archetype}]")
        self.save()
        self.notify_hud()

    def record_combat_postmortem(
        self,
        floor: int,
        encounter: str,
        turns: int,
        hp_lost: int,
        remaining_hp: int,
        max_hp: int,
        summary: str,
    ):
        """战斗结束后战术会话调用：记录实战表现与短板反思"""
        postmortem = CombatPostmortem(
            floor=floor,
            encounter=encounter,
            turns=turns,
            hp_lost=hp_lost,
            remaining_hp=remaining_hp,
            max_hp=max_hp,
            summary=summary.strip(),
        )
        self.latest_combat = postmortem
        self.combat_history.append(postmortem)
        if len(self.combat_history) > 10:
            self.combat_history.pop(0)

        logger.info(
            f"[Blackboard] 战后实战反思已归档: 第 {floor} 层 [{encounter}] (战损 {hp_lost} HP, 耗时 {turns} 回合)"
        )
        self.save()
        self.notify_hud()

    def get_combat_briefing(self) -> str:
        """为 CombatSession 导出战前战略锦囊提示词"""
        return (
            f"Deck Archetype: {self.archetype}\n"
            f"Win Condition: {self.win_con}\n"
            f"Combat Play Guide: {self.play_guide}"
        )

    def get_macro_context(self) -> str:
        """为 MacroSession 导出选牌与长线规划上下文"""
        lines = [
            f"Current Deck Archetype: {self.archetype}",
            f"Strategic Drafting Focus: {self.drafting_focus}",
        ]
        if self.latest_combat:
            c = self.latest_combat
            lines.append(
                f"Latest Combat Reflection (Floor {c.floor} [{c.encounter}]): "
                f"Duration {c.turns} turns, HP lost {c.hp_lost} (Remaining: {c.remaining_hp}/{c.max_hp}).\n"
                f"Postmortem Reflection: {c.summary}"
            )
        return "\n".join(lines)

    def save(self):
        """将黑板状态序列化写入 run_memo.md 文件"""
        try:
            content = self._render_markdown()
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            logger.warning(f"[Blackboard] 保存 run_memo.md 失败: {e}")

    def load(self):
        """尝试从现有 run_memo.md 恢复黑板"""
        if not self.file_path.exists():
            self.save()
            return
        # 简单校验，保持文件存在即可

    def _render_markdown(self) -> str:
        md = [
            "# 🗡️ Slay the Spire Agent 战略黑板 (Run Strategic Blackboard)\n",
            "> 此文档由 MacroSession (宏观战略) 与 CombatSession (战术实战) 共同维护，实时同步全局流派规划与战况反思。\n",
            "## 🎯 宏观流派与作战锦囊 (Macro Strategic Briefing)",
            f"- **流派定位**: {self.archetype}",
            f"- **致胜终端**: {self.win_con}",
            f"- **实战打牌偏好**: {self.play_guide}",
            f"- **下步抓牌/删牌重点**: {self.drafting_focus}\n",
            "---",
            "## ⚔️ 最新战后战况反思 (Latest Combat Postmortem)",
        ]

        if self.latest_combat:
            c = self.latest_combat
            md.extend([
                f"- **战况概括**: 第 {c.floor} 层 击败 [{c.encounter}] | 耗时 {c.turns} 回合 | 战损 {c.hp_lost} HP (剩余 HP: {c.remaining_hp}/{c.max_hp})",
                f"- **实战反思**: {c.summary}\n",
            ])
        else:
            md.append("- *暂无战况记录（新冒险开始）*\n")

        md.append("---")
        md.append("## 📜 历史战况记录 (Combat History)")
        if self.combat_history:
            for item in reversed(self.combat_history[-5:]):
                md.append(
                    f"- **[第 {item.floor} 层 {item.encounter}]**: "
                    f"战损 {item.hp_lost} HP | {item.turns} 回合 | {item.summary}"
                )
        else:
            md.append("- *暂无历史记录*")

        md.append("\n")
        return "\n".join(md)

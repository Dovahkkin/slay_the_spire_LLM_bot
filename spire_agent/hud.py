import sys
import queue
import logging
import threading
from typing import Optional, Dict, Any

logger = logging.getLogger("spire_agent.hud")

try:
    import tkinter as tk
    HAS_TKINTER = True
except ImportError:
    HAS_TKINTER = False


class DummyHud:
    """无 GUI 环境或测试模式下的空实现，所有信息回退输出到日志与终端"""

    def update_blackboard(
        self,
        archetype: str = "",
        win_con: str = "",
        play_guide: str = "",
        drafting_focus: str = "",
        postmortem: Optional[Dict[str, Any]] = None,
    ):
        pass

    def update_thinking(
        self,
        thought: str,
        action: str = "",
        status: str = "",
        badge: str = "● 思考中",
        badge_color: str = "#00f0ff",
    ):
        logger.info(f"[HUD] {badge} | {status} | 操作: {action}\n  思考: {thought}")

    def say(
        self,
        thought: str,
        action: str = "",
        status: str = "",
        badge: str = "🧠 AI",
        badge_color: str = "#2ed573",
    ):
        self.update_thinking(thought, action, status, badge, badge_color)

    def update_profiler(self, summary: Dict[str, Any]):
        total = summary.get("total_time", 0.0)
        bot = summary.get("bottleneck_desc", "")
        logger.info(f"[HUD Profiler] 回合耗时: {total}s | 瓶颈: {bot}")

    def update_profiler_live(self, stage: str, desc: str = "", stage_start: float = 0.0):
        pass

    def close(self):
        pass


class SpireHud:
    """
    杀戮尖塔 Agent 双子桌面置顶透明悬浮窗 (Dual In-Game HUD Overlays)
    
    采用【形态 A：双独立分离窗口】架构：
    - 窗口 1 (Blackboard Window)：战术小黑板，展示宏观流派定位、核心赢法、抓牌重心与最新战后复盘；
    - 窗口 2 (Thinking Window)：实时推演窗，展示当前回合/界面的深度内心独白、敌我态势与即将执行的指令。
    
    两窗口均支持鼠标自由拖拽、置顶半透明显示，且在后台守护线程中安全轮询消息队列，对游戏运行零卡顿。
    """

    def __init__(
        self,
        bb_width: int = 420,
        bb_height: int = 330,
        think_width: int = 440,
        think_height: int = 270,
        perf_width: int = 450,
        perf_height: int = 260,
    ):
        self.bb_width = bb_width
        self.bb_height = bb_height
        self.think_width = think_width
        self.think_height = think_height
        self.perf_width = perf_width
        self.perf_height = perf_height

        self.msg_queue = queue.Queue()
        self.root: Optional[Any] = None
        self.win_bb: Optional[Any] = None
        self.win_think: Optional[Any] = None
        self.win_perf: Optional[Any] = None

        self.live_stage_key: str = "IDLE"
        self.live_stage_start: float = 0.0
        self.live_stage_active: bool = False

        if HAS_TKINTER:
            self.thread = threading.Thread(target=self._run_gui, daemon=True)
            self.thread.start()
        else:
            logger.warning("当前环境未安装 tkinter，HUD 自动回退为纯日志模式。")

    def _bind_drag(self, window, handle_widgets):
        """为悬浮窗绑定自由拖拽事件"""
        drag_data = {"x": 0, "y": 0}

        def start_drag(event):
            drag_data["x"] = event.x
            drag_data["y"] = event.y

        def do_drag(event):
            deltax = event.x - drag_data["x"]
            deltay = event.y - drag_data["y"]
            new_x = window.winfo_x() + deltax
            new_y = window.winfo_y() + deltay
            window.geometry(f"+{new_x}+{new_y}")

        for w in handle_widgets:
            w.bind("<Button-1>", start_drag)
            w.bind("<B1-Motion>", do_drag)

    def _run_gui(self):
        """运行 Tkinter GUI 消息泵（后台常驻线程）"""
        try:
            self.root = tk.Tk()
            self.root.withdraw()  # 隐藏主 root，由两个独立的 Toplevel 承载窗口

            # 色彩主题 (Cyber-Spire Dark Theme)
            bg_color = "#11141a"
            card_bg = "#181b24"
            header_bg = "#1f2430"
            border_color = "#2c3345"
            accent_cyan = "#00f0ff"
            accent_gold = "#ffc83b"
            accent_green = "#2ed573"
            text_white = "#f0f2f5"
            text_muted = "#8a94a6"

            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()

            # ==============================================================
            # 1. 窗口 1：战术小黑板 (Blackboard Window)
            # ==============================================================
            self.win_bb = tk.Toplevel(self.root)
            self.win_bb.title("Spire Strategic Blackboard")
            self.win_bb.overrideredirect(True)
            self.win_bb.attributes("-topmost", True)
            self.win_bb.attributes("-alpha", 0.92)
            self.win_bb.configure(bg=border_color)

            bb_x = max(10, screen_w - self.bb_width - 30)
            bb_y = 40
            self.win_bb.geometry(f"{self.bb_width}x{self.bb_height}+{bb_x}+{bb_y}")

            bb_container = tk.Frame(self.win_bb, bg=bg_color)
            bb_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

            # 顶部标题栏
            bb_header = tk.Frame(bb_container, bg=header_bg, height=28)
            bb_header.pack(fill=tk.X)
            lbl_bb_title = tk.Label(
                bb_header,
                text="📋 战术小黑板 (RUN MEMO)",
                bg=header_bg,
                fg=accent_gold,
                font=("Consolas", 10, "bold"),
            )
            lbl_bb_title.pack(side=tk.LEFT, padx=8, pady=4)

            bb_close = tk.Label(
                bb_header,
                text="✕",
                bg=header_bg,
                fg=text_muted,
                font=("Segoe UI", 10, "bold"),
                cursor="hand2",
            )
            bb_close.pack(side=tk.RIGHT, padx=8)
            bb_close.bind("<Button-1>", lambda e: self.win_bb.withdraw())
            self._bind_drag(self.win_bb, [bb_header, lbl_bb_title])

            # 宏观流派板块
            macro_card = tk.Frame(bb_container, bg=card_bg, padx=8, pady=6)
            macro_card.pack(fill=tk.X, padx=8, pady=(6, 4))

            # 流派名称
            f_arch = tk.Frame(macro_card, bg=card_bg)
            f_arch.pack(fill=tk.X)
            tk.Label(f_arch, text="🏷️ 当前流派: ", bg=card_bg, fg=accent_cyan, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
            self.lbl_archetype = tk.Label(
                f_arch,
                text="初始牌组 / 过渡期 (Starter Deck)",
                bg=card_bg,
                fg=text_white,
                font=("Segoe UI", 9, "bold"),
            )
            self.lbl_archetype.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # 核心赢法
            f_win = tk.Frame(macro_card, bg=card_bg)
            f_win.pack(fill=tk.X, pady=(2, 0))
            tk.Label(f_win, text="🎯 核心赢法: ", bg=card_bg, fg=accent_gold, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, anchor="n")
            self.lbl_win_con = tk.Label(
                f_win,
                text="利用即时物理攻击牌建立伤害优势，平稳过渡前两场精英战。",
                bg=card_bg,
                fg=text_white,
                font=("Segoe UI", 8),
                wraplength=self.bb_width - 110,
                justify="left",
                anchor="w",
            )
            self.lbl_win_con.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # 抓牌重点
            f_focus = tk.Frame(macro_card, bg=card_bg)
            f_focus.pack(fill=tk.X, pady=(2, 0))
            tk.Label(f_focus, text="📌 抓牌重点: ", bg=card_bg, fg=accent_green, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, anchor="n")
            self.lbl_drafting = tk.Label(
                f_focus,
                text="寻找优质单体爆发攻击与 AOE 清场卡，为第 1 幕精英战做准备。",
                bg=card_bg,
                fg=text_white,
                font=("Segoe UI", 8),
                wraplength=self.bb_width - 110,
                justify="left",
                anchor="w",
            )
            self.lbl_drafting.pack(side=tk.LEFT, fill=tk.X, expand=True)

            # 分割线
            sep = tk.Frame(bb_container, bg=border_color, height=1)
            sep.pack(fill=tk.X, padx=8, pady=3)

            # 战后复盘反思板块
            post_card = tk.Frame(bb_container, bg=card_bg, padx=8, pady=6)
            post_card.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

            tk.Label(
                post_card,
                text="📝 最新战后复盘 (Combat Postmortem):",
                bg=card_bg,
                fg=accent_gold,
                font=("Segoe UI", 8, "bold"),
                anchor="w",
            ).pack(fill=tk.X)

            self.lbl_postmortem_header = tk.Label(
                post_card,
                text="暂无战况记录（新冒险开始）",
                bg=card_bg,
                fg=accent_cyan,
                font=("Consolas", 8, "bold"),
                anchor="w",
            )
            self.lbl_postmortem_header.pack(fill=tk.X, pady=(2, 1))

            self.lbl_postmortem_summary = tk.Label(
                post_card,
                text="等待首场战斗打响与复盘总结...",
                bg=card_bg,
                fg=text_white,
                font=("Microsoft YaHei", 8),
                wraplength=self.bb_width - 40,
                justify="left",
                anchor="nw",
            )
            self.lbl_postmortem_summary.pack(fill=tk.BOTH, expand=True)

            # ==============================================================
            # 2. 窗口 2：实时推演与动作窗 (Thinking Window)
            # ==============================================================
            self.win_think = tk.Toplevel(self.root)
            self.win_think.title("Spire Agent Thinking")
            self.win_think.overrideredirect(True)
            self.win_think.attributes("-topmost", True)
            self.win_think.attributes("-alpha", 0.92)
            self.win_think.configure(bg=border_color)

            think_x = max(10, screen_w - self.think_width - 30)
            think_y = bb_y + self.bb_height + 15
            if think_y + self.think_height > screen_h - 40:
                think_y = max(40, screen_h - self.think_height - 50)

            self.win_think.geometry(f"{self.think_width}x{self.think_height}+{think_x}+{think_y}")

            think_container = tk.Frame(self.win_think, bg=bg_color)
            think_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

            # 顶部标题栏
            think_header = tk.Frame(think_container, bg=header_bg, height=28)
            think_header.pack(fill=tk.X)

            lbl_think_title = tk.Label(
                think_header,
                text="🧠 AGENT 实时推演",
                bg=header_bg,
                fg=accent_cyan,
                font=("Consolas", 10, "bold"),
            )
            lbl_think_title.pack(side=tk.LEFT, padx=8, pady=4)

            self.lbl_badge = tk.Label(
                think_header,
                text="● READY",
                bg="#262b3a",
                fg=accent_green,
                font=("Segoe UI", 8, "bold"),
                padx=6,
                pady=1,
            )
            self.lbl_badge.pack(side=tk.LEFT, padx=4)

            think_close = tk.Label(
                think_header,
                text="✕",
                bg=header_bg,
                fg=text_muted,
                font=("Segoe UI", 10, "bold"),
                cursor="hand2",
            )
            think_close.pack(side=tk.RIGHT, padx=8)
            think_close.bind("<Button-1>", lambda e: self.win_think.withdraw())
            self._bind_drag(self.win_think, [think_header, lbl_think_title])

            # 状态简报行 (血量/层数/能量)
            self.lbl_status = tk.Label(
                think_container,
                text="准备就绪，等待游戏信号...",
                bg=bg_color,
                fg=accent_gold,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            )
            self.lbl_status.pack(fill=tk.X, padx=10, pady=(6, 2))

            # 核心思考推演对话框
            thought_frame = tk.Frame(think_container, bg=card_bg, padx=8, pady=6)
            thought_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=3)

            self.lbl_thought = tk.Label(
                thought_frame,
                text="「双 Session 智能体已联机，战术先锋与宏观大脑协同推演中...」",
                bg=card_bg,
                fg=text_white,
                font=("Microsoft YaHei", 9),
                wraplength=self.think_width - 40,
                justify="left",
                anchor="nw",
            )
            self.lbl_thought.pack(fill=tk.BOTH, expand=True)

            # 底部动作行
            self.lbl_action = tk.Label(
                think_container,
                text="▶ 等待操作",
                bg=bg_color,
                fg=accent_cyan,
                font=("Consolas", 9, "bold"),
                anchor="w",
            )
            self.lbl_action.pack(fill=tk.X, padx=10, pady=(3, 6))

            # ==============================================================
            # 3. 窗口 3：性能与耗时监控窗 (Performance & Latency Window)
            # ==============================================================
            self.win_perf = tk.Toplevel(self.root)
            self.win_perf.title("Spire Agent Profiler")
            self.win_perf.overrideredirect(True)
            self.win_perf.attributes("-topmost", True)
            self.win_perf.attributes("-alpha", 0.92)
            self.win_perf.configure(bg=border_color)

            perf_x = 30
            perf_y = 40
            self.win_perf.geometry(f"{self.perf_width}x{self.perf_height}+{perf_x}+{perf_y}")

            perf_container = tk.Frame(self.win_perf, bg=bg_color)
            perf_container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

            # 顶部标题栏
            perf_header = tk.Frame(perf_container, bg=header_bg, height=28)
            perf_header.pack(fill=tk.X)

            lbl_perf_title = tk.Label(
                perf_header,
                text="⏱️ AGENT 性能与延迟监控",
                bg=header_bg,
                fg=accent_gold,
                font=("Consolas", 10, "bold"),
            )
            lbl_perf_title.pack(side=tk.LEFT, padx=8, pady=4)

            self.lbl_perf_badge = tk.Label(
                perf_header,
                text="● READY",
                bg="#262b3a",
                fg=accent_green,
                font=("Segoe UI", 8, "bold"),
                padx=6,
                pady=1,
            )
            self.lbl_perf_badge.pack(side=tk.LEFT, padx=4)

            perf_close = tk.Label(
                perf_header,
                text="✕",
                bg=header_bg,
                fg=text_muted,
                font=("Segoe UI", 10, "bold"),
                cursor="hand2",
            )
            perf_close.pack(side=tk.RIGHT, padx=8)
            perf_close.bind("<Button-1>", lambda e: self.win_perf.withdraw())
            self._bind_drag(self.win_perf, [perf_header, lbl_perf_title])

            # 实时状态与秒表卡片
            live_card = tk.Frame(perf_container, bg=card_bg, padx=8, pady=5)
            live_card.pack(fill=tk.X, padx=8, pady=5)

            f_live_top = tk.Frame(live_card, bg=card_bg)
            f_live_top.pack(fill=tk.X)

            self.lbl_live_stage = tk.Label(
                f_live_top,
                text="当前阶段: 🟢 待命中 (Idle)",
                bg=card_bg,
                fg=text_white,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            )
            self.lbl_live_stage.pack(side=tk.LEFT, fill=tk.X, expand=True)

            self.lbl_live_timer = tk.Label(
                f_live_top,
                text="0.0s ⏳",
                bg=card_bg,
                fg=accent_cyan,
                font=("Consolas", 10, "bold"),
            )
            self.lbl_live_timer.pack(side=tk.RIGHT)

            self.lbl_perf_alarm = tk.Label(
                live_card,
                text="延迟状态: 正常 (Normal)",
                bg=card_bg,
                fg=accent_green,
                font=("Segoe UI", 8),
                anchor="w",
            )
            self.lbl_perf_alarm.pack(fill=tk.X, pady=(2, 0))

            # 上一轮耗时瀑布流
            breakdown_card = tk.Frame(perf_container, bg=card_bg, padx=8, pady=5)
            breakdown_card.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 5))

            tk.Label(
                breakdown_card,
                text="📊 上一轮各阶段耗时瀑布图 (Timing Breakdown):",
                bg=card_bg,
                fg=text_muted,
                font=("Segoe UI", 8, "bold"),
                anchor="w",
            ).pack(fill=tk.X, pady=(0, 2))

            self.lbl_bar_game = tk.Label(
                breakdown_card,
                text="  - 游戏同步 (Game I/O):  -- s  [----------]   --%",
                bg=card_bg,
                fg="#a0a8b9",
                font=("Consolas", 8),
                anchor="w",
            )
            self.lbl_bar_game.pack(fill=tk.X)

            self.lbl_bar_comp = tk.Label(
                breakdown_card,
                text="  - 状态压缩 (Compress):  -- s  [----------]   --%",
                bg=card_bg,
                fg="#a0a8b9",
                font=("Consolas", 8),
                anchor="w",
            )
            self.lbl_bar_comp.pack(fill=tk.X)

            self.lbl_bar_llm = tk.Label(
                breakdown_card,
                text="  - 模型推理 (LLM Call):  -- s  [----------]   --%",
                bg=card_bg,
                fg="#00f0ff",
                font=("Consolas", 8),
                anchor="w",
            )
            self.lbl_bar_llm.pack(fill=tk.X)

            self.lbl_bar_act = tk.Label(
                breakdown_card,
                text="  - 动作执行 (Action):    -- s  [----------]   --%",
                bg=card_bg,
                fg="#a0a8b9",
                font=("Consolas", 8),
                anchor="w",
            )
            self.lbl_bar_act.pack(fill=tk.X)

            # 底部汇总
            self.lbl_perf_summary = tk.Label(
                perf_container,
                text="回合总耗时: -- | 最大瓶颈: --",
                bg=bg_color,
                fg=accent_gold,
                font=("Consolas", 8, "bold"),
                anchor="w",
            )
            self.lbl_perf_summary.pack(fill=tk.X, padx=10, pady=(0, 5))

            # 启动队列事件循环
            self._poll_queue()
            self.root.mainloop()

        except Exception as e:
            logger.error(f"HUD GUI 初始化发生异常: {e}")

    def _poll_queue(self):
        """定期从线程安全队列拉取并刷新 UI"""
        if not self.root:
            return

        try:
            while True:
                data = self.msg_queue.get_nowait()
                msg_type = data.get("type")

                if msg_type == "blackboard":
                    self._apply_blackboard(data)
                elif msg_type == "thinking":
                    self._apply_thinking(data)
                elif msg_type == "profiler":
                    self._apply_profiler(data)
                elif msg_type == "profiler_live":
                    self._apply_profiler_live(data)

        except queue.Empty:
            pass
        except Exception as e:
            logger.debug(f"HUD 刷新异常: {e}")

        # 刷新实时秒表 (平滑走字)
        if getattr(self, "live_stage_active", False) and hasattr(self, "lbl_live_timer"):
            try:
                import time
                elapsed = time.perf_counter() - self.live_stage_start
                self.lbl_live_timer.config(text=f"{elapsed:.1f}s ⏳")
                if elapsed > 10.0 and "llm" in getattr(self, "live_stage_key", ""):
                    self.lbl_perf_alarm.config(text="🚨 警报: API 响应极慢 (>10s), 存在超时或卡死风险!", fg="#ff4757")
                elif elapsed > 5.0 and "llm" in getattr(self, "live_stage_key", ""):
                    self.lbl_perf_alarm.config(text="⚠️ 提示: API 延迟偏高 (>5s), 请关注网络或服务负载", fg="#ffc83b")
            except Exception:
                pass

        self.root.after(60, self._poll_queue)

    def _apply_blackboard(self, data: Dict[str, Any]):
        """更新小黑板窗口"""
        if not self.win_bb:
            return

        # 确保窗口若是被关闭过，则重新展现
        if not self.win_bb.winfo_viewable():
            self.win_bb.deiconify()

        archetype = data.get("archetype")
        win_con = data.get("win_con")
        drafting_focus = data.get("drafting_focus")
        postmortem = data.get("postmortem")

        if archetype:
            self.lbl_archetype.config(text=archetype)
        if win_con:
            self.lbl_win_con.config(text=win_con)
        if drafting_focus:
            self.lbl_drafting.config(text=drafting_focus)

        if postmortem:
            floor = postmortem.get("floor", 0)
            encounter = postmortem.get("encounter", "未知敌人")
            turns = postmortem.get("turns", 0)
            hp_lost = postmortem.get("hp_lost", 0)
            rem_hp = postmortem.get("remaining_hp", 0)
            max_hp = postmortem.get("max_hp", 80)
            summary = postmortem.get("summary", "")

            color = "#2ed573" if hp_lost == 0 else ("#ff4757" if hp_lost >= 15 else "#ffc83b")
            self.lbl_postmortem_header.config(
                text=f"第 {floor} 层 [{encounter}] | 战损 {hp_lost} HP | {turns} 回合 (剩余 HP: {rem_hp}/{max_hp})",
                fg=color,
            )
            self.lbl_postmortem_summary.config(text=summary or "战况正常")

    def _apply_thinking(self, data: Dict[str, Any]):
        """更新实时思考窗口"""
        if not self.win_think:
            return

        if not self.win_think.winfo_viewable():
            self.win_think.deiconify()

        thought = data.get("thought")
        action = data.get("action")
        status = data.get("status")
        badge = data.get("badge")

        if badge:
            text, color = badge
            self.lbl_badge.config(text=text, fg=color)
        if status is not None:
            self.lbl_status.config(text=status)
        if thought is not None:
            self.lbl_thought.config(text=thought)
        if action is not None:
            self.lbl_action.config(text=f"▶ {action}" if action else "▶ 等待指令")

    def _apply_profiler_live(self, data: Dict[str, Any]):
        """更新性能监控窗口实时秒表与当前运行阶段"""
        if not self.win_perf:
            return

        if not self.win_perf.winfo_viewable():
            self.win_perf.deiconify()

        stage = data.get("stage", "IDLE")
        desc = data.get("desc", stage)
        start = data.get("stage_start", 0.0)
        self.live_stage_key = stage
        self.live_stage_start = start if start > 0 else time.perf_counter()
        self.live_stage_active = True

        badges = {
            "game_sync": ("🟡 游戏等待", "#ffc83b"),
            "compress": ("🟢 状态压缩", "#2ed573"),
            "llm_call": ("🔵 LLM 推理", "#00f0ff"),
            "action_exec": ("🟣 动作执行", "#9b59b6"),
            "IDLE": ("● READY", "#2ed573"),
        }
        b_text, b_color = badges.get(stage, ("● " + stage.upper(), "#00f0ff"))
        if "宏观" in desc or "macro" in desc.lower():
            b_text, b_color = ("🟣 宏观决策", "#a55eea")
        elif "战后复盘" in desc or "combat_reflection" in stage:
            b_text, b_color = ("📝 战后复盘", "#3742fa")
        elif stage == "llm_call":
            b_text, b_color = ("🔵 战斗推理", "#00f0ff")

        self.lbl_perf_badge.config(text=b_text, fg=b_color)
        self.lbl_live_stage.config(text=f"当前阶段: {desc}")
        self.lbl_perf_alarm.config(text="延迟状态: 正常 (Normal)", fg="#2ed573")

    def _apply_profiler(self, data: Dict[str, Any]):
        """更新性能监控窗口上一轮各阶段耗时统计"""
        if not self.win_perf:
            return

        if not self.win_perf.winfo_viewable():
            self.win_perf.deiconify()

        self.live_stage_active = False
        summary = data.get("summary", {})
        total = summary.get("total_time", 0.0)
        timings = summary.get("timings", {})
        pcts = summary.get("percentages", {})
        bot_desc = summary.get("bottleneck_desc", "--")
        metrics = summary.get("metrics", {})
        retries = metrics.get("retries", 0)

        def bar(p):
            f = max(0, min(10, int(round(p / 10.0))))
            return "█" * f + "▒" * (10 - f)

        t_game = timings.get("game_sync", 0.0)
        p_game = pcts.get("game_sync", 0.0)
        self.lbl_bar_game.config(text=f"  - 游戏同步 (Game I/O):  {t_game:.2f}s  [{bar(p_game)}]  {p_game:4.1f}%")

        t_comp = timings.get("compress", 0.0)
        p_comp = pcts.get("compress", 0.0)
        self.lbl_bar_comp.config(text=f"  - 状态压缩 (Compress):  {t_comp:.2f}s  [{bar(p_comp)}]  {p_comp:4.1f}%")

        t_llm = timings.get("llm_call", 0.0)
        p_llm = pcts.get("llm_call", 0.0)
        self.lbl_bar_llm.config(text=f"  - 模型推理 (LLM Call):  {t_llm:.2f}s  [{bar(p_llm)}]  {p_llm:4.1f}%")

        t_act = timings.get("action_exec", 0.0)
        p_act = pcts.get("action_exec", 0.0)
        self.lbl_bar_act.config(text=f"  - 动作执行 (Action):    {t_act:.2f}s  [{bar(p_act)}]  {p_act:4.1f}%")

        self.lbl_perf_summary.config(text=f"回合总耗时: {total:.2f}s | 最大瓶颈: {bot_desc}")
        self.lbl_perf_badge.config(text="● READY", fg="#2ed573")

        if retries > 0:
            self.lbl_perf_alarm.config(text=f"⚠️ 提示: 本轮发生了 {retries} 次模型格式重试", fg="#ff4757")
        elif total > 8.0:
            self.lbl_perf_alarm.config(text=f"⚠️ 提示: 回合耗时较长 ({total:.2f}s)", fg="#ffc83b")
        else:
            self.lbl_perf_alarm.config(text="延迟状态: 优良 (Smooth)", fg="#2ed573")

    def update_blackboard(
        self,
        archetype: str = "",
        win_con: str = "",
        play_guide: str = "",
        drafting_focus: str = "",
        postmortem: Optional[Dict[str, Any]] = None,
    ):
        """向小黑板推送宏观战略与战后复盘数据"""
        self.msg_queue.put(
            {
                "type": "blackboard",
                "archetype": archetype,
                "win_con": win_con,
                "play_guide": play_guide,
                "drafting_focus": drafting_focus,
                "postmortem": postmortem,
            }
        )

    def update_thinking(
        self,
        thought: str,
        action: str = "",
        status: str = "",
        badge: str = "● 思考中",
        badge_color: str = "#00f0ff",
    ):
        """向思考窗口推送当前回合与决策逻辑"""
        self.msg_queue.put(
            {
                "type": "thinking",
                "thought": thought,
                "action": action,
                "status": status,
                "badge": (badge, badge_color),
            }
        )

    def update_profiler(self, summary: Dict[str, Any]):
        """向性能监控窗口推送耗时汇总"""
        self.msg_queue.put({"type": "profiler", "summary": summary})

    def update_profiler_live(self, stage: str, desc: str = "", stage_start: float = 0.0):
        """向性能监控窗口推送实时运行状态与秒表"""
        self.msg_queue.put({"type": "profiler_live", "stage": stage, "desc": desc, "stage_start": stage_start})

    def say(
        self,
        thought: str,
        action: str = "",
        status: str = "",
        badge: str = "🧠 AI",
        badge_color: str = "#2ed573",
    ):
        """向后兼容原有接口"""
        self.update_thinking(thought, action, status, badge, badge_color)

    def close(self):
        """安全关闭 HUD 窗口"""
        if self.root:
            try:
                self.root.quit()
            except Exception:
                pass

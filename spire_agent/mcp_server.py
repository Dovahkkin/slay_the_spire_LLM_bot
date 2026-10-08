"""
Slay the Spire MCP Server
将《杀戮尖塔》游戏状态感知、战斗出牌、宏观决策与伤害试算器包装为标准的 MCP Tools。
支持 Antigravity、Claude Code、Cursor、Claude Desktop 等任意兼容 MCP 的客户端。
"""

from __future__ import annotations
import logging
import os
import sys

# 强制将标准输入输出重定向为 UTF-8，彻底解决 Windows 平台的 GBK 编码与乱码问题
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

from typing import Optional, List, Dict, Any
from fastmcp import FastMCP

from .models import (
    PlayCardAction,
    EndTurnAction,
    UsePotionAction,
    ChooseAction,
    ProceedAction,
    CancelAction,
    ConfirmAction,
    FullGameState,
    CombatState,
)
from .driver import BaseGameDriver, MockGameDriver, SocketGameDriver
from .compressor import StateCompressor
from .tools.calculator import DamageCalculatorTool

# 日志输出至 stderr，确保 stdout 仅用于纯净的 MCP JSON-RPC 通信
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("spire_agent.mcp")

mcp = FastMCP(
    name="slay-the-spire",
    instructions=(
        "Model Context Protocol (MCP) server for Slay the Spire. "
        "Allows inspecting combat & macro game state, playing cards, evaluating damage and lethals, "
        "navigating map nodes, and choosing card rewards or shops."
    ),
)

# 全局单例
_driver: Optional[BaseGameDriver] = None
_calculator = DamageCalculatorTool()


def get_driver() -> BaseGameDriver:
    """获取或初始化游戏驱动：优先尝试连接本地 Socket，若未开启游戏则无缝回退至 Mock 沙盒驱动"""
    global _driver
    if os.environ.get("SPIRE_DRIVER") == "mock":
        if not isinstance(_driver, MockGameDriver):
            _driver = MockGameDriver(scenario="cultist")
        return _driver

    port = int(os.environ.get("SPIRE_SOCKET_PORT", 18888))
    host = os.environ.get("SPIRE_SOCKET_HOST", "127.0.0.1")

    # 若尚未初始化、或者原有 Socket 已断开，优先探测真实游戏连接
    if _driver is None or (isinstance(_driver, SocketGameDriver) and not _driver.is_connected()):
        sock_driver = SocketGameDriver(host=host, port=port, timeout=3.0)
        if sock_driver.is_connected():
            logger.info(f"成功连接至运行中的《杀戮尖塔》Socket 继电器: {host}:{port}")
            _driver = sock_driver
            return _driver

    if _driver is None:
        logger.info("未检测到运行中的游戏连接，自动启用 MockGameDriver 本地沙盒模式。")
        _driver = MockGameDriver(scenario="cultist")
    return _driver


def format_state_for_agent(state: Optional[FullGameState]) -> str:
    """将全局状态转化为紧凑、结构化、高语义密度的提示文本 (Windows GBK 兼容)"""
    if state is None:
        return "[WARN] 当前无可用游戏状态 (或游戏已结束/已退出)。"

    lines: List[str] = []
    driver = get_driver()
    is_mock = isinstance(driver, MockGameDriver)
    driver_name = f"Mock 沙盒模式 ({getattr(driver, 'scenario', 'cultist')})" if is_mock else "真实 Steam 游戏 (CommunicationMod)"
    lines.append(f"[DRIVER: {driver_name}]\n")

    if state.in_combat and state.combat_state:
        cs = state.combat_state
        # 1. 战局总览
        lines.append(StateCompressor.compress_combat(cs))

        # 2. 手牌明细（附带出牌所需的 card_index）
        lines.append("\n[HAND CARDS] (打牌请使用对应的 Index):")
        for c in cs.hand:
            cost_str = f"{c.cost}E" if c.cost >= 0 else "XE"
            target_str = " [单体目标需指定 target_enemy_index]" if c.target_type == "ENEMY" else ""
            desc = StateCompressor.clean_card_description(c)
            lines.append(f"  * [Index {c.index}] {c.name} ({cost_str}, {c.type}){target_str} -> {desc}")

        # 3. 怪物明细（附带目标 target_enemy_index）
        lines.append("\n[ALIVE ENEMIES]:")
        for m in cs.alive_monsters:
            p_str = ", ".join([f"{p.name}:{p.amount}" for p in m.powers if p.amount != 0])
            powers_disp = f" | 状态: [{p_str}]" if p_str else ""
            lines.append(f"  * [E{m.index}] {m.name} -> HP: {m.current_hp}/{m.max_hp}, 格挡: {m.block}, 意图: {m.intent_description}{powers_disp}")

        lines.append("\n[HINT] 可调用 `play_card(card_index, target_enemy_index)` 出牌，或 `end_turn()` 结束回合。请自行结合力量、易伤与护甲进行伤害心算与斩杀判断。")
    else:
        # 非战斗界面
        lines.append(f"[SCREEN: {state.screen_type}] (第 {state.act} 幕 | 第 {state.floor} 层)")
        lines.append(f"玩家状态: HP {state.current_hp}/{state.max_hp} | 金币 {state.gold}G | 遗物数 {len(state.relics)} | 卡组厚度 {len(state.deck)} 张")

        # 战利品结算
        if state.screen_type == "COMBAT_REWARD":
            rewards = state.screen_state.get("rewards", [])
            lines.append("\n[REWARDS AVAILABLE]:")
            for idx, r in enumerate(rewards):
                lines.append(f"  * [Choice {idx}] {r.get('reward_type')} ({r})")
            lines.append("\n[HINT] 调用 `choose_option(index)` 领取物品，全部领完后调用 `proceed()` 推进到地图。")

        # 卡牌三选一
        elif state.screen_type == "CARD_REWARD":
            offered = state.screen_state.get("cards", [])
            lines.append("\n[OFFERED CARDS]:")
            for idx, c in enumerate(offered):
                name = c.get("name", c.get("id", "Unknown"))
                cost = c.get("cost", 1)
                desc = c.get("raw_description", "")
                lines.append(f"  * [Choice {idx}] {name} ({cost}费) -> {desc}")
            if state.screen_state.get("skip_available", True):
                lines.append("  * [Skip] 可调用 `cancel_or_skip()` 跳过选牌 (保持卡组精简)。")
            lines.append("\n[HINT] 调用 `choose_option(index)` 选牌，或 `cancel_or_skip()` 跳过。")

        # 手牌选择/升级
        elif state.screen_type == "HAND_SELECT":
            cards = state.screen_state.get("hand", [])
            lines.append("\n[HAND SELECT]:")
            for idx, c in enumerate(cards):
                lines.append(f"  * [Choice {idx}] {c.get('name')} -> {c.get('raw_description')}")
            lines.append("\n[HINT] 调用 `choose_option(index)` 确认选择。")

        # 大地图路线
        elif state.screen_type == "MAP":
            lines.append("\n[MAP NAVIGATION]:")
            lines.append(f"可用命令: {state.available_commands}")
            lines.append("\n[HINT] 调用 `choose_option(index)` 选择下一步前进路线节点。")

        elif state.screen_type == "EVENT":
            ev_name = state.screen_state.get("event_name", state.screen_state.get("event_id", "Event"))
            body = state.screen_state.get("body_text", "")
            lines.append(f"\n[EVENT: {ev_name}]")
            if body:
                lines.append(f"描述: {body}")
            options = state.screen_state.get("options", [])
            lines.append("\n[EVENT OPTIONS]:")
            for idx, opt in enumerate(options):
                disabled_str = " (不可选)" if opt.get("disabled", False) else ""
                lines.append(f"  * [Choice {idx}] {opt.get('text', '')}{disabled_str}")
            lines.append("\n[HINT] 调用 `choose_option(index)` 做出事件抉择。")

        elif state.screen_type == "REST":
            rest_opts = state.screen_state.get("rest_options", state.choice_list or [])
            lines.append("\n[CAMPFIRE REST SITE]:")
            for idx, opt in enumerate(rest_opts):
                lines.append(f"  * [Choice {idx}] {opt}")
            lines.append("\n[HINT] 调用 `choose_option(index)` 做出营地选择（例如 0: rest 休息回血，1: smith 锻造升级卡牌）。")

        elif state.screen_type == "GRID":
            cards = state.screen_state.get("cards", [])
            lines.append("\n[CARD GRID SELECTION]:")
            for idx, c in enumerate(cards):
                name = c.get("name", c.get("id", "Unknown"))
                upgrades = c.get("upgrades", 0)
                upg_str = f"+{upgrades}" if upgrades > 0 else ""
                lines.append(f"  * [Choice {idx}] {name}{upg_str}")
            lines.append("\n[HINT] 调用 `choose_option(index)` 选择要升级或操作的卡牌。")

        elif state.screen_type in ["SHOP_SCREEN", "SHOP"]:
            lines.append("\n[MERCHANT SHOP]:")
            purge_avail = state.screen_state.get("purge_available", False)
            purge_cost = state.screen_state.get("purge_cost", 75)
            if purge_avail:
                lines.append(f"  * [Choice 0: purge] 删除卡牌服务可用 (费用: {purge_cost}G)")
            cards = state.screen_state.get("cards", [])
            lines.append("出售卡牌:")
            for idx, c in enumerate(cards):
                lines.append(f"  * [{c.get('name')}] ({c.get('price')}G)")
            relics = state.screen_state.get("relics", [])
            lines.append("出售遗物:")
            for r in relics:
                lines.append(f"  * [{r.get('name')}] ({r.get('price')}G)")
            potions = state.screen_state.get("potions", [])
            lines.append("出售药水:")
            for p in potions:
                lines.append(f"  * [{p.get('name')}] ({p.get('price')}G)")
            lines.append("\n[HINT] 调用 `choose_option(index)` 购买物品或使用删牌服务。")

        else:
            lines.append(f"界面详情: {state.screen_state}")
            lines.append(f"可用动作: {state.available_commands}")

    return "\n".join(lines)


@mcp.tool()
def get_game_state() -> str:
    """
    【感知当前局势】获取最新的《杀戮尖塔》游戏状态概览。
    无论处于战斗中（手牌、能量、怪物意图、伤害威胁度）还是非战斗界面（地图、选牌、战利品结算），
    都会返回经过清洗与结构化的高密度局势分析。
    """
    driver = get_driver()
    if isinstance(driver, SocketGameDriver):
        state = driver.get_full_state(request_state=True)
    else:
        state = driver.get_full_state()
    return format_state_for_agent(state)


@mcp.tool()
def play_card(card_index: int, target_enemy_index: Optional[int] = None) -> str:
    """
    【出牌】在战斗中打出指定手牌。
    
    参数:
    - card_index: 手牌索引 (从 0 开始，参考 get_game_state 中标明的 [Index N])
    - target_enemy_index: 目标敌人索引 (例如 0, 1。若为单体攻击牌且场上只有一个敌人，可留空自动对准)
    """
    driver = get_driver()
    state = driver.get_full_state()
    if not state or not state.in_combat or not state.combat_state:
        return "[ERROR] 当前不在战斗中，无法打出手牌！"

    cs = state.combat_state
    hand_card = next((c for c in cs.hand if c.index == card_index), None)
    if not hand_card:
        available_indices = [c.index for c in cs.hand]
        return f"[ERROR] 手牌中不存在 index={card_index} 的卡牌！当前可用手牌索引: {available_indices}"

    if hand_card.cost > cs.player.energy:
        return f"[ERROR] 能量不足！卡牌 [{hand_card.name}] 需要 {hand_card.cost} 能量，当前只有 {cs.player.energy} 能量。"

    # 处理目标对准逻辑
    if hand_card.target_type == "ENEMY" and target_enemy_index is None:
        if len(cs.alive_monsters) == 1:
            target_enemy_index = cs.alive_monsters[0].index
        elif len(cs.alive_monsters) > 1:
            m_list = [f"E{m.index} ({m.name})" for m in cs.alive_monsters]
            return f"[ERROR] 卡牌 [{hand_card.name}] 需要指定目标敌人，但场上有多个存活怪: {m_list}。请填入 target_enemy_index！"

    action = PlayCardAction.create(
        card_index=card_index,
        target_index=target_enemy_index,
        card_name=hand_card.name,
        card_id=hand_card.id,
    )
    new_state = driver.send_full_action(action)
    target_info = f" -> 目标 E{target_enemy_index}" if target_enemy_index is not None else ""
    return f"[SUCCESS] 成功打出卡牌 [{hand_card.name}]{target_info}！\n\n{format_state_for_agent(new_state)}"


@mcp.tool()
def end_turn() -> str:
    """
    【结束回合】结束当前玩家出牌阶段。
    敌人将执行其意图动作（造成攻击伤害、施加 Buff/Debuff），结算完成后自动进入下一回合（重置能量并抽牌）。
    """
    driver = get_driver()
    state = driver.get_full_state()
    if not state or not state.in_combat:
        return "[ERROR] 当前不在战斗中，无需结束回合！"

    action = EndTurnAction.create()
    new_state = driver.send_full_action(action)
    return f"[SUCCESS] 已结束回合！敌人行动结算完毕。\n\n{format_state_for_agent(new_state)}"


# @mcp.tool()  # [已根据用户要求屏蔽] 暂时不暴露给大模型，测试大模型自主心算与逻辑推演能力
def calculate_damage(card_indices: List[int], target_enemy_index: int = 0) -> str:
    """
    【精准伤害推演计算器 (0 幻觉验算)】
    在真正打出卡牌之前，试算打出一串手牌的真实伤害、格挡获得量、剩余能量以及是否能够达成斩杀（击杀目标）。
    自动且精确地计算力量、敏捷、易伤 (1.5x)、虚弱 (0.75x) 与怪物护甲抵扣。
    
    参数:
    - card_indices: 准备按顺序打出的手牌索引列表，例如 [0, 1]
    - target_enemy_index: 单体攻击牌的目标敌人索引 (默认 E0)
    """
    driver = get_driver()
    state = driver.get_full_state()
    if not state or not state.in_combat or not state.combat_state:
        return "[ERROR] 当前不在战斗中，无法进行伤害推演！"

    cs = state.combat_state
    result = _calculator.execute({"card_indices": card_indices, "target_enemy_index": target_enemy_index}, context=cs)
    if not result.success:
        return f"[ERROR] 试算失败: {result.error}"

    data = result.data
    energy_needed = data.get("energy_needed", 0)
    energy_avail = data.get("energy_available", 0)
    total_dmg = data.get("total_damage", 0)
    total_blk = data.get("total_block_gained", 0)
    res_blk = data.get("resulting_player_block", 0)
    target_hp = data.get("target_final_hp", 0)
    is_lethal = data.get("target_killed", False)
    valid_energy = data.get("valid_energy", True)

    lines = [
        "== 精准伤害推演核算结果 ==",
        f"* 消耗能量: {energy_needed} (当前拥有: {energy_avail}, 是否合法: {'[OK]' if valid_energy else '[WARN 费用超支]'})",
        f"* 产生总伤害: {total_dmg}",
        f"* 获得格挡: {total_blk} (回合末玩家最终护甲: {res_blk})",
        f"* 目标敌人最终生命: {target_hp}",
        f"* 是否达成斩杀: {'[YES] 确认达成斩杀 (LETHAL SUCCESSFUL)!' if is_lethal else '[NO] 未能直接斩杀'}",
    ]

    steps = data.get("steps", [])
    if steps:
        lines.append("\n[推演出牌明细]:")
        for idx, s in enumerate(steps):
            lines.append(
                f"  {idx+1}. 打出 [{s.get('card')}]: 造成 {s.get('damage_dealt')} 伤 | 获得 {s.get('block_gained')} 甲 | 目标剩余 HP: {s.get('target_remaining_hp')}"
            )

    return "\n".join(lines)


@mcp.tool()
def choose_option(choice_index: int) -> str:
    """
    【非战斗选择】在选牌、战利品、手牌升级、大地图路线或事件中进行选择。
    
    参数:
    - choice_index: 选项索引 (从 0 开始，参考 get_game_state 中的 [Choice N])
    """
    driver = get_driver()
    state = driver.get_full_state()
    if state and state.in_combat:
        return "[ERROR] 当前处于战斗中，请使用 play_card 或 end_turn！"

    choice_val: Any = choice_index
    if state and state.choice_list and 0 <= choice_index < len(state.choice_list):
        choice_val = state.choice_list[choice_index]

    action = ChooseAction.create(choice=choice_val)
    new_state = driver.send_full_action(action)
    return f"[SUCCESS] 已做出选择 #{choice_index} ({choice_val})！\n\n{format_state_for_agent(new_state)}"


@mcp.tool()
def proceed() -> str:
    """
    【推进】点击 Proceed 确认推进流程（例如：领取全部战利品后点击前往大地图）。
    """
    driver = get_driver()
    action = ProceedAction.create()
    new_state = driver.send_full_action(action)
    return f"[SUCCESS] 已点击 Proceed 继续推进！\n\n{format_state_for_agent(new_state)}"


@mcp.tool()
def cancel_or_skip() -> str:
    """
    【跳过 / 取消】跳过当前选择（例如：跳过卡牌奖励 Skip Card Reward，以维持精简卡组）。
    """
    driver = get_driver()
    action = CancelAction.create()
    new_state = driver.send_full_action(action)
    return f"[SUCCESS] 已跳过当前选择！\n\n{format_state_for_agent(new_state)}"


@mcp.tool()
def confirm() -> str:
    """
    【确认】在需要二级确认的界面（例如：锻造升级卡牌、卡牌网格选择确认）点击 Confirm。
    """
    driver = get_driver()
    action = ConfirmAction.create()
    new_state = driver.send_full_action(action)
    return f"[SUCCESS] 已点击 Confirm 确认！\n\n{format_state_for_agent(new_state)}"


@mcp.tool()
def reset_scenario(scenario: str = "cultist") -> str:
    """
    【重置测试沙盒场景】在 Mock 沙盒与真实游戏之间快速切换，便于直接在当前对话中随时测试。
    
    可用参数:
    - "cultist": 邪教徒满血对局 (初始 48 HP 邪教徒蓄力准备打 6 点，测试起手防守与过牌)
    - "lethal": 残血斩杀场景 (15 HP 地精，手牌有打击与痛击，测试斩杀逻辑)
    - "reward": 战斗胜利后的战利品结算界面 (测试金币与卡牌奖励领取)
    - "card_reward": 卡牌三选一界面 (屠戮、铁甲波、无惧疼痛，测试选牌或跳过)
    - "live": 重新尝试连接本地 Steam 正在运行的《杀戮尖塔》真实游戏 (通过 18888 端口)
    """
    global _driver
    if scenario == "live":
        port = int(os.environ.get("SPIRE_SOCKET_PORT", 18888))
        host = os.environ.get("SPIRE_SOCKET_HOST", "127.0.0.1")
        sock_driver = SocketGameDriver(host=host, port=port, timeout=1.0)
        if sock_driver.is_connected():
            _driver = sock_driver
            return f"[SUCCESS] 成功连接至真实 Steam 游戏 (Port {port})！\n\n{format_state_for_agent(_driver.get_full_state())}"
        else:
            return f"[ERROR] 连接失败: 端口 {port} 上未检测到运行中的《杀戮尖塔》Socket 继电器服务。"

    if isinstance(_driver, SocketGameDriver):
        try:
            _driver.close()
        except Exception:
            pass
    mock = MockGameDriver(scenario=scenario)
    if scenario == "card_reward":
        mock.phase = "card_reward"
    elif scenario == "reward":
        mock.phase = "reward"
    elif scenario == "map":
        mock.phase = "map"
    _driver = mock
    return f"[SUCCESS] 已成功切换至 Mock 沙盒场景 [{scenario}]！\n\n{format_state_for_agent(_driver.get_full_state())}"


@mcp.tool()
def solver_health() -> str:
    """
    【健康状态检查】检查 Slay the Spire MCP 系统的组件状态、驱动类型与连通性。
    """
    driver = get_driver()
    driver_type = "MockGameDriver (本地离线沙盒)" if isinstance(driver, MockGameDriver) else "SocketGameDriver (真实 Steam 游戏)"
    connected = True if isinstance(driver, MockGameDriver) else driver.is_connected()
    return (
        f"[ONLINE] Slay the Spire MCP 服务运行正常\n"
        f"* 驱动模式: {driver_type}\n"
        f"* 通信状态: {'已就绪 (Connected)' if connected else '未连接'}\n"
        f"* FastMCP 框架: 正常就绪\n"
        f"* 伤害推演计算器: 正常加载\n"
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()

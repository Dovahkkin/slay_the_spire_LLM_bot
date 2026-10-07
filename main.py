import sys
import os
import argparse
import logging
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent
load_dotenv(project_root / ".env")

# 严禁污染 sys.stdout 管道，所有日志同时输出到 sys.stderr 与 bot_debug.log 文件
log_path = project_root / "bot_debug.log"


class FlushingFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

file_handler = FlushingFileHandler(str(log_path), mode="a", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[console_handler, file_handler],
)
logger = logging.getLogger("main")

from spire_agent import (
    SpireAgent,
    MockGameDriver,
    CommunicationModDriver,
    PlayCardAction,
    EndTurnAction,
    UsePotionAction,
    SpireHud,
    DummyHud,
)


def run_game_loop(agent: SpireAgent, driver, max_steps: Optional[int] = None):
    """
    全生命周期主循环：
    - 战斗状态下：规划整回合连击序列 (TurnPlan)，并具备【过牌/衍生卡中断重新推演】特性；
    - 非战斗状态下：统一派发宏观决策（抓牌、走图、营地、商店）；
    - 战斗胜利结算时：自动触发 combat_session.reset() 清空临时上下文。
    """
    step = 1
    full_state = driver.get_full_state()
    was_in_combat = False

    while full_state is not None and not driver.is_game_over():
        if max_steps is not None and step > max_steps:
            logger.info("达到指定的单次测试步数限制，主循环终止。")
            break

        print("\n" + "=" * 60, file=sys.stderr)

        # 1. 战斗内二次选卡阶段（如武装升级、战吼放回牌顶、头槌捞牌、真拟等）
        if full_state.in_combat and full_state.screen_type in ["HAND_SELECT", "GRID"]:
            was_in_combat = True
            turn_num = full_state.combat_state.turn if full_state.combat_state else "?"
            logger.info(f"--- [战斗回合 {turn_num} | 战斗选卡: {full_state.screen_type} | Micro-step #{step}] ---")
            action = agent.decide_screen_action(full_state)
            logger.info(f"--> [Agent 战斗选卡指令]: {action.raw_command} ({action.action_type})")
            if agent.profiler:
                agent.profiler.start_stage("action_exec", f"执行战斗选卡指令: {action.raw_command}")
            full_state = driver.send_full_action(action)
            if agent.profiler:
                agent.profiler.finish_turn(
                    floor=full_state.floor if full_state else 0,
                    turn=turn_num if isinstance(turn_num, int) else 0,
                    room_type=f"COMBAT_{full_state.screen_type if full_state else 'SELECT'}",
                )
            step += 1

        # 2. 战斗常规出牌阶段
        elif full_state.in_combat and full_state.combat_state is not None:
            was_in_combat = True
            combat_state = full_state.combat_state
            logger.info(f"--- [战斗回合 {combat_state.turn} | Micro-step #{step}] ---")

            # 呼叫 Agent 制定本回合连击方案
            plan = agent.plan_combat_turn(combat_state)
            logger.info(f"--> [Agent 制定连击方案]: 包含 {len(plan.actions)} 个连招动作")

            # 依次执行连击方案中的动作
            if agent.profiler:
                agent.profiler.start_stage("action_exec", f"执行连招 ({len(plan.actions)} 个动作)...")

            for act_idx, action in enumerate(plan.actions):
                if isinstance(action, PlayCardAction):
                    if not combat_state or not combat_state.hand:
                        logger.info("  [手牌为空] 结束本回合连招。")
                        break

                    # 动态匹配当前手牌中要打出的卡牌（完美解决前序出牌导致的手牌索引位移问题）
                    matched_card = None
                    for c in combat_state.hand:
                        if action.card_id and c.id == action.card_id:
                            matched_card = c
                            break
                        elif action.card_name and c.name.lower() == action.card_name.lower():
                            matched_card = c
                            break

                    if not matched_card and 0 <= action.card_index < len(combat_state.hand):
                        matched_card = combat_state.hand[action.card_index]

                    if not matched_card:
                        logger.warning(f"  [连招跳过] 当前手牌已找不到预定卡牌 [{action.card_name or action.card_index}]，跳过。")
                        continue

                    # 检查能量是否足够
                    if combat_state.player.energy < matched_card.cost:
                        logger.info(f"  [连招终止] 剩余能量 ({combat_state.player.energy}) 不足支付 [{matched_card.name}] ({matched_card.cost} 费)，结束本回合。")
                        full_state = driver.send_full_action(EndTurnAction.create())
                        step += 1
                        break

                    # 校验并自愈目标：单体攻击卡确保有存活目标，若原目标阵亡自动切到存活怪
                    alive_indices = {m.index for m in combat_state.alive_monsters}
                    real_target = action.target_index
                    is_attack = matched_card.type == "ATTACK" and matched_card.target_type != "ALL_ENEMY"
                    needs_target = matched_card.has_target or matched_card.target_type == "ENEMY" or is_attack

                    if needs_target:
                        if real_target is None or real_target not in alive_indices:
                            real_target = combat_state.alive_monsters[0].index if combat_state.alive_monsters else 0
                    else:
                        real_target = None

                    # 根据当前手牌中的实际槽位动态构建指令 (CommunicationMod 使用 1-indexed 槽位)
                    current_slot = matched_card.index + 1
                    real_cmd = f"PLAY {current_slot}" if real_target is None else f"PLAY {current_slot} {real_target}"
                    action = PlayCardAction(
                        raw_command=real_cmd,
                        card_index=matched_card.index,
                        target_index=real_target,
                        card_name=matched_card.name,
                        card_id=matched_card.id,
                    )
                    played_card = matched_card
                    agent.last_played_card = matched_card
                else:
                    played_card = None
                    agent.last_played_card = None

                prev_hand_len = len(combat_state.hand) if combat_state else 0
                logger.info(f"  [执行连招 #{act_idx + 1}]: {action.raw_command}")
                full_state = driver.send_full_action(action)
                step += 1

                from spire_agent.combat_tracer import CombatTracer
                CombatTracer.get_instance().log_action_execution(
                    act_idx=act_idx + 1,
                    cmd=action.raw_command,
                    result_summary=f"Screen={full_state.screen_type if full_state else 'None'}, HP={full_state.current_hp if full_state else '?'}/{full_state.max_hp if full_state else '?'}, InCombat={full_state.in_combat if full_state else False}"
                )

                # 检查是否触发战斗内选卡界面（如战吼、头槌、武装、真拟等）
                if full_state and full_state.screen_type in ["HAND_SELECT", "GRID"]:
                    logger.info(f"✦ [战斗内二次选卡触发] 检测到界面 [{full_state.screen_type}]，中断当前连招，交由大模型选择卡牌！")
                    break

                # 检查战斗是否在连招途中已胜利结束（避免选卡弹窗被误认为战斗胜利）
                is_won = False
                if not full_state:
                    break
                if full_state.screen_type == "COMBAT_REWARD":
                    is_won = True
                elif full_state.combat_state and not full_state.combat_state.alive_monsters:
                    is_won = True
                elif not full_state.in_combat and full_state.screen_type not in ["HAND_SELECT", "GRID"]:
                    is_won = True

                if is_won:
                    logger.info("战斗已胜利结束，中断剩余连击并重置战斗会话。")
                    agent.on_combat_end(full_state)
                    was_in_combat = False
                    break

                combat_state = full_state.combat_state

                # 【核心机制：过牌/产卡动态中断重规划】
                # 如果刚才打出的卡牌属于抽牌或产卡类（如战斗专注、祭品、战吼、剑柄打击），
                # 或者打出的药水扩展了手牌（如抽牌药水、赌徒药酿），
                # 手牌池已扩充，必须中断后续出牌，重新唤醒大模型推演新局面！
                has_drawn = (
                    (played_card and played_card.is_card_draw_or_generator)
                    or (isinstance(action, UsePotionAction) and combat_state and len(combat_state.hand) > prev_hand_len)
                )
                if has_drawn:
                    act_name = played_card.name if played_card else action.raw_command
                    logger.info(f"✦ [过牌中断触发] 动作 [{act_name}] 扩展了手牌！中断剩余预设连招，交由大模型重新推演新局面！")
                    break

                if isinstance(action, EndTurnAction):
                    break

            if agent.profiler:
                agent.profiler.finish_turn(
                    floor=full_state.floor if full_state else 0,
                    turn=combat_state.turn if combat_state else 0,
                    room_type="COMBAT",
                )

        # 3. 非战斗阶段（战利品结算、选牌、地图、营地、事件等）
        else:
            if was_in_combat:
                agent.on_combat_end(full_state)
                was_in_combat = False

            screen_name = full_state.screen_type if full_state.screen_type != "NONE" else "DUNGEON"
            logger.info(f"--- [宏观流程 Step #{step} | 界面: {screen_name}] ---")
            action = agent.decide_screen_action(full_state)
            logger.info(f"--> [Agent 宏观指令]: {action.raw_command} ({action.action_type})")
            if agent.profiler:
                agent.profiler.start_stage("action_exec", f"执行宏观指令: {action.action_type}")
            full_state = driver.send_full_action(action)
            if agent.profiler:
                agent.profiler.finish_turn(
                    floor=full_state.floor if full_state else 0,
                    turn=0,
                    room_type=screen_name,
                )
            step += 1

    if driver.is_game_over():
        logger.info("游戏阶段结束或与游戏通信断开。")


def main():
    parser = argparse.ArgumentParser(description="Slay the Spire LLM Agent (DeepSeek / Kimi / Gemini)")
    parser.add_argument(
        "--driver",
        choices=["mock", "live"],
        default="mock",
        help="运行模式: mock 为离线沙盒模拟，live 为连接真实 CommunicationMod 游戏进程",
    )
    parser.add_argument(
        "--scenario",
        choices=["cultist", "lethal", "danger", "gremlin_nob"],
        default="cultist",
        help="沙盒模拟场景: cultist (邪教徒), lethal (斩杀残血局), danger (高危生存局), gremlin_nob (地精大块头精英)",
    )
    parser.add_argument(
        "--provider",
        choices=["deepseek", "kimi", "gemini"],
        default=None,
        help="大模型提供商: deepseek | kimi | gemini (默认从 .env 读取 LLM_PROVIDER)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="模型名称 (例如 deepseek-chat, moonshot-v1-8k, gemini-2.0-flash)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="模型 API Key (若未指定则自动从 .env 对应提供商读取)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="模型 API Base URL",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="采样温度 temperature (针对 kimi-k / reasoner 等模型建议设为 1.0 或留空自动识别)",
    )
    parser.add_argument(
        "--hud",
        dest="hud",
        action="store_true",
        default=True,
        help="开启战术 HUD 悬浮日志提示 (默认开启)",
    )
    parser.add_argument(
        "--no-hud",
        dest="hud",
        action="store_false",
        help="关闭 HUD",
    )
    parser.add_argument(
        "--tools",
        dest="enable_tools",
        action="store_true",
        default=None,
        help="开启本地工具调用模式 (默认读取 .env 的 ENABLE_TOOLS，缺省为开启)",
    )
    parser.add_argument(
        "--no-tools",
        dest="enable_tools",
        action="store_false",
        help="关闭所有工具，开启大模型纯心算模式 (Pure CoT 单次生成，更快且省 Token)",
    )
    parser.add_argument(
        "--calculator",
        dest="enable_calculator",
        action="store_true",
        default=None,
        help="向大模型暴露伤害与格挡试算器 calculate_card_sequence (默认读取 .env 的 ENABLE_CALCULATOR)",
    )
    parser.add_argument(
        "--no-calculator",
        dest="enable_calculator",
        action="store_false",
        help="隐藏伤害试算器，让大模型自行心算伤害与格挡",
    )
    parser.add_argument(
        "--macro-provider",
        choices=["deepseek", "kimi", "gemini"],
        default=None,
        help="宏观战略模型提供商 (默认读取 MACRO_LLM_PROVIDER 或继承主模型)",
    )
    parser.add_argument(
        "--macro-model",
        default=None,
        help="宏观战略模型名称 (默认读取 MACRO_LLM_MODEL 或继承主模型)",
    )
    args = parser.parse_args()

    from config import LLMConfig
    enable_tools = LLMConfig.get_enable_tools(args.enable_tools)
    enable_calc = LLMConfig.get_enable_calculator(args.enable_calculator)

    mode_info = []
    if not enable_tools:
        mode_info.append("纯大模型心算模式 (完全禁用工具，单次生成)")
    elif not enable_calc:
        mode_info.append("自主心算伤害模式 (禁用伤害试算器，保留机制情报工具)")
    else:
        mode_info.append("完整工具辅助模式 (暴露伤害试算器与机制情报工具)")

    logger.info(f"战斗推演模式配置: {', '.join(mode_info)}")

    hud = SpireHud() if args.hud else DummyHud()

    agent = SpireAgent(
        provider=args.provider,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        temperature=args.temperature,
        macro_provider=args.macro_provider,
        macro_model=args.macro_model,
        enable_tools=enable_tools,
        enable_calculator=enable_calc,
        hud=hud,
    )

    if args.driver == "live":
        logger.info("启动真实游戏通信驱动 (CommunicationMod)...")
        driver = CommunicationModDriver()
    else:
        logger.info(f"启动本地沙盒模拟驱动 (场景: {args.scenario})...")
        driver = MockGameDriver(scenario=args.scenario)

    run_game_loop(agent, driver)


if __name__ == "__main__":
    main()

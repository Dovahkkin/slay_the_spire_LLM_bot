# Slay the Spire LLM Agent 🃏⚡

基于大语言模型（**Kimi / DeepSeek / Gemini**）与神经-符号双层规划架构的《杀戮尖塔》（Slay the Spire）全自动化自主对战 Agent。

包含**双独立置顶透明 HUD 悬浮窗**、**共享战术黑板**、**64+ 怪物完整行动禁忌情报库**与 **12 套铁甲战士主流流派架构体系**。

---

## 🌟 核心特色与系统架构

1. **双层规划会话隔离（Two-Level Context Architecture）**：
   - **`MacroSession`（宏观长线战略大脑）**：跨层保持长期记忆。负责战后选牌奖励（三选一与跳过）、商店删牌与消费、地图路线风险评估，动态推演并维护流派形态。
   - **`CombatSession`（微观回合战术先锋）**：**单场即弃，阅后即焚**。战斗开打时激活，制定整回合出牌连招；战斗胜利后**立刻清空所有出牌碎语**，生成战后反思写回黑板，彻底杜绝历史对话污染与 Token 爆炸！
2. **共享战略黑板模式（Shared Blackboard & Run Memo）**：
   - 宏观与微观 Agent 通过统一的 `RunBlackboard` 进行状态交互；
   - 宏观会话选牌后更新【流派定位、致胜终端、抓牌重心】；
   - 战术会话在打完每场战斗后自动复盘【战损掉血、耗时回合、短板教训】写回复盘记录；
   - 实时持久化为项目根目录的 [`run_memo.md`](run_memo.md)，随时可直观查看。
3. **双子桌面置顶透明悬浮窗（Dual In-Game HUD Overlays）**：
   - **小黑板悬浮窗**：实时展示当前流派认知、赢法、抓牌优先级与最新战后战损复盘；
   - **实时思考推演窗**：实时展示 Agent 在战斗或非战斗界面的 Chain-of-Thought 内心独白与即将执行的连招动作；
   - 采用标准库 `tkinter`，零第三方 GUI 依赖；置顶半透明，**两窗均支持鼠标自由拖拽摆放**。
4. **回合连击序列与过牌动态中断（Turn Combo & Draw Interruption）**：
   - 一次性规划整回合的出牌清单（如 `[Bash->E0, Strike->E0, EndTurn]`）；
   - 一旦打出抽牌或产卡牌（如战斗专注、祭品、战吼），执行器立刻暂停剩余动作，重新唤醒大模型推演新扩展的手牌。
5. **纯 Python 符号算力工具箱（Tool-Assisted Execution）**：
   - **精准伤害与格挡试算器 (`calculate_card_sequence`)**：精确叠加力量、敏捷、易伤、虚弱与护甲抵扣；
   - **怪物情报对策库 (`lookup_monster_tactics`)**：收录 64+ 怪物（第 1 至 4 幕所有 Boss、精英与小怪）特异机制与打法禁忌；
   - **战士主流流派定位库**：收录 12 大成熟构筑流派指导，支持 A20 进阶决策。
6. **双轨交互架构（全自动托管 vs 标准 MCP 伴打）**：
   - **全自动托管模式 (`main.py`)**：由神经-符号系统全权决策，全自动通关爬塔；
   - **交互伴打模式 (`spire_agent/mcp_server.py`)**：基于 FastMCP 协议，可无缝接入 **Google Antigravity、Cursor、Claude Code、Claude Desktop** 等现代 AI 环境，支持人类玩家在 IDE / 聊天界面中与 AI 协同打牌、分析局势与决策；
   - **零时差 Socket 继电器 (`spire_agent/relay.py`)**：将 CommunicationMod 桥接至本地 `127.0.0.1:18888` TCP 端口，内置非阻塞缓冲区极速排空（Drain）引擎，杜绝任何历史时差滞后。

---

## 💻 一台新电脑的完整从零配置指南

如果你在一部全新电脑上部署该项目，请按以下步骤依次配置：

### 第一步：基础软件安装
1. **安装 Steam 及原版游戏**：
   - 在 Steam 下载并安装正版《杀戮尖塔》（Slay the Spire）。
2. **安装 Python**：
   - 安装 Python 3.10+（推荐 Python 3.10 ~ 3.14，安装时务必勾选 **"Add python.exe to PATH"**）。

---

### 第二步：Steam 创意工坊 Mod 订阅
打开 Steam 社区的《杀戮尖塔》创意工坊，订阅以下 **3 个必需 Mod**：
1. **ModTheSpire**（所有 Mod 的基础启动与注入器）
2. **BaseMod**（底层扩展 API 支持库）
3. **CommunicationMod**（游戏内外进程间输入输出通信管道）

> 💡 **提示**：订阅后，先在 Steam 启动一次游戏并选择 **Play with Mods**，确认能在 Mod 列表中看到这 3 个 Mod。启动一次游戏后退出，系统会自动生成 Mod 的配置文件目录。

---

### 第三步：配置 CommunicationMod 桥梁（核心关键）

CommunicationMod 需要知道去哪里调用我们编写的 Python 智能体。

#### 1. 找到配置文件路径
在 Windows 资源管理器地址栏输入以下路径或按 `Win + R` 输入运行：
```text
%LOCALAPPDATA%\ModTheSpire\CommunicationMod
```
即对应实际物理路径：
```text
C:\Users\<你的Windows用户名>\AppData\Local\ModTheSpire\CommunicationMod\config.properties
```
*(如果该文件或文件夹不存在，请手动创建文件夹和 `config.properties` 纯文本文件)*

#### 2. 编辑 `config.properties`
用记事本打开 `config.properties`，根据你想运行的模式填入对应命令：

* **模式 A：全自动自主托管爬塔（AI 全自动推演与出牌）**：
  ```properties
  command=C\:\\Users\\<你的Windows用户名>\\Documents\\slay-the-spire-llm-agent\\run_bot.bat
  runAtGameStart=true
  ```
* **模式 B：MCP 伴打与交互模式（推荐接入 Google Antigravity、Cursor、Claude Code 等）**：
  ```properties
  command=C\:\\Users\\<你的Windows用户名>\\Documents\\slay-the-spire-llm-agent\\run_relay.bat
  runAtGameStart=true
  ```

> ⚠️ **极其重要的语法注意点（Java Properties 转义规则）**：
> 1. **反斜杠与冒号转义**：Properties 文件中，路径中的冒号 `:` 前面**必须加反斜杠**转义（即 `C\:`），且路径分隔符必须是**双反斜杠**（即 `\\`）。
>    - ❌ 错误示范：`command=C:\Users\test\project\run_bot.bat`
>    - ✅ 正确示范：`command=C\:\\Users\\test\\project\\run_bot.bat`
> 2. **`runAtGameStart=true`**：该项设置为 `true` 时，每次游戏开局进入地牢，CommunicationMod 会**自动唤醒所配置的脚本**，不需要你每次在后台手动敲命令行！

---

### 第四步：克隆项目与安装 Python 依赖

1. 打开 PowerShell 或 CMD，进入你的项目工作目录：
   ```bash
   cd C:\Users\<你的Windows用户名>\Documents
   git clone <你的项目仓库地址> slay-the-spire-llm-agent
   cd slay-the-spire-llm-agent
   ```

2. 安装依赖库：
   ```bash
   pip install -r requirements.txt
   ```
   *(主要依赖：`openai`, `pydantic`, `pyyaml`, `python-dotenv`)*

---

### 第五步：配置大模型 API Key (`.env`)

1. 在项目根目录复制一份环境变量模板：
   ```bash
   copy .env.example .env
   ```

2. 用文本编辑器打开 `.env`，根据你使用的模型填写配置：

#### 方案 A：使用 Kimi (Moonshot API) - 推荐
```ini
LLM_PROVIDER=kimi
KIMI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=kimi-k2.7-code
```

#### 方案 B：使用 DeepSeek
```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

#### 方案 C：使用 Google Gemini (官方兼容端点)
```ini
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIzaxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
GEMINI_MODEL=gemini-2.5-flash
```

> 💡 **进阶选项**：在 `.env` 中可配置是否开启工具辅助：
> - `ENABLE_TOOLS=true`：开启 ReAct 工具闭环（包含伤害试算与怪物机制查询）；
> - `ENABLE_CALCULATOR=true`：向模型暴露伤害试算器；若设为 `false` 则让模型自主心算伤害。

---

### 第六步：检查启动脚本 `run_bot.bat`
项目根目录下的 [`run_bot.bat`](run_bot.bat) 已经做了智能自适应：
- 优先检测项目内部的虚拟环境 `.venv\Scripts\python.exe`；
- 其次检测本地独立 Python 目录；
- 最后自动回退到系统环境变量的 `python`。

你可以直接双击运行一下 `run_bot.bat` 验证是否能成功加载依赖（测试无误后关掉即可）。

---

## 🎮 开始实机游玩！

1. 在 Steam 中点击运行《杀戮尖塔》，在弹出的启动选项中选择 **Play with Mods**（启动 ModTheSpire）。
2. 在 Mod 列表中勾选 **BaseMod** 和 **CommunicationMod**。
3. 点击底部的 **Play** 进入游戏主界面。
4. **游戏语言建议**：进入设置（Settings）将语言设为 **English（英文）**，这能保证卡牌 ID、怪物意图与系统底层协议完美匹配。
5. 点击 **Standard Run（标准模式）**，选择 **铁甲战士（Ironclad）** 开始游戏。
6. 进入地牢的瞬间：
   - 屏幕右上角会自动弹出 **📋 战术小黑板** 与 **🧠 实时思考推演** 两个透明置顶悬浮小窗；
   - AI 开始自动接管游戏，自主推演走图、打牌、选牌与消费！

---

## 🖥️ 双子置顶 HUD 悬浮窗说明

| 窗口名称 | 默认位置 | 展示内容 | 操作指南 |
| :--- | :--- | :--- | :--- |
| **📋 战术小黑板 (RUN MEMO)** | 屏幕右上角 | 宏观流派定位、核心致胜逻辑、抓牌重点、最新战后战损与反思 | 鼠标按住顶部标题栏可自由拖动；点击 `✕` 隐藏，有新战报时会自动唤出 |
| **🧠 实时推演与动作窗** | 屏幕右侧（黑板下方） | 状态徽章（连招/选牌/路线）、当前 HP/能量、大模型 CoT 思考推演过程、即将打出的指令 | 同样支持独立自由拖动；实时呈现大模型每一步的内心决策逻辑 |

---

## 🔌 Model Context Protocol (MCP) Server 接入与工具指南

除了让 AI 智能体在后台全自动通关爬塔（模式 A：Autopilot）外，本项目现已全面升级支持 **Model Context Protocol (MCP)** 标准！

你可以将《杀戮尖塔》作为一个具有丰富上下文感知与精准推演能力的 **MCP Server**，接入到 **Google Antigravity、Cursor、Claude Code、Claude Desktop** 等现代 AI 环境中，实现 **人类玩家操作 + AI 军师伴打推演**，或通过自然语言让 AI 执行打牌、商店选购与路线导航。

### 1. 架构工作流 (Architecture)

```text
+-----------------------+           Standard I/O          +-----------------------+
|  《杀戮尖塔》Steam 游戏  | <-----------------------------> |  CommunicationMod     |
+-----------------------+                                 +-----------------------+
                                                                      │
                                                             stdin / stdout pipe
                                                                      ▼
+-----------------------+        TCP Socket (18888)       +-----------------------+
|  FastMCP Server       | <-----------------------------> |  spire_agent/relay.py |
| (spire_agent/mcp_server)|                               |  (零时差广播与排空继电器)|
+-----------------------+                                 +-----------------------+
          │
      JSON-RPC (stdio)
          ▼
+---------------------------------------------------------+
|  AI 客户端 (Google Antigravity / Cursor / Claude Code)    |
+---------------------------------------------------------+
```

* **零时差 Socket 继电器 ([`spire_agent/relay.py`](spire_agent/relay.py))**：在后台建立 TCP 广播，彻底解耦游戏 I/O 阻塞。内置非阻塞缓冲区极速排空（Drain）引擎，杜绝任何历史时差滞后。
* **无缝回退与沙盒热插拔**：若未启动游戏或 Socket 离线，MCP 服务会自动挂载本地离线 Mock 沙盒，可随时在聊天窗口中无缝演练与单测！

---

### 2. 客户端配置接入方法 (Client Setup)

在你的 MCP 客户端配置文件中（例如 Cursor `mcp.json`、Antigravity `mcp_config.json` 或 Claude Desktop 对应配置），添加如下配置节：

```json
{
  "mcpServers": {
    "slay-the-spire": {
      "command": "python",
      "args": ["-m", "spire_agent.mcp_server"],
      "env": {
        "PYTHONPATH": ".",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```
> 💡 若使用虚拟环境，将 `"command"` 路径指定为 `.venv/Scripts/python.exe` 即可（参考根目录 [`mcp_config.example.json`](mcp_config.example.json)）。

---

### 3. MCP 工具矩阵 (Tools Reference)

本项目 MCP Server 对外暴露 8 个高语义工具，覆盖从战斗到大地图、商店、火堆休整的全流程：

| 工具名称 | 核心功能与参数说明 | 典型调用场景 |
| :--- | :--- | :--- |
| `get_game_state` | **获取当前全量局势**<br>输出高语义压缩战况：手牌/费用/意图/遗物/血量/商店列表/网格选项等 | 回合开始、开新楼层、进入事件或商店时了解战况 |
| `calculate_damage` | **精确伤害与斩杀推演**<br>参数: `card_indices: list[int]`, `target_index: int = 0`<br>严格计算力量、敏捷、易伤、虚弱及护甲 | 决策出牌顺序前心算连招伤害，判断能否直接秒杀怪物 |
| `play_card` | **执行打牌动作**<br>参数: `card_index: int` (手牌索引 0-based), `target_index: int = 0` | 打出打击、痛击、旋风斩、防御等卡牌 |
| `end_turn` | **结束当前战斗回合**<br>向游戏底层下达 `end` 指令并等待怪物回合结算 | 当前费用耗尽或无需继续出牌时交替回合 |
| `choose_option` | **做出选择与交互**<br>参数: `index: int`, `name: str = ""` (可选名字做二次校核)<br>支持地图选点、战利品认领、商店购物、火堆锻造、事件分支 | “买下狂暴”、“前往精英怪房间”、“火堆锻造痛击” |
| `confirm` | **通用确认交互**<br>无参。向下位机发送 `confirm` 指令 | 篝火锻造确认、卡牌升级完成、网格选牌确认 |
| `cancel_or_skip` | **跳过奖励或返回**<br>无参。向下位机发送 `cancel` 指令 | 跳过卡牌三选一、离开商店、退出选牌界面 |
| `proceed` | **推进结算流程**<br>无参。向下位机发送 `proceed` 指令 | 战斗胜利战利品领完后离开房间、通往下一层 |
| `reset_scenario` | **切换测试沙盒环境**<br>参数: `scenario: str`<br>可选: `"cultist"`, `"lethal"`, `"card_reward"`, `"reward"`, `"live"` | 离线调试、单元测试或切回 Steam 实机连接 |
| `solver_health` | **检查系统健康与连通性**<br>检查 Socket 通信、驱动类型及 FastMCP 运行状态 | 诊断服务可用性 |

---

### 4. 伴打与实战指令范例 (Examples)

连接 MCP 客户端后，你可以直接用自然语言对 AI 发号施令：

* **局势分析**：“*看一眼现在的牌面，计算一下痛击加两张打击能不能斩杀左边的小怪？*”
* **连招出牌**：“*先对 0 号怪打出痛击，然后打一张防御，最后结束回合。*”
* **商店消费**：“*看下商店里有什么牌和遗物，帮我买下无惧疼痛，再删掉牌组里的基础打击。*”
* **火堆锻造**：“*在火堆选择升级，帮我把痛击升级为痛击+，然后确认。*”

---

## 🧪 离线沙盒极速测试（无需打开游戏）

即使没有打开 Steam，你也可以在命令行中利用内置的沙盒模拟器进行极速算法验证：

* **邪教徒遭遇战沙盒（可看到双 HUD 实时弹出）**：
  ```bash
  python main.py --driver mock --scenario cultist
  ```
* **地精大块头精英战（检验禁忌技能防范机制）**：
  ```bash
  python main.py --driver mock --scenario gremlin_nob
  ```
* **残血斩杀测试（检验精准计算与连击逻辑）**：
  ```bash
  python main.py --driver mock --scenario lethal
  ```
* **运行 MCP Server 专属单元测试（7 个用例全覆盖）**：
  ```bash
  python -m unittest tests/test_mcp_server.py
  ```
* **运行全套自动化单元测试（94 个用例）**：
  ```bash
  python -m unittest discover tests
  ```

---

## 📁 核心日志与状态监控文件

- [`run_memo.md`](run_memo.md)：战略黑板实时保存文件，以标准 Markdown 记录流派演变与历史战斗复盘。
- [`run_bot.bat`](run_bot.bat)：CommunicationMod 唤醒全自动 Agent 运行的启动脚本。
- [`run_relay.bat`](run_relay.bat)：CommunicationMod 唤醒零时差 Socket 继电器的启动脚本。
- [`spire_agent/mcp_server.py`](spire_agent/mcp_server.py)：基于 FastMCP 构建的 Slay the Spire 标准 MCP 服务器。
- [`spire_agent/relay.py`](spire_agent/relay.py)：双向 Socket 广播桥梁，解决跨进程并发通信阻塞。
- [`mcp_config.example.json`](mcp_config.example.json)：AI 客户端 MCP 连接配置模板。
- [`run_bot.log`](run_bot.log)：CommunicationMod 唤醒批处理脚本的启动与退出时间戳记录。
- [`bot_debug.log`](bot_debug.log)：游戏与 Agent 之间所有的通信协议交互、大模型推演日志及调试信息。

---

## 👥 贡献者与结对致谢 (Contributors & Credits)

本项目由人类工程师与大语言模型代理结对编程（Pair-Programmed）协同构筑：

| 贡献者 / 协作角色 | 领域与职责 | 链接 |
| :--- | :--- | :--- |
| **Dovahkkin** | 👑 项目主创、游戏决策体系架构、实机测试与战略规划 | [@Dovahkkin](https://github.com/Dovahkkin) |
| **Google DeepMind Antigravity** | ⚡ AI 结对编程、FastMCP 协议服务器、零时差 Socket 继电器与符号计算库 | [Google DeepMind](https://deepmind.google/) |

> 💡 **致谢说明**：本项目的宏观/微观双层规划体系、FastMCP 协议服务器、怪物行动禁忌库以及零时差 Socket 继电器网桥均由人类开发者与 Google DeepMind Antigravity 深度协同结对实现。


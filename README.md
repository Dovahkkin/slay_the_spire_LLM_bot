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
用记事本打开 `config.properties`，填入以下内容：

```properties
command=C\:\\Users\\<你的Windows用户名>\\Documents\\slay-the-spire-llm-agent\\run_bot.bat
runAtGameStart=true
```

> ⚠️ **极其重要的语法注意点（Java Properties 转义规则）**：
> 1. **反斜杠与冒号转义**：Properties 文件中，路径中的冒号 `:` 前面**必须加反斜杠**转义（即 `C\:`），且路径分隔符必须是**双反斜杠**（即 `\\`）。
>    - ❌ 错误示范：`command=C:\Users\test\project\run_bot.bat`
>    - ✅ 正确示范：`command=C\:\\Users\\test\\project\\run_bot.bat`
> 2. **`runAtGameStart=true`**：该项设置为 `true` 时，每次游戏开局进入地牢，CommunicationMod 会**自动启动 `run_bot.bat` 并接管游戏**，不需要你每次在后台手动敲命令行！

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
* **运行全套自动化单元测试**：
  ```bash
  python -m unittest discover tests
  ```

---

## 📁 核心日志与状态监控文件

- [`run_memo.md`](run_memo.md)：战略黑板实时保存文件，以标准 Markdown 记录流派演变与历史战斗复盘。
- [`run_bot.log`](run_bot.log)：CommunicationMod 唤醒批处理脚本的启动与退出时间戳记录。
- [`bot_debug.log`](bot_debug.log)：游戏与 Agent 之间所有的通信协议交互、大模型推演日志及调试信息。

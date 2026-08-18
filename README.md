# san11-agent

《三国志11：威力加强版》(san11pk.exe) LLM 代理研究项目。让 LLM 像人类玩家一样操作游戏、推进一局对局，衡量 AI 与人类玩家的决策差距。个人研究项目，游戏为本地单机离线游戏。

完整项目规格见对话记录 / 项目 wiki（本仓库暂未收录规格文档本身）。核心约束：**信息边界**——中间层必须显式过滤，只暴露人类玩家在界面上能看到的信息，M2 已实现；**执行层**——键鼠模拟走 Win32 SendInput，动作可重入、失败即归位重来，M3 已搭好脚手架；**LegalActions**——AI 只能从"当前合法动作"的结构化列表里选，不能自己猜规则、不会输出非法指令，M4 做了内政阶段这一半；**战略层**——LLM 只做高层决策（每 N 回合一次），战术层用规则把意图翻译成动作，M5 本次搭好了这条链路的地基（假 LLM 后端），见下方"当前状态"。

## 当前状态：M5（地基）— 战略备忘录 + 战略层调用框架

**本次范围有一个重要前提**：真实游戏当前无法运行（用户机器锁屏、人在远程），
且不接任何真实 LLM API（用户明确要求）。所以本次**只做能离线测试的部分**：
战略备忘录读写、局势摘要、LLM 战略层接口（用假后端）、高层意图类型、内政
战术层、主循环——全部用 `FakeStrategyLLM`/`FakeGameStateSource`/
`FakeActionExecutor` 离线跑通，不调用任何真实模型、不操作真实游戏。验收
目标（来自项目规格）：

> **M5 — LLM 接入**：战略备忘录 + 战略层调用，跑通"AI 决策 -> 执行 -> 推进
> 回合"的完整循环，能连续自动推进若干回合。

- [x] **战略备忘录**（`san11agent/strategy_memo.py`）：Markdown 正文 +
  极简元数据头（`schema_version`/`turn`/`checksum`，纯 `key: value`，不引入
  PyYAML），原子写（临时文件 + `Path.replace()`）+ 写入前自动备份上一版
  （`<path>.bak`）+ 校验和检测损坏（`StrategyMemoCorruptedError`）+ 长度
  预算超限拒绝写入（`StrategyMemoTooLongError`，不做自动截断/自动摘要）
- [x] **局势摘要**（`san11agent/situation_summary.py`）：**核心约束同 M4**
  ——`summarize_situation()` 只建立在 M2 的 `VisibleGameState` 之上，完全
  不引用完整 `GameState`，`tests/test_situation_summary.py` 有专门的架构
  守卫测试（模块不绑定完整 GameState 类型名、AST 检查只 import 了
  `visible_state`/`legal_actions`、参数类型标注核实）守住这一点
- [x] **高层意图类型体系**（`san11agent/intent.py`）：结构化 `StrategicIntent`
  （不是自由文本），`default_focus`（内政重心，5种封闭枚举）+
  `city_directives`（按城池覆盖 + 记录镇守人选）+ `target_faction_index`/
  `expansion_notes`（攻打哪个势力/扩张方向，本次只做类型占位，不驱动动作
  ——没有战斗/出征执行层可以消费，见 docs/strategy_research.md 第3节）
- [x] **LLM 战略层接口**（`san11agent/strategy_llm.py`）：`StrategyLLM`
  抽象（`decide(prompt) -> str`，返回原始文本贴近真实 LLM 形态）+
  `FakeStrategyLLM`（可脚本化/可用 callable 驱动，完全离线不联网）+
  `build_strategy_prompt()`（局势摘要 + 备忘录 + JSON 输出格式说明三段拼接）
  + `parse_llm_response()`（fail closed 解析，逐字段校验，非法内容抛
  `StrategyParseError` 并点名具体字段）
- [x] **内政战术执行层**（`san11agent/domestic_tactics.py`）：**核心约束**
  ——`select_domestic_actions()` 返回的每个动作，必须是传入的
  `legal_actions`（M4 `enumerate_legal_actions()` 的产出）里的同一个对象，
  不能编造，`tests/test_domestic_tactics.py` 用身份检查（不是结构相等）
  守住这一点；实现是一张"重心 -> 动作类型优先级"的固定规则表，每个决策都
  带 `reason` 字段（可观测性要求）
- [x] **主循环**（`san11agent/strategy_loop.py`）：串起"读状态 ->
  (每N回合)调LLM更新备忘录/意图 -> 战术层出动作 -> 执行 -> 推进回合"，
  `GameStateSource`/`ActionExecutor` 两处抽象都只有假实现（复用 M3
  `FakeInputBackend` 的思路，只记录/只推进计数器，不做真实操作）；LLM
  返回非法内容/连续失败/备忘录超长/备忘录损坏，四类失败各有独立的处理
  策略，见 docs/strategy_research.md 第6节
- [x] 单元测试：`tests/test_strategy_memo.py` + `tests/test_situation_summary.py`
  + `tests/test_strategy_llm.py` + `tests/test_domestic_tactics.py` +
  `tests/test_strategy_loop.py`（M5 新增共 67 个测试），全部离线，不真的
  等待、不调用任何真实 API、不依赖真实游戏进程
- [ ] **真实 LLM 接入**——本次完全没有涉及，`StrategyLLM` 只有假实现
- [ ] **真实游戏场景下的实际验证**——主循环里的两处抽象
  （`GameStateSource`/`ActionExecutor`）都还没有真实实现，依赖 M1~M4 现有
  的全部缺口（锚点/坐标/规则数值）先解决
- [ ] 多条设计取舍需要你确认（备忘录超长时拒绝写入 vs 自动截断/自动摘要、
  连续 LLM 失败后整个循环停止 vs 继续用旧意图跑、`target_faction_index`
  等字段目前只记录不消费是否可接受等），全部列在 docs/strategy_research.md
  第7节

## 历史状态：M4（上半场）— LegalActions（内政阶段）

**本次范围有一个重要前提，和 M3 一样**：真实游戏当前无法运行（用户机器锁屏、
人在远程），所以本次**只做 LegalActions**（枚举当前合法动作），不做 Execute
（把 Action 转换成真实键鼠输入）——等真实游戏能跑、M3 的 camera/selection
内存缺口解决后再做 Execute。验收目标（来自项目规格）：

> `LegalActions`：枚举当前阶段所有合法动作（关键 —— AI 不需要猜规则，也不会输出非法指令）

- [x] 内政阶段动作类型体系（`san11agent/legal_actions.py`）：8 种
  `ActionKind`（设施建设/征兵/训练/治安巡查/征收金/征收粮/外交/计略），每种
  一个结构化 `frozen` dataclass（不是字符串），共享 `general_index`/
  `city_index`/`unverified_constraints` 基类
- [x] **核心约束**：`enumerate_legal_actions()` 只建立在 M2 的
  `VisibleGameState` 之上，完全不引用 M1 完整 `GameState` 的类型——用
  `isinstance(x, VisibleGeneralFull)`/`isinstance(x, VisibleCityDetail)`
  判断"信息是否充分"，而不是假设字段存在。`tests/test_legal_actions.py`
  里有专门的架构守卫测试守住这一点（模块不绑定完整 GameState 类型名、
  `state` 参数类型标注确实是 `VisibleGameState`、防御性 isinstance 检查）
- [x] 约束枚举覆盖：武将本回合是否已指派（显式参数，不来自内存）、体力是否
  充足、是否在该城（`location == city.index`，未经验证的假设，可自定义
  覆盖）、金钱粮草是否够（走规则表）、设施建设位是否可用、城池是否己方、
  计略目标归属是否已知（fail-closed）
- [x] 内政规则表 `rules/`（跟 `offsets/`/`ui_layout/` 平行的新目录）：
  `rules/schema.json` 格式定义 + `rules/domestic_actions_pk_1.1_cn.json`
  数据，加载器 `san11agent/domestic_rules.py`（风格模仿 `offsets.py`）。
  **所有资源消耗数值（体力/金/粮阈值）诚实标 `unknown`**——这些不是内存
  偏移问题，是游戏规则数值本身没有实机验证途径，没有编数字进去。**但这里
  `unknown` 的语义和 `offsets.py` 不同**：不会拒绝枚举，只会把动作标记
  `unverified_constraints`，供下游复核——这是一个明确的设计取舍，不是延续
  M1/M2/M3 的默认做法，见 docs/legal_actions_research.md 第2节
- [x] 单元测试：`tests/test_domestic_rules.py`（规则表加载器）+
  `tests/test_legal_actions.py`（44个测试，全部用手工构造的
  `VisibleGameState`/`DomesticRulesConfig`，完全离线，不经过 M1/M2 链路）
- [ ] **Execute（把 Action 转换成真实键鼠输入）**——有意留到真实游戏能跑时
  再做，这次完全没有涉及
- [ ] 多条设计取舍需要你确认（"治安"和"巡查"是否应该拆开、`levy_gold`/
  `levy_food` 是否应该合并、五种设施类型是否完整准确、`location==city.index`
  假设是否成立等），全部列在 docs/legal_actions_research.md 第4节

## 历史状态：M3 — 执行层最小链路脚手架

**本次范围有一个重要前提**：真实游戏当前无法运行（用户机器锁屏、人在远程），
且 M1 的 GAME_DATA_BASE 锚点仍未解决。所以 M3 这一轮**没有**接触真实游戏，
只搭建了这条链路的执行层基础设施，用可替换的假后端（dry-run）离线测试，
等锚点问题解决、游戏能跑时直接换上真实实现。验收目标（来自项目规格）：

> 验证一条完整链路：从内存读某城池格子坐标 → 滚动地图使其进入视野 → 点击 →
> 轮询确认内存中"当前选中城池"已变更。

- [x] `InputBackend` 键鼠输入抽象（`san11agent/input_backend.py`）：
  `SendInputBackend`（Win32 SendInput，仅 Windows，真的会发送输入，自动化
  测试里从未实际调用过）+ `FakeInputBackend`（只记录调用，支持
  `on_click`/`on_key_press` 回调模拟"游戏对输入做出反应"，供测试用）
- [x] 窗口/坐标（`san11agent/window.py`）：`ensure_dpi_awareness()` 启动时
  设置 DPI 感知；`Win32GameWindow.client_to_screen()` 做客户区->屏幕坐标
  换算；`FakeGameWindow` 供离线测试
- [x] 界面固定元素坐标表（`ui_layout/`，格式参考 `offsets/` 的做法）+ 加载器
  （`san11agent/ui_layout.py`）——生产文件 `ui_layout/pk_1.1_cn.json` 目前
  只搭好了格式，`map_viewport` 等元素全部 `unknown: true`（游戏无法运行，
  完全没有测量数据）
- [x] 地图格子坐标 -> 屏幕坐标换算（`san11agent/map_projection.py`）：从
  内存读摄像机偏移/缩放反算屏幕位置，目标在视野外返回 `None` 交给上层滚动。
  换算公式（正交网格 + 线性缩放假设）**未经真实游戏验证**，见
  docs/execution_research.md
- [x] 通用轮询/超时/重试机制，可注入时钟（`san11agent/clock.py` +
  `san11agent/polling.py`）：禁止固定 sleep，所有等待走 `poll_until()`，
  测试用 `FakeClock` 完全不真的等待
- [x] 归位例程 + 可重入的动作序列（`san11agent/execution.py`
  `CitySelector`）：失败即连按 Esc 归位、整个动作重来，不做中途状态恢复；
  归位目前只能做到"发 Esc"，无法校验是否真的回到已知界面（`GlobalState.phase`
  仍是 M1 遗留的 unknown 字段）
- [x] 完整动作日志（`san11agent/action_log.py`）：时间/意图/参数/结果/
  执行前后状态差异
- [x] `offsets/pk_1.1_cn.json` 新增 `camera`（摄像机偏移/缩放）、
  `selection`（当前选中城池）两个 struct，按 M1 既有原则标 `unknown: true`，
  不猜测填值
- [x] CLI `select-city` 子命令（`san11agent/cli.py`），默认演练模式
  （`FakeInputBackend`，不发送真实输入），加 `--live` 才切换到真实后端
- [x] 单元测试：假后端 + 假内存（新增 `MutableMemoryReader`）+ 可注入时钟，
  完全离线，覆盖成功/滚动进视野/超时重试/归位/配置缺失报错等分支
- [ ] **真实游戏场景下的实际验证**——依赖 `camera`/`selection` 两组新增
  unknown 字段、`ui_layout` 坐标测量、以及第3节列出的多条设计假设（地图
  网格形状、滚动输入方式、SendInput 是否被游戏感知等），全部详见
  docs/execution_research.md

**没有做**（有意，等真实游戏能跑、锚点问题解决后再推进）：跟真实游戏的
实际联调（发一次真实点击、看游戏是否响应）、LegalActions/Execute 更高层的
动作接口、LLM 接入、战斗。

## 历史状态：M2 — 信息边界过滤器

在 M1（内存读取与状态解析）之上加了一层白名单式过滤器，把完整 `GameState` 转换成人类可见的 `VisibleGameState`。

- [x] `VisibilitySource` 可见性来源抽象（`san11agent/visibility.py`）：`StaticVisibilitySource`（离线合成，供测试用）+ `UnresolvedVisibilitySource`（真实进程占位——探明/视野/武将发现相关内存字段还没找到，调用会显式报错，不猜测）
- [x] 白名单式人类可见状态类型（`san11agent/visible_state.py`）：默认不暴露，每个字段都要显式列出才会出现；城池/武将/势力按"是否需要额外权限查看细节"拆成 Summary/Detail、Public/Full 两级类型，而不是用 `Optional` 字段表达"看不到"
- [x] 过滤器本体（`san11agent/boundary.py`）：`filter_game_state(state, visibility) -> VisibleGameState`
- [x] 对比测试：完整 GameState fixture vs 过滤后结果逐字段断言禁止字段不泄漏 + 白名单字段集合回归测试（`tests/test_boundary.py`、`tests/test_visibility.py`）
- [ ] 真实进程场景下的实际验证——依赖 M1 的 `city.faction_id` 缺口和 M2 新发现的探明/视野/武将发现缺口，见 `docs/visibility_research.md`

CLI 暂未接入 `--visible` 之类的过滤开关——见提交报告里的说明。

## M1 — 内存读取与状态解析（已完成）

- [x] offsets 文件格式（`offsets/schema.json`）与候选偏移表（`offsets/pk_1.1_cn.json`）
- [x] 内存读取抽象层：真实进程（Win32 ReadProcessMemory）+ 离线 dump 两套实现，上层解析代码不关心用的是哪套
- [x] GameState 解析：武将表、城池表、部队表、势力表、全局参数（回合/日期）
- [x] 命令行快照工具
- [x] 单元测试（离线合成 fixture，不依赖真实游戏进程）
- [ ] **真实内存 dump 验证** —— 尚未在真实游戏进程上跑过，见下方"已知缺口"

## 目录结构

```
docs/offset_research.md        M1：内存偏移的调研报告——来源、可信度评估、所有未解决问题
docs/visibility_research.md    M2：可见性状态的调研报告——探明/视野/武将发现相关缺口
docs/execution_research.md     M3：执行层调研报告——camera/selection 内存缺口、ui_layout 坐标缺口、所有未经验证的设计假设
docs/legal_actions_research.md M4：LegalActions 设计取舍报告——Action 类型体系、约束建模、规则表 unknown 语义的取舍、需要你确认的问题
docs/strategy_research.md      M5：战略层设计取舍报告——备忘录格式/避免损坏/长度控制、局势摘要、意图类型体系、战术层"只能挑选不能编造"的保证、主循环调用节奏与失败处理策略、需要你确认的问题
docs/verification_checklist.md  汇总 M1~M4 全部待验证事项，按"启动游戏→定位锚点→验证偏移→定位缺失字段→测坐标→验证规则"的实机操作顺序排列，供游戏能运行后按顺序执行（M5 本次不接真实游戏/真实 LLM，没有新增需要实机验证的事项）
offsets/schema.json       offsets 文件的格式定义（人类可读的权威文档）
offsets/pk_1.1_cn.json    候选偏移表（未在真实进程验证过，meta.verified=false；含 M3 新增的 camera/selection struct）
ui_layout/schema.json     ui_layout 文件的格式定义（客户区固定元素坐标表，跟 offsets 平行但不是内存偏移）
ui_layout/pk_1.1_cn.json  界面坐标表（M3 阶段游戏无法运行，全部 unknown，只搭好格式）
rules/schema.json         内政动作规则表的格式定义
rules/domestic_actions_pk_1.1_cn.json  内政动作规则表（M4，资源消耗数值全部诚实标 unknown，见 docs/legal_actions_research.md）
san11agent/
  memory.py                MemoryReader 抽象 + ProcessMemoryReader(真实进程) + DumpMemoryReader(离线dump) + MutableMemoryReader(可写，仅供 M3 测试用)
  offsets.py                加载/校验 offsets json
  game_state.py             GameState 数据结构（General/City/Troop/Faction/GlobalState）—— M1，完整未过滤
  perception.py             anchor 解析 + 按 offsets 把内存字节解析成 GameState + 启动常量校验 + read_struct_fields() 公共读取逻辑
  cli.py                     命令行工具：snapshot（快照）+ select-city（M3 执行链路，默认演练模式）
  visibility.py              M2：VisibilitySource 抽象 + StaticVisibilitySource(离线) + UnresolvedVisibilitySource(真实进程占位)
  visible_state.py           M2：白名单式人类可见状态类型（VisibleGameState 及其子结构）
  boundary.py                M2：filter_game_state()，GameState -> VisibleGameState 的过滤器本体
  clock.py                   M3：Clock 抽象 + SystemClock(真实) + FakeClock(测试用可控时钟)
  polling.py                 M3：poll_until() 通用轮询/超时机制，可注入 Clock
  action_log.py              M3：ActionLog/ActionLogEntry，完整动作日志（时间/意图/参数/结果/状态差异）
  window.py                  M3：GameWindow 抽象 + Win32GameWindow(真实，ClientToScreen) + FakeGameWindow(测试) + ensure_dpi_awareness()
  input_backend.py           M3：InputBackend 抽象 + SendInputBackend(真实 Win32 SendInput) + FakeInputBackend(测试，支持回调)
  ui_layout.py                M3：加载 ui_layout/*.json 界面固定元素坐标表
  execution_state.py         M3：CameraState/SelectionState 解析（复用 perception.read_struct_fields）
  map_projection.py          M3：地图格子坐标 -> 客户区坐标换算（project_tile_to_client）
  execution.py               M3：CitySelector 执行链路——滚动进视野→点击→轮询确认→失败归位重来
  domestic_rules.py          M4：加载/校验 rules/*.json 内政动作规则表（RuleValue/ActionRuleSpec/DomesticRulesConfig）
  legal_actions.py           M4：内政阶段 Action 类型体系（8种 ActionKind）+ enumerate_legal_actions()——只依赖 VisibleGameState
  intent.py                  M5：高层战略意图类型体系（DomesticFocus/CityDirective/StrategicIntent）
  strategy_memo.py           M5：战略备忘录读写（格式/原子写/备份/校验和/长度预算）
  situation_summary.py       M5：VisibleGameState -> 给 LLM 看的局势摘要（summarize_situation/render_situation_text）——只依赖 VisibleGameState
  strategy_llm.py            M5：StrategyLLM 抽象 + FakeStrategyLLM + 提示词组织（build_strategy_prompt）+ 输出解析（parse_llm_response）
  domestic_tactics.py        M5：内政战术执行层——select_domestic_actions() 把 StrategicIntent 翻译成 M4 合法动作，只能挑选不能编造
  strategy_loop.py           M5：主循环 StrategyLoop——串起状态源/LLM/战术层/执行后端，GameStateSource/ActionExecutor 均为假实现
tests/
  test_offsets.py            offsets 文件加载与校验的单元测试
  test_perception.py          GameState 解析的单元测试（合成 fixture）
  test_cli.py                  命令行工具（snapshot）的单元测试
  test_cli_select_city.py      命令行工具（select-city）的冒烟测试
  test_visibility.py           VisibilitySource 各实现的单元测试
  test_boundary.py             M2 核心：完整 GameState fixture vs 过滤结果的对比测试 + 白名单字段回归测试
  test_memory.py                MutableMemoryReader 单元测试
  test_clock.py                 FakeClock 单元测试
  test_polling.py               poll_until() 单元测试（超时/重试，不真的等待）
  test_action_log.py            ActionLog/diff_state 单元测试
  test_window.py                FakeGameWindow/ensure_dpi_awareness 单元测试
  test_input_backend.py         FakeInputBackend 单元测试 + SendInput 坐标换算纯函数测试
  test_ui_layout.py             ui_layout 加载器单元测试
  test_map_projection.py        地图坐标换算单元测试
  test_execution_state.py       CameraState/SelectionState 解析单元测试
  test_execution.py             M3 核心：CitySelector 全链路测试（成功/滚动/超时重试/归位/配置缺失报错）
  test_domestic_rules.py        M4：规则表加载器单元测试（生产文件 + 测试 fixture + 格式错误）
  test_legal_actions.py         M4 核心：44个测试——架构守卫（只依赖 VisibleGameState）、约束枚举、资源阈值拦截、可观测性
  test_strategy_memo.py         M5：战略备忘录读写单元测试（格式往返/原子写/备份/长度拒绝/校验和损坏检测/恢复）
  test_situation_summary.py     M5：局势摘要单元测试——架构守卫（只依赖 VisibleGameState）+ 摘要内容正确性
  test_strategy_llm.py          M5：StrategyLLM 单元测试——提示词组织、FakeStrategyLLM 两种驱动方式、parse_llm_response 逐字段容错
  test_domestic_tactics.py      M5 核心：内政战术层单元测试——身份检查"动作确实来自 legal_actions"、重心优先级映射、防御性报错
  test_strategy_loop.py         M5 核心：主循环端到端测试——连续多回合空跑、调用节奏、LLM非法/超长/备忘录损坏等失败处理策略
  fixtures/
    offsets_test.json                    M1/M2 用：仅供测试的最小偏移表（结构形状同生产文件，数值是编的）
    offsets_execution_test.json          M3 用：只含 camera/selection 的最小偏移表
    ui_layout_test.json                  M3 用：含已知坐标的 ui_layout 测试 fixture
    domestic_rules_test.json             M4 用：全部资源数值 unknown 的最小规则表 fixture
    build_synthetic_dump.py              生成 M1/M2 合成内存 dump 的脚本
    synthetic_dump.json                  M1/M2 合成内存 dump（已提交方便直接跑测试）
    build_synthetic_execution_dump.py    生成 M3 CLI 冒烟测试用合成内存 dump 的脚本
    synthetic_execution_dump.json        M3 合成内存 dump（已提交方便直接跑测试）
```

## ⚠ 已知缺口

**M1**（详见 docs/offset_research.md）：最重要的一条是 offsets/pk_1.1_cn.json 里 `anchor.resolution_method = "unknown"`——目前找到的开源资料只给出了"某次运行观测到的一个绝对地址"，完全没说明这个地址是编译期固定的静态地址、还是需要指针链才能定位的堆地址。在这个问题解决之前，`ProcessMemoryReader` 真实进程模式会在 `resolve_anchor()` 直接抛出 `AnchorResolutionError` 并拒绝继续——这是刻意设计，不是 bug。其余缺口：城池所属势力ID/地图坐标、当前年月日的直接字段、游戏阶段标志位——全部标记为 `unknown: true`，解析时会安静地返回 `None`，不会报错也不会编数据。

**M2**（详见 docs/visibility_research.md）：探明城池/视野内部队/已发现在野武将这三类可见性状态，在现有内存资料里完全没有找到对应字段。真实进程场景下调用 `UnresolvedVisibilitySource` 的对应方法会显式抛出 `VisibilityUnknownError`。另外，M1 里 `city.faction_id` 本身也是 unknown，导致过滤器目前无法在真实进程数据上正确判断"这座城是不是我的"——会保守地把所有城池当非己方处理（只给摘要，不泄漏，但也不好用），这两个缺口解决前，M2 过滤器在真实对局里还用不起来，但离线测试证明了过滤逻辑本身是对的。

**M3**（详见 docs/execution_research.md）：`camera`（摄像机偏移/缩放）、`selection`（当前选中城池）两组新增内存字段完全未定位；`ui_layout/pk_1.1_cn.json` 里的界面坐标（`map_viewport`）完全没有真实测量数据。这两类缺口解决前，`CitySelector` 在真实进程场景下会在坐标换算那一步显式报错，不会用编出来的坐标点击。另外，这次新写的地图坐标换算公式、地图滚动的输入方式（假设方向键）、SendInput 是否被游戏感知，都是**未经真实游戏验证的设计假设**，不是已确认的事实——详见 docs/execution_research.md 第3节和第5节"需要你确认的问题"。

**M4**（详见 docs/legal_actions_research.md）：`rules/domestic_actions_pk_1.1_cn.json` 里全部资源消耗数值（体力/金/粮阈值）都是 unknown——这些不是内存偏移问题，是游戏规则数值本身没有实机验证途径，unknown 时 LegalActions 不会拦截，只会记录进 `Action.unverified_constraints`（这个"不拦截"的默认行为本身是需要你确认的取舍，见报告第2节）。另外，"武将是否在这座城"（`location == city.index`）、"治安/巡查是否应合并"、"五种设施类型是否完整准确"等多条设计假设**未经真实游戏验证**，详见 docs/legal_actions_research.md 第4节"需要你确认的设计取舍"。武将适性/特技完全没有对应数据模型字段，本次没有实现相关约束（不是漏做，是数据模型目前不支持）。

**M5**（详见 docs/strategy_research.md）：本次完全不接真实 LLM API、不接真实游戏，`StrategyLLM`/`GameStateSource`/`ActionExecutor` 三处抽象接口都只有假实现——真实 LLM 接入、真实 Execute（把内政 Action 变成键鼠输入）都留给后续里程碑，且后者依赖 M1~M4 现有的全部内存/坐标/规则数值缺口先解决。另外，`llm_call_interval`（每N回合调用一次）的默认值、备忘录超长时"拒绝写入"而非"自动截断/自动摘要"、连续 LLM 失败后"整个循环停止"而非"继续用旧意图跑"，都是**没有依据支撑的占位取舍**，需要你确认，详见 docs/strategy_research.md 第7节。

## 运行

开发机上 `python`/`pip` 命令本身是 Windows Store 的执行别名占位符（不可用），但机器上装有独立的 Python 3.12（`%LOCALAPPDATA%\Programs\Python\Python312\python.exe`），已用它实际跑过下面的命令并确认可用（M1~M5 共 264 个测试全通过，全部离线、不依赖真实游戏、不调用任何真实 LLM API、不真的等待）。

```bash
pip install -r requirements-dev.txt

# 生成合成测试 dump（仓库里已经带了一份生成好的，一般不需要重新生成）
python tests/fixtures/build_synthetic_dump.py
python tests/fixtures/build_synthetic_execution_dump.py

# 跑单元测试
pytest

# 命令行工具：离线 dump 模式，打印快照
python -m san11agent.cli snapshot --offsets tests/fixtures/offsets_test.json --dump tests/fixtures/synthetic_dump.json --summary

# 命令行工具：真实进程模式（预期会因为 anchor unknown 而报错退出，这是当前阶段的正确行为）
python -m san11agent.cli snapshot --offsets offsets/pk_1.1_cn.json --process san11pk.exe

# 命令行工具：M3 执行链路，离线演练模式（不发送真实输入，用 --dump 只读内存所以最终会轮询超时，用来验证链路本身跑不跑得通）
python -m san11agent.cli select-city --offsets tests/fixtures/offsets_execution_test.json --ui-layout tests/fixtures/ui_layout_test.json --dump tests/fixtures/synthetic_execution_dump.json --city-index 3 --tile-x 5 --tile-y 5 --poll-timeout 0.2
```

运行时依赖：无第三方库，只用了标准库（`ctypes`/`json`/`dataclasses`/`argparse`/`hashlib`/`shutil`）。测试依赖：`pytest`（见 `requirements-dev.txt`）。M2 的过滤器暂未接入 CLI（`san11agent.cli` 还没有 `--visible` 之类的开关），只能通过 Python API（`san11agent.boundary.filter_game_state`）调用——见提交报告里的说明。M3 的 `select-city` 子命令默认是演练模式（`FakeInputBackend`，不发送真实输入），要真的操作游戏窗口需要显式加 `--live`（仅 Windows，且目前 camera/selection 字段/ui_layout 坐标都是 unknown，实际跑不通，见上方"已知缺口"）。M4 的 LegalActions 同样暂未接入 CLI，只能通过 Python API（`san11agent.legal_actions.enumerate_legal_actions`）调用。M5 延续同样的做法，`san11agent.strategy_loop.StrategyLoop` 同样暂未接入 CLI，只能通过 Python API 组装（`FakeStrategyLLM`/`FakeGameStateSource`/`FakeActionExecutor`，见 `tests/test_strategy_loop.py` 里的完整用法示例）——本次只做到"能离线连续空跑若干回合"，接入命令行/接真实 LLM/接真实游戏留给后续里程碑。

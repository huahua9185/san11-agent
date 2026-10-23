# san11-agent 开发交底说明

更新日期：2026-10-23。交底基线：[`b8f7f9a`](https://github.com/huahua9185/san11-agent/commit/b8f7f9ab4ab10529f1b6a8c8ec9751d728ac769e)，分支 `master`；本文描述该基线，之后又有 LegalActions 子类型金价、巡察后置验证等提交，接手时以 `git log` 和当前工作区为准，不要覆盖后来工作。

本文供没有先前对话的智能体接续开发。**已确认**指源码、记录或明确实验支持的结论；方案、解释和未覆盖情况以**推测／待验证**标记。原始证据和历史报告不应因新结论被改写成“当时已经确认”。

## 1. 先建立正确预期

**已确认（README、当前源码）**：这是《三国志11：威力加强版》本地单机LLM代理研究项目。目标是读取游戏局势，经中间件过滤为人类玩家可见的信息，让LLM制定高层意图，再由规则战术层选动作、键鼠执行层操作游戏并读取反馈，研究AI与人类玩家的决策差异。

**当前没有实现生产自动对局闭环。** 真实读取已经存在，但真实模型后端、完整动作执行器及自动推进旬仍未完成。受控UI实验已经完成一次巡察和一次旬，不能把这件事表述为程序已能自动玩游戏。

完整规格/wiki未收录于仓库，无法从现有文件确认全部产品验收细则。README中M3～M5以及旧报告的“游戏无法运行”“字段未定位”等文字含历史条件；先读其顶部更新，再读最新专题报告。

建议阅读顺序：

1. 本文 → [README 当前进展](README.md)。
2. [巡察成本与军团预算](docs/rea_action_budget_2026-10-23.md)：当前最新研究结果和后续路径。
3. [武将已行动状态](docs/rea_general_action_state_2026-10-23.md)、[军团行動力](docs/rea_action_points_2026-10-22.md)。
4. 按任务阅读 [执行层](docs/execution_research.md)、[LegalActions](docs/legal_actions_research.md)、[可见性](docs/visibility_research.md)、[战略层](docs/strategy_research.md)。
5. 需要原始论据时，再按专题报告的文件名和Evidence ID查询 [REA证据目录](docs/rea/)；环境与研究时间线在 [REA研究记录](docs/rea_research.md)。

## 2. 当前实现与代码入口

以下由链接源码确认；“存在”不表示所有规则均已通过实机穷举。

| 环节 | 当前状态 | 接手入口 |
|---|---|---|
| 版本布局与读取 | offsets配置、动态锚点、结构解析已有实现；不能把配置顶层verified=false改成全局已验证 | [offsets](offsets/pk_1.1_cn.json)、[perception.py](san11agent/perception.py)、[memory.py](san11agent/memory.py) |
| 势力归属 | 使用对象force_id → Force.faction_id → Faction；General的历史faction_id字段不能直接当政治势力ID | [faction_resolve.py](san11agent/faction_resolve.py) |
| 信息边界 | GameState → VisibleGameState；军团余额和武将行动状态仅保留己方字段 | [boundary.py](san11agent/boundary.py)、[visible_state.py](san11agent/visible_state.py) |
| 可见性来源 | StaticVisibilitySource接受显式集合；UnresolvedVisibilitySource仍是占位并会对未知查询报错，非真实自动视野 | [visibility.py](san11agent/visibility.py) |
| 动作枚举 | 内政候选已有12种ActionKind；unknown约束会标记但未全部阻止候选生成 | [legal_actions.py](san11agent/legal_actions.py)、[domestic_rules.py](san11agent/domestic_rules.py) |
| 战略层 | 摘要、备忘录、意图解析、调用接口及FakeStrategyLLM存在；没有真实模型后端 | [situation_summary.py](san11agent/situation_summary.py)、[strategy_llm.py](san11agent/strategy_llm.py)、[strategy_memo.py](san11agent/strategy_memo.py) |
| 战术与循环 | 按意图选择候选，FakeActionExecutor用于离线验证；当前一次读状态后选整批，再逐条执行 | [domestic_tactics.py](san11agent/domestic_tactics.py)、[strategy_loop.py](san11agent/strategy_loop.py) |
| 真实状态源 | RealGameStateSource.read复用解析和边界过滤；advance_turn仍抛NotImplementedError | [strategy_loop.py](san11agent/strategy_loop.py) |
| 键鼠执行 | SendInputBackend、执行/菜单/轮询脚手架存在；地图定位、相机、选中对象和阶段仍有缺口，未接成真实ActionExecutor | [input_backend.py](san11agent/input_backend.py)、[menu_execution.py](san11agent/menu_execution.py)、[execution_state.py](san11agent/execution_state.py)、[map_projection.py](san11agent/map_projection.py) |
| 动作后置验证 | 巡察验证器已实现（前后 VisibleGameState 对比，confirmed/failed/inconclusive 三值）；尚未接真实执行器 | [patrol_verification.py](san11agent/patrol_verification.py) |
| 城池选择 | 2026-10-23 菜单 A/B + 纯悬停 A/B 均验证 manager+0x64 → 城市对象 → index；reader 已接入 parse_selection_state 的 unknown 回退；camera 仍缺 | [selection_reader.py](san11agent/selection_reader.py)、[execution_state.py](san11agent/execution_state.py) |

数据流：

```text
MemoryReader + offsets → parse_game_state → GameState
  → filter_game_state(VisibilitySource) → VisibleGameState
    ├─ summarize_situation → render_situation_text → build_strategy_prompt → StrategyLLM
    └─ enumerate_legal_actions → select_domestic_actions → ActionExecutor
         → 待完成：实机后置验证 → 重读/重算 → 继续或推进旬
```

LegalActions、摘要和模型输入不得绕过VisibleGameState读取隐藏信息。现有架构测试会检查相关导入和类型边界。

## 3. 已确认的数据与不能外推的部分

仅对应下面第4节指定构建，完整依据见三个REA专题报告。

| 数据 | 已确认并接入的解释 | 尚不能据此声称 |
|---|---|---|
| 军团表 | `GAME_DATA_BASE+0xB20C+index*0x50`；容量47 | 47个活跃势力；Faction表也应改为47 |
| 行動力 | `Force+0x2C`，u8；己方VisibleForce及摘要中有余额，未知保留None | 城池各有独立余额；每旬固定加55或重置90 |
| 武将行动状态 | `General+0x124`的u32位0 → has_acted；只向己方公开布尔值 | 其他位语义已知；False就一定能执行任意指令 |
| 巡察费用 | 前置检查及扣减链对一次指令使用20行動力、100资金；1～3人不按人数倍增 | 所有指令费用固定；多人执行模型已完成 |
| 巡察治安条件 | 已接入治安达到100时排除候选 | 已完成真实99/100边界实验或全部巡察资格判定 |
| 成本规则 | `action_points_cost`是基础标价；新增`effective_action_points_cost`才用于已核实的余额硬检查，生产仅巡察=20 | 基础价等于实际价；未知折扣可直接忽略或全部减半 |

**已确认**：以下约束标记仍可能出现在候选中：

- `general_action_state`：已行动状态未知。
- `action_points_cost`：有效费用未知。
- `action_points_balance`：所属己方军团余额缺失、未知或ID重复；不借用敌方或另一己方军团余额。
- `patrol_preconditions`：巡察仍有未解析的前置条件；即使余额足够也保留。
- 设施、科技、登庸等其他标记见源码，不能把上面列表当成全部未知项。

**待验证／尚未实现**：候选中的未知约束不能自动视为安全通过并交给无人复核的真实执行器。当前尚无该真实执行器的完整门禁。

**已确认**：枚举的动作是备选，不是已预留资源的一批计划。同军团有20点时，A城和B城巡察都可作为备选，不代表两条都能执行。当前循环每次从空assigned集合开始，尚未逐动作读取真实变化，也未做整批共享预算调度。

## 4. 实机基线与历史实验

**已确认（留存记录，非接手时实时状态）**：

- 游戏：Steam繁中San11WPK.exe，x86；记录中的Steam build为2520441，文本cp950。
- 原EXE SHA-256：`f2a304b118e72673f4a788b1e87322fa891ff57218a8b89e671d4f8cb6aca041`。
- 原机器路径：`C:\Program Files (x86)\Steam\steamapps\common\San11WPK\San11WPK.exe`；仓库原工作目录`C:\projects\san11-agent`。另一机器不得假设这些路径存在。
- 实验记录PID33888、模块基址0x400000；均不是下次可复用的身份。每次重查PID、模块基址、文件指纹及结构锚点。
- 剧本1，曹操势力0，陈留城市12，军团0；事前保存到空白槽5，备注`REA-20261022-before`。
- 巡察选择曹操343、夏侯惇85、夏侯淵78：行動力55→35、资金4200→4100、治安80→91，三人已行动false→true、体力仍100。
- 仅推进一旬：日期190-1-1→190-1-11，行動力35→90；关闭军师提示后恢复地图操作，三人已行动恢复false。后续只读复核仍在旬1、军团余额90。
- 主要记录：[受控实验](docs/rea/2026-10-22/live_patrol_and_turn.json)、[人员字节时间线](docs/rea/2026-10-23/general_flags_timeline.json)、[最终预算读取](docs/rea/2026-10-23-budget/production_budget_readback_with_eligibility_marker.json)。

**待验证**：接手时游戏是否运行、当前存档/控制权、槽5是否仍可恢复、用户是否正在输入。不要直接沿用历史窗口句柄、截图ID、鼠标坐标、PID和绝对内存地址。

历史用户授权的一次巡察及一次旬已执行完毕，不等于允许无限追加实验。新实验按当前用户指令和已有明确授权范围执行，先安排可恢复状态与结束条件；不要覆盖未知存档或盲重试最终确认。当前交底任务本身不需要操作游戏。

若宿主提供san11桥接器，先调用get_game_status并通过兼容性检查，才信任结构化读取。该桥接器不是仓库自动附带的服务，工具名称/连接情况依宿主而定。实际UI操作使用宿主支持的计算机操作工具及其指引；生产实现走项目输入后端。研究中的读取不应改成写内存、注入或调用内部函数来代替键鼠。

## 5. 下一步从哪里做（待验证方案）

建议先完成一个可验证的小闭环，不先扩大动作种类或接模型API。

| 优先级 | 任务与具体入口 | 需要获取的数据／建议验收 |
|---|---|---|
| P0-1 | 补巡察资格。REA已有`0x5CC000`门槛、`0x5B8750`选将、`0x5B8520`人员判断；继续解释`0x486930`、`0x47B530`等未知分支 | 当前城市/阶段、人员身份/任务/驻地、可能的次数限制；逐项与允许/禁用、取消、已行动等UI对照后再消除patrol_preconditions |
| P0-2 | 定位执行所需界面状态。沿`0x60B4E0`巡察面板的目标指针、选择槽及确认处理继续追踪 | 选中对象类型/ID、城市设施坐标、相机投影、菜单/确认/动画/玩家控制状态；接入execution_state/menu_execution/map_projection，覆盖A城/B城/空地、取消和相机变化 |
| P0-3 | 实现单条真实ActionExecutor及明确后置结果 | 核对目标、执行者、确认费用；再核对军团余额、资金、治安与人员变化。已发送不等于已确认；超时先查状态，结果不明不能盲点重试 |
| P0-4 | 改造StrategyLoop为每条动作后重读/重算 | 同军团跨城不重复分配；失败与结果不明分开处理；避免Fake源不变时无终止地循环。新循环要有动作数/进度/失败终止条件及有意义的回归测试 |
| P0-5 | 实现真实advance_turn | 精确日期增量、军团恢复、人员清位、事件退出及玩家重新获得控制共同验收；不能仅凭日期变了就继续输入 |
| P1 | 条件费用、真实VisibilitySource、真实模型 | 先完成城市设施类型/生效条件与指令映射、信息边界对照，再接模型做对局比较；完整规格缺口需继续明确 |

每项改动应明确：新增字段如何从读取层进入己方可见态、如何被候选/摘要/执行器消费、失败与unknown怎样处理、哪些证据支持、哪些仍未覆盖。不要为让循环“跑通”而吞掉NotImplementedError或把真实依赖换成假成功。

**2026-10-23 camera阻塞（待处理）**：探针原先未做 DPI 感知，在 175% 缩放下
读到虚拟化 `1462×914`；加 `ensure_dpi_awareness()` 后客户区为 `2560×1600`，
`ui_layout` 视口匹配。但四点悬停/点击标定仍无法用二维等距公式拟合
（仿射最大残差约34px），地图很可能是3D透视/地形视图，camera字段仍未定位。
详见[camera报告](rea_camera_2026-10-23.md)。已开始D3D静态排查：修正vtable
偏移后找到4处SetTransform，全部是WORLD(0x100)，没有VIEW/PROJECTION；
42处`+0x178`调用的语义仍待确认，见[D3D报告](rea_d3d_2026-10-23.md)。
已用 apitrace 抓取 D3D9 trace，拿到真实 VIEW/PROJECTION 矩阵；4K四城验证
得到 map→world 仿射并固化到 [map_camera.py](san11agent/map_camera.py)。
已实现 d3d9 代理 DLL，把实时 VIEW/PROJECTION 写入 `Local\San11Camera`，
[camera_reader.py](san11agent/camera_reader.py) 可读取；实机数值与4K trace
一致。`CitySelector` 已增加 live camera 分支；2026-10-23 实机悬停平原成功
（selection None→4，只移动鼠标未点击）；`ActionMenuExecutor` 也已接入
live camera；当前 428 passed。4K下右键自己的城陈留已测到城池指令菜单与
“都市”二级菜单坐标；游戏崩溃后改用 2048×1152 窗口，又测到南皮的
2048 坐标。两者不是线性缩放，均仅单城单样本，未写入生产 ui_layout，见
[4K菜单测量](rea_4k_menu_2026-10-23.md) /
[2048菜单测量](rea_2048_menu_2026-10-23.md)。第二座城小沛复测显示菜单相对
城池的偏移不稳定，固定偏移模型不成立；未修改生产offsets/ui_layout。

**2026-10-23 selection追加（未写入生产offsets）**：`DAT_096a58f0+0x64`
指向当前城池对象；`FUN_004919a0` 用
`(obj-(GAME_DATA_BASE+0x89730))/0x38` 算索引。菜单点击和纯悬停两种 A/B
都已验证：濮陽/index 11、南皮/index 3，移开鼠标后manager回0。
对象`+0x1C/+0x20`是`city.map_x/map_y`候选，42城坐标与内政用地坐标空间相关。
`selection_reader` 已接入 `parse_selection_state` 的 unknown 回退；详见
[selection报告](rea_selection_2026-10-23.md)。

## 6. REA接续方法与避坑

**已确认（本仓库脚本与记录）**：

- 工具入口：[便携CLI](tools/rea-portable.ps1)、[持久研究会话](tools/rea_research_session.py)；研究脚本见[tools](tools/)。`.rea-tools/`被gitignore排除，GitHub克隆不含引擎、JDK、安装包、派生载体或本地请求队列。
- 原环境REA6.4.0、Ghidra12.1.4、Temurin JDK21.0.12.1+1；下载来源、校验和在[环境记录](docs/rea_research.md)。新机器需先确认可用环境，不能仅凭仓库存在wrapper就宣称provider可用。
- Python测试只依赖requirements-dev中的pytest；研究脚本另用Capstone、MCP Python SDK、已安装的Node/REA等。它们没有全部写入生产/开发依赖表，需要按脚本核对，不能假设全新环境已具备。
- 会话脚本目前硬编码项目内Ghidra/JDK目录，REA启动器取`%APPDATA%/npm/node_modules/rea-agents/scripts/rea.mjs`。路径不匹配时先按新环境适配，不更改无关全局客户端配置。
- 磁盘.text与加载.text不同。当前分析载体是仅替换.text的**混合派生文件**，并非原发行EXE或完整解包程序；SHA-256为`bc7f57cf26fc7a17f3e85d520543f397d93fbba7bea13a74162f32bbe6410e8f`。来源见[provenance](docs/rea/loaded_text_provenance_2026-10-15.json)。不得执行它或替换游戏文件。
- 派生脚本要求加载.text两次一致，并拒绝未经处理的重定位。需要重新生成时先检查[derive_loaded_text.py](tools/derive_loaded_text.py)，选择不存在的新输出，保留来源；不通过校验就继续推理是无效证据。
- 旧会话已关闭；优先复用仓库结果，不重复对同一函数导入分析。新会话首次Ghidra分析曾耗时约3分钟，后续同会话查询快；这是历史观察，不是耗时保证。
- 非交互exec的stdin可能直接EOF：需要后续查询时使用`--inbox`请求目录，不能假设write_stdin可驱动脚本。请求格式为`name/arguments/label`；标签与输出不可重复，空闲15分钟自动关闭，结束时发close_binary。

会话启动形状（先创建包含open_binary请求的UTF-8 plan，并替换为当前真实路径；下面路径是新研究任务的占位名称）：

plan格式示例；`0x486930`是下一项尚待解释的已有调用目标。先检查是否已有后续证据，避免重复分析：

```json
[
  {
    "name": "open_binary",
    "label": "open_loaded_text",
    "arguments": {
      "provider_id": "ghidra",
      "path": "C:\\projects\\san11-agent\\.rea-tools\\san11-loaded-text.pe.bin"
    }
  },
  {
    "name": "analyze_function",
    "label": "patrol_gate_dependency_486930",
    "arguments": { "procedure": "0x486930" }
  }
]
```

```powershell
python tools/rea_research_session.py --out docs/rea/new-investigation --plan .rea-tools/new-plan.json --inbox .rea-tools/new-inbox
```

不要把完整REA JSON直接塞进上下文，文件可能有数MB且text与structuredContent重复。优先取结构化结果并只显示所需部分，例如：

```python
import json
from pathlib import Path

path = Path("docs/rea/2026-10-23-budget/patrol_gate_5cc000.json")
raw = json.loads(path.read_text(encoding="utf-8"))
evidence = raw["structuredContent"]
print(evidence["evidence_id"])
result = evidence["normalized_result"]
print(result.get("pseudocode", "")[:12000])  # 仅显示片段，完整结果仍在原文件
```

部分结果只有content文本，解析方式参照会话脚本value_of。不要把客户端截断或恢复的void签名当作完整结果/真实原函数签名；要结合汇编与调用者。补充Capstone重叠解码是候选搜索，不是REA确认的指令边界。原始Evidence的authority字段也不能抹去“输入是混合载体”这一来源限制。

## 7. 已排除或不能重复当事实的线索

- **已确认反例**：`General+0x12A`从0变2后跨旬仍为2，hasActed已恢复false；不能当简单已行动布尔值。REA显示它是5个步长2数值的取值区域；“能力经验”仍只是推测。
- **已确认语义纠正**：`0x486F50`是资金读取路径，不是行動力getter；`0x4869C0`解析城市，不是军团解析器。旧证据文件名中的district_resolver不代表最终结论。
- **已确认的解释边界**：`0x49DBB0`遍历城市+0xF4的30个槽，检查对象类型与+0x14。推测是生效设施查询，类型0x29/0x2A/0x2C名称未确认；不能直接命名成建筑/科技或据此上线通用折扣。
- **未确认函数角色**：`patrol_availability_5edf20.json`实际包含上下文预算、随机阈值和自动选将，推测为AI安排流程；不是已确认的玩家UI通用门槛。`executor_candidate_5c72f0.json`也未建立巡察语义。
- **已证伪的旧选择地址**：0x1C1FF160不能可靠区分城市选择；参见execution_research，不要再次填成生产偏移。
- **历史阻塞已变化**：用户曾报告远程桌面DirectX初始化失败，但后来已进入游戏并完成实验。根因/修复方式未确认，不把旧失败当当前阻塞，也不要自动重复修改显示环境。
- **仍未定位**：一般清位函数存在，但本次跨旬触发的精确清位调用链未确认；日期递增不等于控制权恢复。

## 8. 验证、提交与更新交底

从仓库根目录开始：

```powershell
git status -sb
git log -3 --oneline
python -m pytest -q
git diff --check
```

基线测试结果为428项通过。这些是离线测试，不能替代实机验收；后续修改后数量会变化，不应为了维持数字删除/伪造测试。新环境缺pytest时可在项目虚拟环境安装requirements-dev；不需要先启动游戏才能运行测试。

增加状态字段时至少核对未知值、字节宽度/掩码、版本边界及敌方信息不泄漏；修改执行/循环时增加状态变化、结果不明、失败、共享预算和终止条件的测试。文档-only改动检查链接与差异即可，无需新增镜像实现的测试。

GitHub远端为[huahua9185/san11-agent](https://github.com/huahua9185/san11-agent)。b8f7f9a已推送到master；本文编写前工作区干净。提交/推送按当前用户请求执行，不覆写无关修改、不强推历史。游戏EXE、DLL、工具安装包、完整内存dump、存档和凭据不提交；`.rea-tools/`继续保持忽略。

后续交接时同步更新本文的基线、已完成/未完成、最后实机状态的时间、恢复点、测试结果与下一步；证据新增而不覆盖，源码/测试和研究说明保持一致。**接手的第一项建议工作是P0-1巡察资格补全；本说明本身不表示该工作已经完成。**

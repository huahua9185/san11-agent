# 战略层设计取舍报告（M5·地基）

> 本次范围：M5 的地基——战略备忘录 + 战略层调用框架，用假 LLM 后端离线跑通
> "AI 决策 -> 执行 -> 推进回合"的完整循环，**不接任何真实 LLM API，不接真实
> 游戏**。真实 LLM 接入（调用真实 API、处理真实网络/超时/重试）和真实游戏
> Execute（把 Action 变成真实键鼠输入）都不在本次范围内，留给下一个里程碑。

## 0. 和 M1~M4 的关系

M5 新增 6 个模块，全部只建立在 M2 的 `VisibleGameState` 和 M4 的
`enumerate_legal_actions()`/`Action` 类型体系之上，完全不涉及 M1 的完整
`GameState`、也不涉及 M3 的执行层（`InputBackend`/`window`/`map_projection`）
——这是有意的：M5 的目标是验证"决策链路本身能不能跑通"，不是把它接到还没
解决的内存/坐标缺口上。

| 模块 | 职责 |
|---|---|
| `san11agent/intent.py` | 高层意图的结构化类型（`DomesticFocus`/`CityDirective`/`StrategicIntent`） |
| `san11agent/strategy_memo.py` | 战略备忘录的读写（格式、原子写、备份、长度控制） |
| `san11agent/situation_summary.py` | `VisibleGameState` -> 给 LLM 看的局势摘要 |
| `san11agent/strategy_llm.py` | `StrategyLLM` 抽象 + `FakeStrategyLLM` + 提示词组织 + 输出解析 |
| `san11agent/domestic_tactics.py` | 战术执行层（内政）：意图 -> 合法动作 |
| `san11agent/strategy_loop.py` | 主循环：串起以上全部 + 假状态源 + 假执行后端 |

## 1. 战略备忘录：`strategy_memo.py`

### 1.1 格式

Markdown 正文 + 一段极简的 `---` 包裹元数据头（`schema_version`/`turn`/
`checksum`，纯 `key: value`，手写解析，不引入 PyYAML——项目到目前为止运行时
零第三方依赖，见 README，不想为这一个文件破例）：

```
---
schema_version: 1
turn: 12
checksum: 3f9a1b2c4d5e6f70
---
## 当前目标
...

## 势力判断
...

## 未来规划
...
```

正文完全是 LLM 自己组织的自由 Markdown（人类和 LLM 都好读好改），元数据头
只服务于程序校验，LLM 不需要关心它——写回时由 `write_memo()` 自动生成。

### 1.2 避免损坏

- **原子写**：先写到同目录 `.tmp` 临时文件，再 `Path.replace()`
  （`os.replace()`）覆盖目标路径——POSIX 和 Windows 上都是原子操作，中途
  崩溃不会留下"写了一半"的文件。
- **保留上一版备份**：覆盖前把当前文件复制成 `<path>.bak`（只保留一份，不是
  完整版本历史，见第7节需要你确认的取舍）。
- **校验和**：正文的 sha256 前16位存进元数据头；读取时重新计算，对不上就
  说明文件在写入流程之外被改动/损坏，抛 `StrategyMemoCorruptedError`，不会
  把可能损坏的内容悄悄喂给 LLM。`strategy_loop.py` 捕获这个错误后自动尝试
  `restore_backup()` 回退到上一版；连备份都没有时才让异常继续往上抛（这已经
  不是"LLM 说了不合规范的话"能解决的问题，需要人工介入）。

### 1.3 长度控制

`write_memo()` 接受 `max_body_chars`（默认 6000 字符），正文超过预算直接
**拒绝写入**（`StrategyMemoTooLongError`），旧文件保持不变——不做自动截断
（可能从句子中间切断丢失语义）、不做自动摘要（需要额外一次 LLM 调用，这次
完全离线不调用任何真实模型）。这意味着"控制长度"这件事目前完全依赖 prompt
里告诉 LLM 预算（见第4节），以及 LLM 本身愿不愿意遵守。**这是需要你确认的
取舍**，见第7节。

## 2. 局势摘要：`situation_summary.py`

**核心约束，和 M4 LegalActions 完全相同的理由**：`summarize_situation()`
只能建立在 `VisibleGameState` 之上，不能碰完整 `GameState`——如果 LLM 决策
时用到了人类玩家在界面上看不到的信息，"AI 和人类站在同样信息基础上决策"这
个实验前提就被破坏了。跟 M4 一样，这条约束由架构守卫测试
（`tests/test_situation_summary.py`）用两种方式守住：模块不绑定完整
`GameState` 类型名、AST 检查模块只 `import` 了 `visible_state`/`legal_actions`、
`summarize_situation()` 的 `state` 参数类型标注确实是 `VisibleGameState`。

摘要内容：己方城池详情（兵力/钱粮/治安/内政空位）、可见的非己方城池（摘要
级别，未探明的只显示归属）、可指派的己方武将（体力>0 且本回合未指派，供
LLM 判断"谁能镇守/行动"）、己方总钱粮、势力总数。"武将当前在哪座城"复用了
`legal_actions.default_is_general_in_city()` 同一条未经验证的假设
（`General.location == City.index`），没有重新发明一份不一致的猜测。

摘要拆成"结构化数据"（`SituationSummary` dataclass）和"渲染成文本"
（`render_situation_text()`）两步，方便分别测试，也方便未来换一种展示格式
而不用改数据提取逻辑。

## 3. 高层意图类型体系：`intent.py`

不是自由文本。`StrategicIntent` 是一个 `frozen` dataclass：

| 字段 | 含义 | 是否被战术层消费 |
|---|---|---|
| `default_focus: DomesticFocus` | 内政重心（均衡/经济/农业/军事/治安5种封闭枚举） | 是 |
| `city_directives: tuple[CityDirective, ...]` | 按城池覆盖默认重心 + 记录镇守人选 | `focus` 部分是；`garrison_general_index` 只记录 |
| `target_faction_index: int \| None` | 意图攻打的势力 | 否，仅记录 |
| `expansion_notes: str` | 扩张方向 | 否，仅记录 |
| `rationale: str` | 决策理由，供人工复核 | 否，纯可观测性 |

`target_faction_index`/`expansion_notes` 对应规格里"攻打哪个势力/往哪个
方向扩张"这两项高层意图，本次**只做了类型占位，不驱动任何动作**——原因是
战术执行层这次只覆盖内政（第5节），没有战斗/出征层能消费"打谁"这种信息。
`garrison_general_index` 同理：没有出征动作的情况下，"谁镇守"没有可执行的
含义，也只是记录。这是有意的占位，不是遗漏，方便未来加战斗执行层时不用
重新设计 Intent 的顶层结构，但**这几个字段目前实际上是"写了也没用"，需要你
确认这个占位策略是否认可**，见第7节。

## 4. LLM 战略层接口：`strategy_llm.py`

`StrategyLLM.decide(prompt) -> str` 返回**原始字符串**，不是直接返回
`StrategicIntent`——这是刻意贴近真实 LLM 的调用形态：真实 LLM 返回的是文本
（哪怕要求了 JSON 格式），可能格式错、可能漏字段、可能夹带解释性废话。把
"调用 LLM"和"解析 LLM 输出"拆成 `decide()` + `parse_llm_response()` 两步，
"LLM 返回非法内容怎么办"这个问题就能独立处理、独立测试。

**输出格式选了 JSON**（不是自由文本 + 正则提取）：结构化意图本身有嵌套字段
（`city_directives` 是列表），JSON 是最不容易产生歧义的格式，也是目前主流
LLM API 原生支持"按 schema 输出"的格式（tool use / JSON mode）。提示词
（`build_strategy_prompt()`）三段拼接：当前局势摘要 + 上一次的战略备忘录 +
输出格式说明（包含合法的 `default_focus` 枚举值列表、备忘录字符预算）。

**`FakeStrategyLLM`**：完全离线，从不联网。支持两种驱动方式——固定顺序的
字符串列表（预设脚本用尽会抛 `IndexError`，不是安静地循环或返回空）、或者
一个 `Callable[[StrategyPrompt], str]`（用于"根据传入的 prompt 内容动态决定
返回什么"这类测试场景，比如模拟"连续几次非法之后突然合法"）。另外提供
`format_strategy_response()` 反向工具函数，把结构化字段拼成合法 JSON 字符串，
避免测试代码里出现容易打错字的 JSON 字面量。

`parse_llm_response()` 的校验是 fail closed 的——JSON 解析失败、顶层不是
对象、缺 `memo`/`intent`、`default_focus`/`city_directives[].focus` 不在
5 个合法枚举值里、`city_index`/`garrison_general_index`/`target_faction_index`
类型不是整数，全部抛 `StrategyParseError` 并带上具体是哪个字段出的问题。
**这里只校验结构/类型/枚举取值，不检查备忘录长度**——长度预算是
`strategy_memo.write_memo()` 的职责（单一事实来源），调用方要分别处理两类
失败。

## 5. 战术执行层（内政）：`domestic_tactics.py`

**核心约束，是 M4"AI 不会输出非法指令"这条保证在战术层的延续**：
`select_domestic_actions()` 返回的每个 `TacticalDecision.action`，必须是
传入的 `legal_actions` 参数里的**同一个对象**（不是"字段恰好相等的另一个
对象"）。实现上天然满足——所有候选动作全程直接来自对 `legal_actions` 的
分组，代码里从未构造过一个新的 `Action` 实例。`tests/test_domestic_tactics.py`
用身份检查（`is`，不是结构相等的 `==`）守住这一点，并且用一条防御性测试
（手工构造"同一武将出现在两座城"的违规输入，用 `dataclasses.replace()` 篡改
一个真实合法动作的 `city_index`）验证战术层在遇到违反自身假设的数据时
`raise TacticalError`，而不是猜一个动作出来。

实现方式是一张固定的规则表，不是搜索算法（规格里"用规则或搜索算法"二选一，
本次选规则，理由见第7节）：先按 `general_index` 分组，再查
`intent.directive_for(city_index).focus` 决定这座城的重心，按重心对应的
`ActionKind` 优先级顺序（`_FOCUS_ACTION_PRIORITY`），选第一个这位武将实际
拥有的匹配动作；`build_facility` 命中时进一步按重心偏好选子类型
（经济→市场，农业→农田，军事→兵营/马厩，治安→弩楼）；全部优先级都没有
命中时保底选第一条（正常情况下不可达，因为 5 种重心的优先级表都覆盖了全部
8 种 `ActionKind`，但仍然写了防御性分支并用 `monkeypatch` 验证过）。

**可观测性**：每个 `TacticalDecision` 都带 `reason` 字段，同时说明"命中了
哪条优先级规则"和这个动作本身的人类可读描述（复用 M4 的 `describe_action()`）
——项目明确要求这一层"要能看清意图怎么变成动作"，`reason` 不是可选项。

## 6. 主循环：`strategy_loop.py`

串起"读状态 -> (每N回合)调LLM更新备忘录/意图 -> 战术层出动作 -> 执行 ->
推进回合"。两处关键抽象，都只有假实现（复用 M3 `FakeInputBackend` 的思路，
只记录调用/只推进一个计数器，不做真实操作）：

- `GameStateSource`（`read()` + `advance_turn()`）：真实实现需要 M1 内存
  读取 + M2 过滤器 + 一个目前完全不存在的"结束内政"Execute 动作。
  `FakeGameStateSource` 包一份可变的 `VisibleGameState`，`advance_turn()`
  只把 `current_xun` 加一，**不模拟任何游戏经济副作用**（执行动作后金钱/粮草
  不会真的变化）——这次的验收目标是"循环能连续推进若干回合"，不是"模拟
  完整游戏经济"，见第7节范围说明。
- `ActionExecutor`（`execute(action)`）：Execute 这一环完全没有真实实现
  （跟 M3 `select_city` 之外的一切内政动作 Execute 一样），`FakeActionExecutor`
  只记录调用。

**调用节奏**：`StrategyLoopConfig.llm_call_interval` 控制"每 N 回合调用一次"，
用 `current_xun % N == 0` 判断，外加"从来没有成功调用过"时强制调用一次
（否则如果起始回合数和 N 不对齐，可能永远轮不到）。

**LLM 返回非法/无法解析内容时的处理策略**（规格明确要求的一项）：

1. `StrategyParseError`（格式/类型/枚举不对）：本回合保留上一轮的
   `StrategicIntent` 不变，记 `strategy.llm_response_invalid` 日志，失败计数
   +1，循环继续（不是整体停摆）。
2. `StrategyMemoTooLongError`（格式对，正文超预算）：新 `intent` 仍然采用
   （intent 解析已经成功，跟备忘录能否落盘是两件独立的事），但备忘录文件
   保持旧内容不变，记 `strategy.memo_write_rejected` 日志。
3. `StrategyMemoCorruptedError`（文件被外部改动/损坏）：自动尝试
   `restore_backup()`；连备份都没有时不再假装恢复成功，让
   `StrategyLoopError` 继续往上抛，需要人工介入。
4. **连续失败达到 `max_consecutive_llm_failures`（默认3）次**：抛
   `StrategyLoopError` 停止整个循环，而不是无限拿着一个可能早就过期的旧
   intent 静默空转到底。**这是一个需要你确认的取舍**，见第7节。

## 7. 需要你确认的设计取舍

1. **备忘录长度超预算时"拒绝写入"，而不是"自动截断"或"额外调用LLM做摘要"**
   （见第1.3节）：拒绝写入最安全（不会截断出语义错误的内容），但如果真实
   LLM 持续不遵守 prompt 里的字符预算，备忘录会一直卡在旧版本，长期看长线
   一致性会退化。如果你更倾向于自动截断（简单但可能语义损坏）或者用一次
   低成本的 LLM 调用做摘要（更好但增加调用量和复杂度，且这次完全不能验证，
   因为不接真实 LLM），告诉我，`write_memo()` 那一处逻辑不难改。
2. **备份只保留一份（`<path>.bak`），不是完整版本历史**：如果你想要更完整
   的历史（比如按 turn 编号存多份、或者接入 git 做版本控制），`write_memo()`
   需要相应扩展，这次先按需求原文"保留上一版备份"（单数）实现了最小版本。
3. **`target_faction_index`/`expansion_notes`/`garrison_general_index` 目前
   只被记录、不驱动任何动作**（见第3节）：这是"没有战斗/出征执行层，这些
   字段暂时没有可执行含义"的必然结果，不是遗漏。如果你希望这次就做一些
   哪怕很粗糙的消费逻辑（比如"有 target_faction_index 时，外交/计略动作
   优先针对该势力"），可以加，但这会让战术层管的范围超出"只做内政"，需要
   你确认要不要现在就做。
4. **连续 LLM 失败达到阈值后整个循环停止（`StrategyLoopError`），而不是无限
   用旧 intent 继续跑**（见第6节）：这是偏保守的默认——"哪怕 intent 过期也
   继续跑"和"过期太久就该停下报警"是两种合理的产品取向，如果你更倾向于
   前者，把 `max_consecutive_llm_failures` 设成 `None`（需要我加一处判断）
   或调大即可。
5. **战术层用固定规则表，不是搜索算法**（规格"用规则或搜索算法"二选一）：
   本次内政动作的选择空间小（几种动作类型 × 几种重心），规则表足够表达
   "按重心选类型"这个逻辑，没有必要引入搜索。如果未来战术层要处理更复杂的
   分配问题（比如"多位武将、多座城池、要在总资源约束下整体最优分配"），
   规则表这种"逐武将独立决定"的做法会显得粗糙，需要换成真正的分配算法，
   这次没有做，因为当前场景（单武将单城独立选一个动作）还不需要。
6. **`FakeGameStateSource` 不模拟游戏经济副作用**（动作执行后金钱/粮草不变、
   武将体力不消耗）：这次验收目标是"循环能连续推进若干回合、调用节奏对、
   容错策略对"，不是"模拟完整游戏经济"。如果你想要更真实的空跑（比如验证
   "连续执行 levy_gold 之后金钱真的累积、体力真的耗尽后这位武将不再被枚举"），
   需要在 `FakeGameStateSource`/`FakeActionExecutor` 之间加一层状态联动，
   这次没有做，见提交报告范围说明。

## 8. 测试覆盖

全部离线，不真的等待、不调用任何真实 API、不依赖真实游戏进程：

- `tests/test_strategy_memo.py`：格式往返、原子写、备份创建、长度拒绝、
  校验和损坏检测、多种格式错误、备份恢复（含"没有备份"的报错路径）。
- `tests/test_situation_summary.py`：架构守卫（同 M4 的两种检查方式）+
  摘要内容正确性（己方/非己方城池区分、总量统计、武将位置启发式、
  空摘要的渲染）。
- `tests/test_strategy_llm.py`：提示词组织、`FakeStrategyLLM` 两种驱动方式
  + 调用记录、`format_strategy_response`/`parse_llm_response` 往返、以及
  逐字段的解析容错（非 JSON/非对象/缺字段/类型错/枚举值非法，每种都单独
  测一遍，并检查错误信息点名了具体字段）。
- `tests/test_domestic_tactics.py`：核心约束（身份检查"动作确实来自
  legal_actions"）、5 种重心 -> 动作类型的优先级映射、`city_directives`
  覆盖 `default_focus`、`build_facility` 子类型偏好、"一武将多城"防御性
  报错、优先级表未命中时的保底分支（用 `monkeypatch` 显式制造该条件）。
- `tests/test_strategy_loop.py`：连续 6 回合空跑验证调用节奏
  （`llm_called` 序列）、每回合都产出并执行动作、备忘录落盘、`ActionLog`
  同时记录战术/战略两类条目；LLM 非法响应不崩溃且保留旧 intent、连续失败
  达阈值后停止、失败后又成功会重置失败计数；备忘录超长被拒绝但 intent 仍
  采用；备忘录损坏时自动从备份恢复、没有备份时报错停止。

全部 264 个测试（M1~M4 原有 197 个 + M5 新增 67 个）用
`C:\Users\hhhh\AppData\Local\Programs\Python\Python312\python.exe -m pytest`
跑过，全部通过。

## 9. 哪些部分只能靠设计保证，无法在本次离线测试里验证

- **提示词能不能真的让一个真实 LLM 稳定输出合法 JSON、并遵守字符预算**：
  `FakeStrategyLLM` 只能验证"如果 LLM 输出长这样，解析/容错逻辑对不对"，
  没法验证"真实 LLM 实际会输出成什么样"。接入真实 LLM 后大概率需要根据
  实测调整 `_INSTRUCTIONS_TEMPLATE` 的措辞、可能需要加 few-shot 示例。
- **`llm_call_interval` 这个"每N回合"节奏在真实多小时对局里是否合适**：
  数值本身（默认5）是随手定的占位，没有依据——真实游戏一局 100+ 回合，
  这个值应该多大取决于战略决策的时效性要求和真实 LLM 的调用成本，需要你
  结合实际调用预算确认，见 README 里项目规格原文提到的"调用量会失控"。
- **`FakeGameStateSource`/`FakeActionExecutor` 空跑出来的"连续若干回合"，
  不代表真实游戏里 Execute 真的能把动作点出来**：M3 的 Execute 现在只做到
  了"点选城池"，内政动作（建设/征兵/训练/征收/外交/计略）对应的具体键鼠
  操作序列完全没有实现，这次的主循环只验证了"决策链路（LLM->意图->战术->
  ActionLog）能不能自动转起来"，不是"整条链路能不能在真实游戏里跑通"。

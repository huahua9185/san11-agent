# LegalActions 设计取舍报告（M4·上半场）

> 本次范围：只做 M4 里的 LegalActions（内政阶段动作枚举），不做 Execute（把
> Action 转换成真实键鼠输入）——原因和 M3 一样，真实游戏当前无法运行（用户
> 机器锁屏、人在远程），Execute 需要真的操作游戏窗口验证，等游戏能跑再做。
> 这次也没有开始 M5。

## 0. 和 M1/M2/M3 的关系

LegalActions（`san11agent/legal_actions.py`）的输入是 M2 的
`VisibleGameState`，不是 M1 的完整 `GameState`——这是项目规格明确要求的
实验前提：AI 只能用人类玩家在界面上能看到的信息判断自己能做什么，不能
偷看只有内存里才有、界面上不显示的数据。这一点在代码里通过两处强制：

1. `legal_actions.py` 完全不 `import` `game_state.py` 里的
   `GameState`/`General`/`City`/`Troop`/`Faction`/`GlobalState`。
2. 判断"这位武将/这座城信息是否充分"时用 `isinstance(x, VisibleGeneralFull)`
   / `isinstance(x, VisibleCityDetail)`，而不是假设字段存在——按 M2 的白名单
   设计，看不到的字段在 Visible* 对象上根本不存在。

`tests/test_legal_actions.py` 里专门有一组"架构守卫"测试守住这一点：
检查模块不绑定完整 GameState 的类型名、检查 `enumerate_legal_actions()` 的
`state` 参数类型标注确实是 `VisibleGameState`、以及一个防御性测试——即便
某个己方武将因为上游 bug 只带 Public 档（没有体力字段），也必须被
`isinstance()` 拒绝，不会尝试访问不存在的字段或者悄悄当作"体力无限"处理。

## 1. Action 类型体系

没有用字符串或者一个大 dict 表示动作，而是每种动作一个 `frozen`
dataclass（`kw_only=True`），共 8 种（`ActionKind`），共享同一个
`ActionBase`（`general_index`/`city_index`/`unverified_constraints`）：

| ActionKind | dataclass | 额外参数 |
|---|---|---|
| `build_facility` | `BuildFacilityAction` | `facility_type: str`, `target_tile: tuple[int,int] \| None` |
| `recruit_troops` | `RecruitTroopsAction` | 无 |
| `train_troops` | `TrainTroopsAction` | 无 |
| `security_patrol` | `SecurityPatrolAction` | 无 |
| `levy_gold` | `LevyGoldAction` | 无 |
| `levy_food` | `LevyFoodAction` | 无 |
| `diplomacy` | `DiplomacyAction` | `target_faction_index: int`, `diplomacy_type: str` |
| `stratagem` | `StratagemAction` | `target_city_index: int`, `stratagem_type: str` |

`facility_type`/`diplomacy_type`/`stratagem_type` 是字符串而不是 Python
`Enum`，因为这些具体子类型本身是不确定的游戏规则数据（见第2节），存进配置
表比硬编码进代码更容易在你确认真实规则后修改，不需要改代码。

每个 Action 实例都带 `unverified_constraints: tuple[str, ...]`——记录这个
动作在枚举时，哪些约束因为规则表里数值是 `unknown` 而没有真正检查（比如
`"gold_cost"`）。这不代表动作不合法，只代表"这一项没有被验证过"，是可观测性
设计的一部分：下游（未来的 LLM prompt 或 Execute）可以看到"这条动作的资源
消耗没有被验证"，而不是被蒙在鼓里。`BuildFacilityAction` 还固定带一条
`"target_tile_precision"`，原因见第3节。

## 2. 规则表：`rules/domestic_actions_pk_1.1_cn.json`

跟 `offsets/`、`ui_layout/` 是同一种做法——新增了一个顶层目录 `rules/`
（`rules/schema.json` 是格式定义，`rules/domestic_actions_pk_1.1_cn.json`
是实际数据），加载器 `san11agent/domestic_rules.py` 风格上刻意模仿
`offsets.py`（`RuleValue`/`ActionRuleSpec`/`DomesticRulesConfig`，字段找不到
依据时 `unknown: true`）。

**但 `unknown` 的语义和 `offsets.py` 不同，这是本次一个需要你留意的设计
决定**：`offsets.py` 的 `FieldSpec.require_known()` 在字段 unknown 时直接
抛异常拒绝读取（因为那是内存地址，读错了可能读到垃圾数据甚至游戏崩溃，
"拒绝"是安全的默认行为）。但 `rules/*.json` 里的 unknown 主要不是"内存地址
没找到"，而是"游戏规则数值本身没有实机验证途径"（游戏跑不起来，我也没有
权威资料）——如果沿用"unknown 就拒绝"的语义，规则表几乎所有数值现在都是
unknown，LegalActions 会拒绝枚举几乎所有动作，整个里程碑就没有产出。所以
这里选择了相反的默认：**unknown 的资源阈值不拦截，只记录进
`unverified_constraints`**。这是一个明确的取舍，不是延续 M1/M2/M3 的既有
原则，特此在这里说明，如果你认为应该反过来（unknown 就应该拒绝，宁可枚举
不出动作也不要产出未经验证的动作），请告诉我，改起来不难（`_check_resource()`
一处逻辑）。

规则表目前对全部 8 种动作、全部资源字段（体力/金/粮）都标 `unknown`——本项目
没有找到、也没有能力验证这些具体数值，没有编数字进去。结构性字段（是否需要
己方城池、是否需要设施建设位、每种动作有哪些子类型）是明确给定的，因为这些
更接近"这个动作范畴长什么样"这类框架性问题，不是"具体消耗多少"这类需要实测
的数值。

## 3. 已经能靠现有数据模型强制的约束 vs. 做不到的约束

**能做的**（`enumerate_legal_actions()` 实际强制执行）：

- 武将本回合是否已被指派：`assigned_general_indices` 参数排除（见第4节，
  这个状态不来自内存）。
- 武将体力：`stamina > 0` 是硬性门槛（没体力肯定不能行动，这条不依赖规则表）；
  具体每种动作的体力消耗阈值来自规则表，未知时不拦。
- 金钱/粮草是否够：同上，未知时不拦。
- 设施建设位是否可用：`development_land_count - developed_land_count > 0`。
- 城池是否己方：`city.faction_id == player_faction_id`。
- 计略目标城池归属：只有 `faction_id` 明确已知的非己方城池才会被列为计略
  目标（fail-closed：归属未知的城池不会被当作合法目标，也不会被当作己方）。

**做不到、明确跳过、不猜测的**（详见模块 docstring）：

- **武将适性/特技**：`GameState` 数据模型里完全没有"兵科适性"这类字段（M1
  没有解析过），`special_skill_id` 虽然存在，但项目里任何地方都没有定义每个
  id 对应什么效果，无法用来做门槛判断。这不是这次没做完，是数据模型目前
  完全不支持，需要先在 M1 层面补上这类字段才有可能实现。
- **外交目标是否"已接触"**：没有对应字段能判断"是否已知晓/见过某个势力"，
  `enumerate_legal_actions()` 会对所有非己方势力都枚举外交动作，可能过度
  宽松（把理论上还没有建立联系的势力也列进去）。
- **计略目标的可达性**（是否要求接壤/在一定范围内）：同样没有对应字段，
  目前对所有归属已知的非己方城池一视同仁。

## 4. 需要你确认的设计取舍（本次没有替你决定，按你的要求列在这里）

1. **"武将已指派"状态的来源**：这不是从游戏内存读出来的字段，而是"这个
   回合里 agent 自己已经发过的指令"，所以设计成 `enumerate_legal_actions()`
   的一个显式参数 `assigned_general_indices: frozenset[int]`，要求未来的
   对局循环自己维护（类似 M2 里 `player_faction_id` 必须显式传入的理由）。
   如果游戏内存里其实有一个"该武将本回合是否已行动"的标志位（可能藏在
   `General.location` 或某个还没识别的字段里），那从内存读会比 agent 自己
   记账更可靠——但目前没有证据证明存在这样的字段，需要你确认要不要往这个
   方向查。
2. **"武将是否在这座城"的判定**（`default_is_general_in_city()`）：默认假设
   `General.location == city.index`——根据 offsets 里 `location` 字段现有
   注释（">87 表示在部队中，减87=部队ID"）推出的猜测：暗示 ≤87 的取值可能
   是别的编码，游戏共 42 座城，0~41 都落在这个范围内，但资料里**没有**明确
   证实"不在部队中时 location 就等于所在城池 index"。如果这个假设错了，
   `enumerate_legal_actions()` 支持传入自定义的 `is_general_in_city` 谓词
   覆盖它，但默认值需要你确认或纠正。
3. **"治安"和"巡查"合并成一个动作类型**（`security_patrol`）：本表没有独立
   证据证明这是游戏里两个不同的指令还是同一指令的两种叫法，按"同一指令"
   处理。如果实际是两个独立指令，需要拆开，规则表和 `ActionKind`/dataclass
   都要相应调整。
4. **`levy_gold`/`levy_food` 要不要合并成一个"征收"指令**：目前按两个独立
   动作类型建模（分别征金/征粮），如果实际游戏里是一次性指令（一次征收同时
   拿到金和粮，不能分开选），需要合并。
5. **`build_facility` 的五种设施类型**（农田/市场/兵营/马厩/弩楼）是你在
   需求里直接列出的，本表没有独立验证这是不是该版本游戏里完整、准确的
   设施清单——完整版可能还有其它设施，也可能个别名称对不上，需要你核对。
6. **`BuildFacilityAction.target_tile` 的精度问题**：`GameState.City` 目前
   只解析了**一组** `domestic_land_x`/`domestic_land_y` 坐标（M1 阶段没有
   把"开发用地网格"解析成完整的空位列表，只有 `development_land_count`/
   `developed_land_count` 这两个计数），所以 LegalActions 没办法说清楚
   "具体建在哪一格空位"，只能把这组唯一的坐标原样带出来，同时在
   `unverified_constraints` 里固定标 `"target_tile_precision"`。如果开发
   用地实际上是多格网格（很可能是），需要先在 M1 层面把完整的格子列表解析
   出来，LegalActions 才能精确枚举"建在哪一格"。
7. **`rules/*.json` 里 `unknown` 的语义选择"不拦截、只标记"**（见第2节）：
   这是和 `offsets.py`"unknown 就拒绝读取"相反的默认行为，出于"不然
   LegalActions 现在完全产不出动作"的实用考虑，但如果你更看重"宁可枚举
   不全，也不要输出未经验证资源消耗的动作"，这个默认可以改。
8. **外交"已接触"、计略"可达性"未建模**（见第3节）：目前的行为偏宽松
   （所有非己方势力/归属已知的非己方城池都会被枚举），如果这会导致产出
   明显不合理的动作数量，可以考虑先收紧成"只保留有共同边境的目标"这类
   更保守的默认，用 `city.adjacent_cities` 做粗略邻接判断——这次没有做，
   因为"外交/计略是否要求接壤"本身也是不确定的规则，不想在两层不确定性上
   叠加猜测。

## 5. 测试覆盖

`tests/test_domestic_rules.py`：规则表加载器（生产文件 + 测试 fixture 都要
能正常加载；生产文件里全部资源数值确实诚实标了 unknown；各类格式错误正确
拒绝）。

`tests/test_legal_actions.py`（44 个测试）：

- 架构守卫：模块不绑定完整 GameState 类型、`state` 参数类型标注确实是
  `VisibleGameState`、防御性 isinstance 检查。
- 结构性约束逐条覆盖：已指派武将排除、零体力武将排除、不在己方城池的武将
  排除、非己方武将（哪怕 index 対上也不行）排除、设施建设位满时不产出
  `BuildFacilityAction`、计略只能打归属已知的非己方城池、外交不能对自己。
- 资源阈值：用独立构造的最小规则表验证"已知阈值确实会拦截不满足的动作"、
  "未知阈值不拦截但会被记录进 `unverified_constraints`"两条路径都对。
- `is_general_in_city` 默认实现的行为 + 自定义谓词可以覆盖默认值。
- `describe_action()` 可观测性辅助函数的基本输出格式。

全部离线，用手工构造的 `VisibleGameState`/`DomesticRulesConfig`，不依赖
真实游戏进程、不依赖 M1 的 memory/perception 链路。

## 6. 和 Execute 的边界

`legal_actions.py` 只产出结构化 `Action` 对象，不做任何键鼠模拟、不碰
`InputBackend`/`window`/`map_projection`。把某个 `Action` 真正变成游戏里的
操作——比如 `BuildFacilityAction` 最终要点开哪个菜单、`DiplomacyAction`
的外交界面长什么样——是 Execute 的范围，等真实游戏能跑起来再做，这次完全
没有涉及。

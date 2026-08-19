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

## 7. 2026-08-19 重大发现：游戏安装目录自带官方手册，一次性解决了大半个验证清单阶段7

在实机核对 `security_patrol`（巡察）的资源消耗时，用户在游戏内「用語事典」
（术语词典）里查到「訓練」的说明写着"必要行動力：20"，跟本项目一直假设的
"武将个人体力（stamina）"是完全不同的资源概念。尝试提取「用語事典」本身
（游戏内建、按拼音索引的完整词典）时，发现它存在游戏私有压缩格式
`media/msg/S11MSG0X.s11` 文件里（"LS11"文件头，非标准 zlib，直接破解需要
真正的反汇编逆向，本次没有做）。但游戏安装目录下还有一份 **`San11WPK.pdf`
（74MB，官方《遊戲說明書》）**，用 `pdftotext`（Poppler，机器上已有）
直接提取出约120KB的文字层，里面有一份结构化的"指令一覽"章节，逐条列出
每种据点指令的资金/行動力消耗、执行武将人数上限、效果说明——这是**官方
权威数据源**，不是实机测量也不是猜测，跟本项目"没依据就标 unknown"的
原则完全不冲突（手册文本本身就是依据）。

### 7.1 核心发现：真正的门槛资源是"行動力"，不是武将个人体力

手册"行動力（最大255）實行指令時需要。於每回合恢復。實行指令的話便會
減少。"——这是一个**城池级**资源池（不是武将个人属性，也不是势力共享
的单一数值：同一时刻襄陽读到54、江夏读到34，见 docs/offset_research.md
7.4节的实机记录），每回合恢复，随城池发展程度而不同上限。

手册逐条列出的全部据点指令（都市/軍事/人材/外交/計略）**没有一条提到
"武将体力"这个概念**，一致只提"行動力"。这跟 `security_patrol` 的实机
验证结果吻合（两次执行，6位武将 stamina 全部保持100不变，见
docs/verification_checklist.md 7.4节）——说明 `rules/domestic_actions_pk_1.1_cn.json`
原本假设的 `min_general_stamina` 门槛，对这批内政指令而言基本不成立，
已在 rules 文件里把全部6种已建模动作的 `min_general_stamina` 改成
`0`（已知），新增 `action_points_cost` 字段承载真正的门槛资源。

**这个字段目前还没法真正拿来做约束检查**：`city.action_points`（offsets
文件里新增的占位字段）本身仍未定位到内存偏移（2026-08-19 扫描过
`City[29]`/`City[27]` 结构体全部字节找当前显示值，均为0个候选，见
docs/offset_research.md 7.4节），所以 `enumerate_legal_actions()` 目前
还是拿不到"这座城当前还剩多少行動力"这个运行时数值，只能在规则表层面
记录"这个动作需要消耗多少行動力"，还做不到"行動力不够就不产出这个
Action"这一步约束。`legal_actions.py` 里 `general.stamina > 0` 那条硬性
门槛暂时保留未动——这是概念上更保守的一条独立假设（有没有一般性意义
上的"精疲力竭不能行动"机制，跟这里讨论的"这个具体指令消耗行動力不消耗
体力"不是同一个问题），没有证据证明它错，本次没有改。

### 7.2 新发现的前置条件：部分都市/軍事指令需要先建成对应设施

- **徵兵需要「兵營」**：手册原文"雇用士兵。需要有內政設施「兵營」。1回合
  中只能實行與兵營數相同的徵兵"。跟用户实机观察吻合（襄陽「設施數 0/18」
  时「徵兵」在都市菜单里灰色不可点，见 docs/verification_checklist.md
  7.4节）。
- **訓練跟「軍事府」的关系有矛盾，如实记录**：手册说建有「軍事府」的
  都市"其所需行動力將減半"（暗示没建也能执行、只是更贵），但用户实机
  遇到一座未建「軍事府」的城池「訓練」完全点不动。这个矛盾没有强行
  调和，写进了 `rules/domestic_actions_pk_1.1_cn.json` 的 `train_troops.
  action_points_cost.note` 里，可能是那座城当时还有其它未满足的前置
  条件，需要之后专门复核。
- 这类"需要先建成某设施"的前置条件，`enumerate_legal_actions()` 完全
  没有建模——`City` struct 目前没有解析"这座城已经建了哪些设施"这份
  清单（`city.development_land_count`/`developed_land_count` 只有总数，
  没有明细），是一个需要专门补的数据模型缺口。

### 7.3 顺带解决的历史遗留问题

- **`break_alliance` 的正确字形是「摒棄」，不是「破棄」**（2026-08-18
  截图字形辨认时留的存疑，见该字段旧 note），手册原文明确写"摒棄同盟"。
- **验证清单 7.1~7.8（除 `levy_gold`/`levy_food` 已删除）基本已用手册
  数据解决**：`build_facility`（顶层 action_points_cost=20、
  min_general_stamina=0、food_cost=0，各设施 gold_cost 此前已实机确认）、
  `recruit_troops`（gold=300/action_points=20/food=0，外加兵營前置条件）、
  `train_troops`（gold=0/action_points=20/food=0）、`security_patrol`
  （已实机验证，手册数值完全吻合，双重印证）、`diplomacy`（顶层
  action_points=30，7个子类型里4个有固定/门槛 gold_cost，3个是"出价越高
  成功率越高"的可变值，故意不设固定数字）、`stratagem`（顶层
  gold=200/action_points=30，3个子类型一致）。`levy_gold`/`levy_food`
  已在 2026-08-18 确认游戏里根本不存在，不适用。

### 7.4 数据来源的可信度定位

这些数值来自"官方权威文档"，跟"实机操作+内存/界面读数交叉核对"是两种
不同性质的证据——手册可能存在语言本地化误差、版本差异（游戏更新过但
手册没同步）等风险，不是 100% 等同于"逐条实机验证过"。`rules` 文件里
每个字段的 `source` 如实标注了"游戏内建手册"这个来源，`confidence`
定为 `high`（官方一手资料，不是社区整理或猜测），但**没有**把
`meta.verified` 整体设成 `true`——那需要更系统性的交叉核对（比如
挑几个手册数值再做一次实机核对），这次没有做到那个程度。

### 7.5 继续挖手册：武将五维属性与指令成果的对应关系（供将来的战术层参考）

手册"能力"章节明确给出了武将「統率／武力／智力／政治／魅力」五维基础
属性各自影响哪些指令的成果，原文摘录（两处出现，内容一致）：

| 属性 | 影响的指令/效果 |
|---|---|
| 統率 | `巡察` 的成果、部队防御力 |
| 武力 | `訓練` 的成果、部队攻击力、单挑攻击力 |
| 智力 | `生產兵裝`、全部 `計略`、部队指令「偽報」「擾亂」「伏兵」「內訌」「妖術」「落雷」、舌战成果，以及部队智力 |
| 政治 | `開發`、「吸收合併」、`外交`（「降伏勸告」除外）、「商人」、「探索人材」的成果，以及部队建设力 |
| 魅力 | 「降伏勸告」、`徵兵`、「登庸武將」的成果 |

**目前项目里的应用现状**：`domestic_tactics.py` 的 `select_domestic_actions()`
现在是"按重心（economy/agriculture/military/security/balanced）选一张
固定的 `ActionKind` 优先级表"，选中动作后**不会**按"这位武将哪个属性
更适合这个指令"去挑执行人选——这张表提供了未来做这个优化的具体依据
（比如巡察应该优先派"統率"高的武将、徵兵应该优先派"魅力"高的武将），
但这次没有改 `domestic_tactics.py` 的选人逻辑，只记录信息来源，是否要
实现属于后续的功能改进，不在本次范围内。

### 7.6 兵種適性 / 特技：确认是真实机制，但仍缺内存/含义数据

- **兵種適性**（troop type aptitude）：手册确认这是武将对"各兵科"的适性
  评级，S＞A＞B＞C 四档，"影響到率領特定兵科時的部隊的能力，或是可使用
  的戰法的種類"。`docs/legal_actions_research.md` 第0节/第4节之前提到的
  "武将适性/特技对动作合法性的限制——GameState 数据模型完全没有解析"
  这条缺口，现在确认了这个机制**在游戏设计上确实存在**（不是本项目
  凭空假设的概念），但内存偏移仍然完全没有定位，`General` 结构体里也
  没有对应字段，这次没有进一步深挖。
- **特技**（special skill）：手册"基本上，1名武將只有1項「特技」（也有
  沒有特技的武將）"——跟 offsets 文件里 `general.special_skill_id`
  （-1=无特技）这个已知字段的语义完全吻合，进一步确认这个字段的推测
  没有问题。但每个具体 id 对应哪个特技、特技各自的效果，手册里似乎有
  独立的"全特技的說明"列表（原文引用页码 P.32/P.44 附近），本次没有
  进一步提取，如果以后要用特技做约束判断，值得回来挖这部分。

### 7.7 设施邻接加成与「吸收合併」机制（新了解，未建模）

手册"造幣廠會使鄰接的市場的效果，穀倉會使鄰接的農場的效果增為1.5倍"——
部分设施（造幣廠/穀倉）需要建在对应基础设施（市場/農場）**邻接**的
位置才能生效，会使邻接设施收益提升50%。「吸收合併」（都市菜单第2项，
之前完全没有解释过是什么）原来是"將2個相鄰接的內政設施合併為1個設施。
可合併的內政設施為「市場」「農場」「兵舍」「鍛冶廠」「廄舍」。合併後，
設施的Lv會上昇，收入及生產量也會增加"——是一种设施升级机制，不是本项目
当前建模的8种 `ActionKind` 之一，`rules/domestic_actions_pk_1.1_cn.json`
目前没有为它建条目。这类"设施相对位置/邻接关系"的机制，依赖 M1 层面
解析出城池的完整设施清单+位置（现在完全没有，见验证清单8.11"目标格
精度"那条缺口），这次只记录发现，没有扩展数据模型或新增 `ActionKind`。

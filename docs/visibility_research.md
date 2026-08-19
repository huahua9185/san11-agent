# 信息边界 / 可见性状态调研报告（M2）

> 本文档记录 M2 里程碑里"谁能看到什么"这一层依赖、但目前**无法从真实游戏内存里
> 确定**的状态。做法与 docs/offset_research.md（M1）一致：找不到可靠依据的地方
> 明确标 unknown 并在这里列出，不猜测填值。

## 1. M2 要解决的问题，和 M1 遗留缺口的关系

M2 的过滤器（`san11agent/boundary.py`）本身是纯函数：给定一份完整
`GameState` 和一个能回答"是否可见"的 `VisibilitySource`
（`san11agent/visibility.py`），输出人类可见的 `VisibleGameState`。这一层的
正确性已经用离线合成 fixture 完整测试（`tests/test_boundary.py`），不依赖
真实内存。

但把过滤器接到真实游戏进程上、真正过滤出对局中某一时刻的人类可见状态，
依赖两类信息，其中第一类在 M1 阶段就已知是缺口，第二类是 M2 新发现的缺口：

### 1.1 继承自 M1 的缺口：城池所属势力 ID —— 2026-08-18 找到了替代解决路径

`offsets/pk_1.1_cn.json` 里 `city.faction_id` 直接字段仍然标记为
`unknown: true`（见 docs/offset_research.md 4.2 节，原资料说要走一个
未知偏移的虚表函数调用）。但 2026-08-18 发现了一条不需要这个直接字段的
替代路径：**`City.force_id`（已知，confidence high）→ 新解出的
`Force[force_id].faction_id` → `Faction[faction_id]`**，在12座城池上
交叉验证全部给出历史上合理的势力归属，见 docs/offset_research.md 第
7.11节。也就是说"这座城池是不是我自己的"这个判断依据**实际上已经可以
拿到了**，只是要经过这条两步查表的间接路径，而不是一个能直接读的字段——
**`_filter_city()` 已于 2026-08-18 改用这条链路**（见第 3.1 节末尾和
`docs/offset_research.md` 第 8.4 节）。下面这段"读不到"的描述保留是为了记录
原始问题，不再反映当前行为。

这对 M2 过滤器的实际影响：`_filter_city()` 用 `city.faction_id == player_faction_id`
判断是否己方。在这个字段被解析为 `None` 的情况下，比较结果恒为 `False`——
所有城池都会被当成"非己方"处理，包括玩家自己的首都。这是**刻意的、安全的
退化行为**：宁可对己方城池也保守地只给摘要信息（fail closed），也不错误地
把它当成"确定是己方"从而绕过后续的探明检查（fail open）。在这个字段
被解决之前，真实进程场景下 M2 过滤器不会有实际可用的输出，但也不会泄漏数据。

### 1.2 M2 新发现的缺口：探明 / 视野 / 武将发现状态

为了实现 M2，检索了 M1 引用的同一份资料库（sjn4048/311MemoryResearch）里
所有可能相关的关键词：迷雾、视野、探明、侦察、情报、发现、在野、羁绊。
**没有找到任何字段偏移或函数地址**能直接回答以下三个问题：

1. **某座非己方城池，其内部详情（守军数量/武将配置/粮草储备）是否已对玩家
   探明？** 游戏内确实存在类似机制（比如需要谍报/势力接触后才能看到详细
   情报），但资料库里没有对应的标志位记录。
2. **某支非己方部队，当前是否在玩家视野内（未被战场迷雾遮挡）？**
   同样没有找到。
3. **某个无势力归属的在野武将，玩家是否已经发现/接触过？**
   同样没有找到。

这三个问题在 `san11agent/visibility.py` 里对应
`VisibilitySource.is_city_explored` / `is_troop_visible` /
`is_general_discovered`。真实进程场景下使用的
`UnresolvedVisibilitySource` 对这三个方法一律显式抛出
`VisibilityUnknownError`，不会返回"默认已探明"（会泄漏数据）或"默认未探明"
（会让过滤器在真实对局里几乎不可用但至少不泄漏)——这两种默认值都是没有依据
的猜测，所以选择显式报错，符合"遇到无法确定的地方标 unknown 并汇报，不要
猜测填值"的要求。

## 2. "玩家自己是哪个势力"——特意不从内存派生

`offsets/pk_1.1_cn.json` 里唯一疑似相关的字段是 `faction.player_marker`
（`+0x60`），但该字段本身的语义未经实机验证：注释写着"是索引还是布尔标志
未经实机验证，先原样暴露数值"，`confidence: low`。

M2 没有尝试拿这个未验证的字段去派生 `player_faction_id`，而是让
`VisibilitySource.player_faction_id` 变成一个必须由调用方显式提供的值——
玩家自己选了哪个势力开局，这本来就是玩家/操作方已知的信息，不需要靠猜内存
字段语义来确定。等 `player_marker` 的语义被实机验证过，可以再加一个
"从 GameState 派生并和显式传入值交叉核对"的辅助函数，但不会取代显式传入
这个默认、更可靠的路径。

## 3. "在野武将"哨兵值的假设 —— 2026-08-18 已确认成立

`boundary.py` 里 `FREE_AGENT_FACTION_ID = -1` 是根据 M1 现有代码里其它
字段的既有惯例推出来的假设——`General.death_year`、`General.special_skill_id`、
`Troop.vice_general_1_id` / `vice_general_2_id` 在"无"的情况下都用 `-1`
表示。**2026-08-18 实机验证**：真实进程里 1100 位武将中恰好有 413 位
`faction_id == -1`，数量级和"剧本1(黄巾之乱)大部分历史人物尚未登场"的
预期吻合，这个假设已确认成立，见 `docs/offset_research.md` 第7.10节。

### 3.1 但同一次验证发现了一个更严重的问题：`faction_id == player_faction_id` 这个比较本身可能是错的

`_filter_general()`（`boundary.py` 第107行）和 `_filter_troop()`（第196行）
都用 `xxx.faction_id == player_faction_id` 判断"这是不是我自己的
武将/部队"。这次验证发现：**对于"有归属"（非-1）的武将，`faction_id`
的具体数值不是稳定的政治势力索引**——抽样9位驻守城池、未随部队出征的
武将，`faction_id` 精确等于他们所在城池的 `index`（比如張燕
`faction_id=3`，恰好是南皮城池的 index，而不是"张角势力"该有的某个固定
数字）；带兵在外的武将（裴元紹）`faction_id=4`，又是另一个和前者不在
同一体系里的值。

这意味着：**即便未来把 `player_faction_id` 这个显式传入值搞对了，
`general.faction_id == player_faction_id` 这个比较在真实对局里也大概率
永远不会为真**（除非碰巧 `player_faction_id` 数值等于某座城的 index），
`_filter_general`/`_filter_troop` 现在这个"识别己方"的实现在接入真实内存
后会系统性失效，而不是仅仅"字段还没验证过所以保守拒绝"这种安全的退化——
这是一个需要在真正接入真实内存前修复的逻辑问题，不只是等一个字段解析
出来那么简单。城池的 `_filter_city()`（第160行）用的是 `city.faction_id`
（不同字段，仍然完全 unknown，未受这次发现直接影响，但同样需要重新
评估"这真的是稳定的势力ID吗"这个前提）。

详细的原始数据和另一个疑点（`troop.faction_id` 在已确认为真实、活跃的
部队记录上读到 `-1`，语义更加不明）见 `docs/offset_research.md` 第7.9/
7.10节。在这个问题被进一步厘清之前，不建议信任 `general.faction_id`/
`troop.faction_id` 做任何"是否属于某势力"的判断。

**2026-08-18 追加：已经找到一条可靠的替代路径**——`General`/`City`
都有已知的 `force_id`（"军团ID"），2026-08-18 新解出了 Force（军团）
结构体的 `faction_id` 字段，`General/City.force_id → Force[force_id]
.faction_id → Faction[faction_id]` 这条链路在12座城池的交叉验证上全部
给出历史上合理的结果，详见 `docs/offset_research.md` 第7.11节，代码
已实现（`san11agent/perception.py` 的 `parse_forces()`，`GameState.forces`）。
**→ 2026-08-18 已修复**（用户确认后执行）。新增
`san11agent/faction_resolve.py` 的 `FactionResolver`，`boundary.py` 的三个
过滤函数改用它解析归属；`VisibleXxx.faction_id` 也改成装解析后的值，因此
`legal_actions.py` / `situation_summary.py` 的同类判断自动变正确，无需改动。
解析失败返回 `None`，自动 fail-closed。详见
`docs/offset_research.md` 第 8.4 节。

⚠ 仍需注意：三条解析路径里 `of_troop()`（部队）**尚未实机验证**——Troop
结构体没有 force_id，只能经主将绕两跳，这条路是目前这一层最弱的一环。
下次上机验证待办见 `docs/verification_checklist.md` 第 4.4 项。

## 4. 战斗随机数种子 / 命中判定预演

项目规格里禁止暴露的条目之一是"战斗随机数种子、命中判定结果的预演"。
M1 的 `GameState` 里完全没有建模任何战斗计算相关的数据结构（M1/M2 阶段都
还没有战斗系统，见 README 路线图，战斗是 M6 的范围）。所以这一条在 M2 里
没有对应的具体字段需要过滤——不是遗漏，是当前 `GameState` 的表达范围里
根本不存在这类数据。等 M6 引入战斗相关状态时，需要在那个里程碑里同样按
白名单方式扩展 `VisibleGameState`，而不是假设"以后自然会被挡住"。

## 5. 需要你确认的问题（汇总）

1. 城池所属势力 ID（`city.faction_id`）和探明/视野/武将发现三个标志位，
   目前全部是 unknown。你是否有额外资料（比如 CE 表、SCP 插件源码）能提供
   这些字段的偏移？或者你打算之后我们一起对着运行中的游戏做内存搜索
   （比如对比切换"谍报"界面前后的内存快照差异）来定位？
2. ~~`FREE_AGENT_FACTION_ID = -1` 这个假设是否合理？~~ **2026-08-18 已确认
   合理**，见第3节。同一次验证牵出的关联问题——`general.faction_id`/
   `troop.faction_id` 在"有归属"时的真实语义不是稳定的政治势力ID——
   **已于同日修复**：`_filter_general`/`_filter_city`/`_filter_troop`
   改用 `FactionResolver`（`force_id -> Force.faction_id` 链路）判断归属，
   见第3.1节。仍需你关注的是其中 `of_troop()` 这条路径尚未经实机验证。
3. 详见提交报告里关于信息边界字段归类的具体取舍（哪些字段划进"公开"档、
   哪些划进"己方专属"档），这些是游戏规则层面的判断，不是内存研究缺口，
   单独列在报告里让你确认。

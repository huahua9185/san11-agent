# 实机验证清单（汇总 M1~M4）

> 本文档把 `docs/offset_research.md`（M1）、`docs/visibility_research.md`（M2）、
> `docs/execution_research.md`（M3）、`docs/legal_actions_research.md`（M4）四份
> 报告里散落的"待确认/unknown"事项，以及 `offsets/pk_1.1_cn.json`、
> `ui_layout/pk_1.1_cn.json`、`rules/domestic_actions_pk_1.1_cn.json` 三份数据
> 文件里所有标 `unknown: true` 或语义未经实机核实的字段，汇总成**一份按操作
> 顺序排列的清单**，供你坐到能跑游戏的电脑前时按顺序执行。
>
> 本文档不猜测任何数值，只列"要验证什么、为什么需要、建议怎么做、填到哪里"。
> 四份原始报告仍然是各里程碑设计取舍的完整记录，本文档不取代它们，只是把
> "需要动手验证"的部分抽出来重新按流程组织。

## 总览

- **共 44 项待验证/待确认事项**，分 8 个阶段，大致对应你坐下来那一次的真实操作顺序。
- **关键路径（P0，卡住一切真实内存相关工作）**：阶段 3 的 `GAME_DATA_BASE` 锚点定位方法（1.1 节）。在这一项解决之前，阶段 4、5 完全无法进行——`ProcessMemoryReader` 真实进程模式下代码会显式拒绝解析并报错退出（`san11agent/perception.py` `resolve_anchor()`），这是刻意设计，不是 bug。
- **不依赖锚点、可以随时先做的两块**：阶段 7（内政规则数值，纯靠观察游戏内 UI 数字变化）、阶段 8 里的一部分设计假设（比如设施类型是否齐全、地图网格形状、地图滚动方式——这些靠"看游戏""玩一玩"就能确认，不需要读内存）。如果锚点问题一时半会解决不了，可以先做这两块，不会浪费这次上机时间。
- 优先级标注：**P0** = 卡住某个里程碑继续推进；**P1** = 该里程碑能用但会有明显缺陷/安全退化；**P2** = 锦上添花，缺了不影响里程碑基本可用性。

```
阶段1 启动游戏确认版本  →  阶段2 进入存档/附加进程  →  阶段3 定位锚点【P0，全局关键路径】
        →  阶段4 验证已有偏移  →  阶段5 定位缺失内存字段  →  阶段6 测量界面坐标
        →  阶段7 验证规则数值(可提前做)  →  阶段8 验证设计假设(部分可提前做)
```

---

## 阶段 1：启动游戏，确认版本信息

### 1.1 确认游戏具体版本号/补丁号 [P0][依赖: 无] ✅ 部分完成 2026-08-18
- **验证什么**：`san11pk.exe` 的具体版本号/补丁号/文件大小或哈希。
- **为什么需要**：`offsets/pk_1.1_cn.json` 的 `meta.game_version` 目前是 `null`，`pk_1.1_cn` 这个标签只是沿用规格文档示例命名，**不代表已确认版本是 1.1**（见 `docs/offset_research.md` 第2节）。311MemoryResearch 资料全仓库都没有标注对应版本，如果你的游戏版本和资料作者的不一致，后面所有偏移都可能对不上，且没有任何独立信号能提前发现——只能靠这一步先确认。
- **建议怎么做**：游戏内"关于"界面，或右键 `san11pk.exe` → 属性 → 详细信息，或直接告诉我文件大小/MD5，我可以帮你和已知版本信息交叉核对。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `meta.game_version`；如果确认版本和资料不一致，可能需要重新考虑 `meta.label` 的命名。
- **2026-08-18 结果**：已采集文件大小/SHA256/VersionInfo/PE TimeDateStamp，见 `offsets/pk_1.1_cn.json` → `meta.file_identity` 和 `docs/offset_research.md` 第7.1节。`meta.game_version` 仍为 `null`——游戏内"关于"界面显示的版本号字符串本次没有采集（需要键鼠操作打开菜单，不在本次只读勘察范围）。

### 1.2 确认进程名与游戏内置假设一致 [P1][依赖: 无] ✅ 已完成 2026-08-18
- **验证什么**：任务管理器里游戏进程的实际可执行文件名是否确实是 `san11pk.exe`（不同发行渠道——比如 Steam 版——文件名或壳可能不同）。
- **为什么需要**：`offsets/pk_1.1_cn.json` 的 `meta.process_name` 硬编码为 `"san11pk.exe"`，`san11agent/memory.py` 的 `find_pid_by_process_name()` 按这个名字精确匹配（大小写不敏感），名字不对会导致 `--process` 模式直接报错"没有找到进程"。
- **建议怎么做**：游戏启动后打开任务管理器"详细信息"页确认进程名。
- **填到哪里**：如果不一致，改 `offsets/pk_1.1_cn.json` → `meta.process_name`。
- **2026-08-18 结果**：真实进程名是 `San11WPK.exe`（Steam 繁体中文版），与假设不一致，已更新 `offsets/pk_1.1_cn.json` → `meta.process_name` 及代码里的示例/文档，见 `docs/offset_research.md` 第7.1节。

---

## 阶段 2：进入某个剧本存档

### 2.1 记录本次验证用的具体剧本/存档 [P2][依赖: 无]
- **验证什么**：本次验证选用哪个剧本编号、哪个存档（新开局还是读档），后续所有"观测到的数值"都要基于这个已知起点才能交叉核对。
- **为什么需要**：`offsets/pk_1.1_cn.json` 的 `validation.scenario_id_range` / `start_year_range` 校验依赖能读到真实 `scenario_id`/`start_year` 后和已知剧本信息比对；如果不记录用的是哪个剧本，读出来的数字对不对无从判断。
- **建议怎么做**：选一个你记得清楚开局年份/君主/势力数的剧本（比如"黄巾之乱"），进正式对局（不要在剧本选择界面，那样 `GAME_DATA_BASE` 后面的数组可能还没初始化）。
- **填到哪里**：无需填文件，口头/聊天里告诉我即可，供后续核对用。

---

## 阶段 3：定位内存锚点 GAME_DATA_BASE 【全局关键路径】

### 3.1 GAME_DATA_BASE 锚点定位方法 [P0][依赖: 阶段1/2完成，游戏进入正式对局] ✅ 已完成（high confidence）2026-08-18
- **验证什么**：`0x07201958` 这个资料里给出的绝对地址，到底是编译期固定的静态地址（`模块基址 + 固定RVA`），还是运行时堆分配、每次重启会变的指针目标（需要指针链）。
- **为什么需要**：这是**整个项目里唯一的、卡住所有真实内存读取的问题**。`offsets/pk_1.1_cn.json` 的 `anchor.resolution_method` 目前是 `"unknown"`，`perception.py` 的 `resolve_anchor()` 在这个值下对真实进程会直接抛 `AnchorResolutionError` 拒绝继续——General/City/Troop/Faction/GlobalState 全部数组都基于这个地址算偏移，不解决它，阶段4、5 的一切工作都无法开始，M1 之后所有里程碑的真实进程验证都被卡住。
- **建议怎么做**（二选一或都做，用 Cheat Engine）：
  1. **验证"静态地址"假说**：进程附加后，直接查看地址 `0x07201958` 处的内存内容，看是否稳定存在有意义的数据（比如武将姓名的 GBK 字节）。如果**重启游戏后这个绝对地址还是同一份数据**，说明是静态地址，此时用 `模块基址`（Cheat Engine 里能直接看到，一般就是 `0x00400000`）反推 RVA = `0x07201958 - 模块基址`，写入 `resolution_method: "static_rva"` + `rva`。
  2. **验证"堆指针"假说**（更可能，见 `docs/offset_research.md` 第3节的 RVA 过大分析）：在 Cheat Engine 里对 `0x07201958` 这个地址做"什么写入了这个地址"或指针扫描（Pointer Scan），找一条从 `San11WPK.exe+固定偏移` 出发、经过 1~2 层解引用能稳定指向数据基址的指针链。**重启游戏一次，确认这条指针链依然成立**（这是判断"真的是稳定指针链"还是"偶然对上"的关键一步）。写入 `resolution_method: "pointer_chain"` + `pointer_chain`。
  3. 如果你手头有能跑起来的 CE 表或 SCP 插件源码，直接看它们是怎么定位这个基址的，可能比重新扫描更快。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `anchor.resolution_method`（改成 `static_rva` 或 `pointer_chain`）、`anchor.rva` 或 `anchor.pointer_chain`、`anchor.confidence`（改成 `high`）；`meta.verified` 暂不要改（还需要阶段4的字段验证通过才算数）。
- **2026-08-18 结果**：不用 Cheat Engine，改用项目自带的 `probe-anchor` 工具直接对真实进程验证。`static_rva`（rva=`0x6E01958`，即把 `0x07201958` 当绝对地址反推）第一轮验证通过。随后用户**重启游戏并进入另一个正式对局存档**，用同一个 rva 重新验证：角色底表数据（姓氏/五维属性）逐字节不变，随存档变化的字段（faction_id/location）正确变化，城池数据从"整齐的开局数值"变成"玩了30旬后参差不齐的真实存档数值"——静态数据不变+动态数据合理变化的组合证据排除了"上次是巧合"的可能。`anchor.confidence` 已从 `medium` 提升为 `high`。副产品：发现 `scenario_id` 更可能是 0-based 索引，已同步调整 `validation.scenario_id_range` 从 `[1,60]` 到 `[0,59]`。详见 `docs/offset_research.md` 第7.3/7.7节。

---

## 阶段 4：验证已有偏移

> 前提：阶段 3 完成，`anchor.resolution_method` 已经不是 `unknown`。这一阶段目标是确认"已经填了数值、但从未在真实进程上测过"的字段到底对不对——`offsets/pk_1.1_cn.json` 的 `meta.verified` 目前整体是 `false`，本阶段做完才能考虑把它改成 `true`。

### 4.1 用 `snapshot` 命令跑一次真实进程，看启动校验能否通过 [P0][依赖: 3.1] ✅ 已完成 2026-08-18
- **验证什么**：`validate_constants()`（`perception.py`）里的合理性校验——武将数=1100、城池数=42、势力数=42、剧本编号在 `[1,60]`、开局年份在 `[150,280]`——是否都能通过。
- **为什么需要**：这是项目里现成的、最快的"偏移表整体对不对"信号。校验失败几乎肯定意味着锚点或某个基础 struct 偏移算错了，值得先跑一次而不是逐字段人工核对。
- **建议怎么做**：
  ```
  python -m san11agent.cli snapshot --offsets offsets/pk_1.1_cn.json --process San11WPK.exe --summary
  ```
  （用 `C:\Users\hhhh\AppData\Local\Programs\Python\Python312\python.exe`，不是 `python`/`python3` 别名）。校验不通过会明确打印哪个数字对不上，据此判断是锚点问题还是某个 struct 偏移问题。
- **填到哪里**：无需改文件；如果校验失败，回到 3.1 或本阶段其余项排查。若通过，是后续把 `meta.verified` 改 `true` 的必要条件之一。
- **2026-08-18 结果**：跑通过，无报错。武将数=1100/城池数=42/势力数=42/剧本编号=7/开局年份=251，全部通过。跑的过程中发现城池/武将姓名解码乱码，排查后是文本编码问题（简体GBK vs 繁体cp950），已修复，详见 `docs/offset_research.md` 第7.4节。`meta.verified` 仍保持 `false`——4.2（troop 基址二选一）和 4.3（逐字段抽查）尚未做。

### 4.2 Troop 基址的 `0x100` 差值二选一 [P0][依赖: 3.1]
- **验证什么**：`troop.base_offset` 到底应该是 `0x169630`（当前默认值，按公式算出）还是 `0x169730`（资料原文独立给出的绝对地址对应值），两者相差 `0x100`（256字节）。
- **为什么需要**：部队（Troop）是 M1 五张核心表之一，`GameState.troops` 全部基于这个基址；选错会导致读出来的部队数据整体错位（读到的其实是相邻部队记录里的字段）。当前默认用的是 `0x169630`，但资料本身对这个值存疑，见 `docs/offset_research.md` 第3节"数值矛盾"。
- **建议怎么做**：读一条已知部队（比如你亲自派出的一支部队）的 `commander_general_id`（`+0x0C`）和 `troop_count`（`+0x18`），分别用两个候选基址算出的地址读取，哪个读出来的主将ID和你在游戏里实际派的武将对得上、兵力数字合理，就是对的。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.troop.base_offset`（确认后可以把 `base_offset_candidates` 数组删掉或保留作记录）。

### 4.3 抽查高/中置信度字段与游戏内实际显示比对 [P1][依赖: 3.1, 4.1] 🟡 部分完成 2026-08-18
- **验证什么**：`confidence: "high"`/`"medium"` 的字段（武将姓名/统率武力智力政治魅力/城池钱粮兵力/势力信息等，`offsets/pk_1.1_cn.json` 里绝大多数字段）是否真的读出了和游戏界面一致的数值。这些字段虽然有交叉印证的资料支持，但**从未在真实进程上实测过**（`meta.verified: false`）。
- **为什么需要**：交叉印证的是"多份第三方笔记互相印证"，不是"在你这个具体版本的游戏上跑过"——4.1 的整体校验只能发现明显错位，不能保证每个字段都对。
- **建议怎么做**：用 `snapshot`（不加 `--summary`）打印完整 JSON，挑 2~3 位你认识的武将、2~3 座你熟悉的城池，逐字段和游戏内界面显示的数字肉眼比对。重点核对三处已知"顺序未验证"的地方：
  - `general.base_stats`（统率/武力/智力/政治/魅力的字节顺序）
  - `general.display_stats_wound` / `display_stats_normal`（受伤/未受伤显示属性顺序）
  - `general.location` 的编码规则（是否真的是">87 表示在部队中，减87=部队ID"）
- **填到哪里**：核对通过的字段，把 `confidence` 从 `medium`/`low` 提升到 `high`；核对不上的，改成 `unknown: true` 并写清楚原因。全部核对完、4.1 校验通过后，可以把 `meta.verified` 改成 `true`。
- **2026-08-18 结果**：用户发来两张城池详情截图（南皮/濮陽），逐字段核对 `city.gold`/`city.food`/`city.troops`/`city.security`/`city.governor_general_id`（经姓氏交叉核对），**五个字段十项数值全部精确吻合**，均已提升到 `confidence: high`。同时验证了 `current_xun` 换算日期公式（30旬+184-1-1=184-11-1）与截图日期一致。但截图里的"耐久"/"現役"两个字段扫描后确认不在 City 记录范围内（可能需要走设施子结构）。`general.base_stats` 字节顺序、`display_stats_wound/normal`、`general.location` 编码规则这三项**仍未核对**（需要你确认具体某位武将的属性/位置状态），`meta.verified` 仍为 `false`。详见 `docs/offset_research.md` 第7.8节。

---

## 阶段 5：定位缺失的内存字段

> 这一阶段的字段全部是 `unknown: true`，`perception.py`/`execution_state.py` 解析时会安静跳过（返回 `None`），不会报错也不会编数据——除非你显式定位到偏移。**这九项按"能否在同一次操作里顺便一起测"分成四组**，减少反复重启/反复操作的次数。

### 组 A：切换游戏阶段界面（内政/战略/战斗）时对比快照——可一次定位 1 项

#### 5.1 `global.phase`（游戏阶段标志位）[P0][依赖: 阶段4]
- **验证什么**：能标识"当前处于内政阶段/战略阶段/战斗阶段/单挑阶段"等的标志位偏移。
- **为什么需要**：这是 M1 最大的空白之一。M3 的归位例程（`execution.py` `_home()`）目前只能"连续按 Esc"、无法验证真的回到了哪个界面；M4 的动作执行、未来的对局循环也需要知道"当前是不是内政阶段"才能决定该不该枚举内政动作。全仓库关键词检索（游戏阶段/内政阶段/战略阶段）完全没有命中，311MemoryResearch 资料库里没有这个字段。
- **建议怎么做**：在内政界面、战略地图界面之间来回切换，每次切换前后各做一次内存快照（比如用 Cheat Engine 的"内存扫描"或"冻结对比"，或者手动记录 `GAME_DATA_BASE + 0x28` ~ `+0x58` 这段目前完全没有记录字段含义的区间——`global` struct 原资料本身在这一段是空白，值得优先扫描这里），找出哪个字节/字段随界面切换而稳定变化。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.global.fields.phase`。

### 组 B：等待游戏内时间推进时对比快照——可一次定位 3 项

#### 5.2 `global.current_year` / `current_month` / `current_day`（当前年/月/日）[P1][依赖: 阶段4]
- **验证什么**：能直接读取当前游戏内年/月/日的字段偏移。
- **为什么需要**：资料里只找到三个疑似取值函数地址（`004824B0`/`004824F0`/`00482530`），没给出内部换算公式，也没给出可以直接内存读的字段。目前 `GlobalState` 里这三个字段都是 `None`。
- **建议怎么做**：记录当前 `current_xun`（已知偏移 `+0x5C`）和游戏界面上显示的年月日，推进几旬后再记录一次，比较两次快照差异——如果能找到一个随时间推进而规律变化的字段，多半就是它；同时可以验证"开局年月日 + 当前旬数 × 10天"这个换算方案本身是否和界面显示吻合（如果吻合，即使找不到直接字段，也可以确认这个换算方案可用，见 5.2 备选方案）。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.global.fields.current_year/current_month/current_day`；如果决定采用"换算"方案而非直接字段，需要额外告诉我，`perception.py` 的 `parse_global_state()` 需要改成算出来而不是直接读。

### 组 C：城池易主/势力接触前后对比快照——可一次定位 3 项

#### 5.3 `city.faction_id`（城池所属势力ID）[P0][依赖: 阶段4]
- **验证什么**：城池自身的"所属势力ID"字段偏移（不是 `force_id` 军团ID，那个已知）。
- **为什么需要**：这是**继承自 M1、影响 M2/M4 两个下游里程碑的关键缺口**。`boundary.py` 的 `_filter_city()` 用它判断"这座城是不是我自己的"，未知时恒为 `False`（fail-closed：所有城池都当非己方处理，包括玩家自己的首都，宁可保守也不泄漏，但真实对局里完全不可用）；`legal_actions.py` 的 `enumerate_legal_actions()` 同样靠它判断能否在某城发起内政动作、能否把某城列为计略目标。资料显示这是通过虚表函数调用（`[[城市指针]+0x40]` 间接调用，注意这个虚表槽位偏移数值上和"兵力"字段的直接偏移 `+0x40` 相同但含义完全不同，容易搞混）取得的，没有直接字段偏移。
- **建议怎么做**：对比你自己的城池和一座已知势力的城池的完整内存区域快照，或者更直接——观察一座城池被攻占、易主前后的内存快照差异（如果本次对局能等到这种事件）；也可以尝试沿着资料提到的"设施(Facility)指针"（函数 `0047c4c0`）方向反汇编确认。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.city.fields.faction_id`。

#### 5.4 `city.map_x` / `city.map_y`（城池地图坐标）[P0][依赖: 阶段4]
- **验证什么**：城池本体在战略地图上的格子坐标（不是 `domestic_land_x/y`，那是内政建设用地坐标，已知）。
- **为什么需要**：M3 执行层 `CitySelector` 要把城池格子坐标换算成屏幕坐标再点击，没有这两个字段，`select_city()` 无法拿到目标城池的坐标输入（目前只能靠调用方从外部传入 `TileCoord`，见 `cli.py` 的 `--tile-x/--tile-y` 参数，这不是长久之计）。
- **建议怎么做**：资料推测需要先经函数 `0047c4c0` 取得关联的"设施(Facility)"指针，再读该结构体 `+0x1E`（x）/`+0x20`（y），但"城市指针→设施指针"这一跳的偏移常量本身未给出。可以尝试反汇编该函数确认跳转偏移；或者更简单地——已知若干城池在游戏地图上的大致格子坐标（比如从小地图或已有的地图标注资料换算），在内存里搜索这些已知的小整数值，看能否在城池记录附近找到匹配。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.city.fields.map_x/map_y`。

### 组 D：拖动地图/点击不同城池前后对比快照——可一次定位 3 项（M3 execute 阶段专用，建议和阶段6一起做）

#### 5.5 `camera.offset_x` / `camera.offset_y` / `camera.zoom_level`（地图摄像机偏移/缩放）[P0][依赖: 阶段4]
- **验证什么**：地图滚动/缩放状态对应的内存字段。
- **为什么需要**：`map_projection.py` 的 `project_tile_to_client()` 需要它才能把地图格子坐标换算成屏幕坐标；未定位时该函数直接抛 `MapProjectionError`，M3 执行链路在真实进程场景下完全无法进行地图点击。
- **建议怎么做**：拖动/滚动地图前后各做一次快照对比，找出随滚动量变化的字段（大概率是两个相邻的 i32/f32）；缩放地图（如果游戏支持缩放）前后再对比一次找 `zoom_level`。**同一次操作里请一并记录**：拖动的方向和格数、缩放的挡位，方便后续验证 5.6/8.16/8.17/8.18 的单位和语义假设。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.camera.fields.offset_x/offset_y/zoom_level`。

#### 5.6 `selection.selected_city_index`（当前选中/高亮的城池 index）[P0][依赖: 阶段4]
- **验证什么**：点击城池后，"当前选中城池"这个状态对应的内存字段。
- **为什么需要**：`execution.py` 的 `CitySelector` 用它轮询确认"点击城池"这个动作是否生效——没有这个字段，M3 执行链路无法验证点击是否成功，只能盲发输入。
- **建议怎么做**：依次点击几座不同的城池，每次点击前后做快照对比，找出随点击目标变化、且数值等于该城池在 `city` 数组里 index 的字段。可以和 5.5 在同一次拖地图+点城池的操作序列里顺带做完，减少来回。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.selection.fields.selected_city_index`。

### 组 E：M2 可见性相关字段——建议结合具体游戏事件测，无法完全在同一次操作里凑齐

#### 5.7 探明状态标志位（`is_city_explored`）[P1][依赖: 阶段4]
- **验证什么**：某座非己方城池的内部详情（守军/武将/粮草）是否已对玩家探明的标志位。
- **为什么需要**：`visibility.py` 的 `UnresolvedVisibilitySource.is_city_explored()` 目前对真实进程一律显式抛 `VisibilityUnknownError`，M2 过滤器在真实对局里无法给出"能看到多少非己方城池细节"的正确答案。
- **建议怎么做**：找一座目前"不了解详情"的非己方城池，通过谍报/势力接触等游戏内手段让它变为"已探明"，对比这个操作前后该城池记录附近的内存快照差异。
- **填到哪里**：`offsets/pk_1.1_cn.json` 需要新增一个字段位置（目前文件里还没有为这个概念预留 struct/field，需要先确定它是城池记录内的一个字节，还是单独一张"探明表"，再决定加在哪）。

#### 5.8 视野内标志位（`is_troop_visible`）[P2][依赖: 阶段4]
- **验证什么**：某支非己方部队当前是否在玩家视野内（未被战场迷雾遮挡）的标志位。
- **为什么需要**：同上，`visibility.py` 的 `is_troop_visible()` 同样显式报错，M2 过滤器无法正确处理"部队是否可见"。
- **建议怎么做**：观察一支敌方部队进入/离开你的侦察范围前后的内存快照差异（可能需要等到有对战/侦察机制触发的场合，不一定能在纯内政阶段测到）。
- **填到哪里**：同 5.7，需要先确定加在哪张表。

#### 5.9 在野武将发现标志位（`is_general_discovered`）[P2][依赖: 阶段4]
- **验证什么**：一个无势力归属的在野武将，玩家是否已经发现/接触过的标志位。
- **为什么需要**：同上，`is_general_discovered()` 同样显式报错。
- **建议怎么做**：找一位当前"未发现"的在野武将，通过游戏内手段（比如所在城池被己方控制、或搜索武将）使其变为"已发现"，对比前后快照。
- **填到哪里**：同 5.7。

> 5.7~5.9 优先级低于组 A~D，是因为它们依赖能触发到具体的游戏事件（城池探明/部队遭遇/武将发现），不一定能在一次短暂的验证会话里凑齐条件；如果这次时间有限，可以先跳过，不影响 M1/M3/M4 的推进（只影响 M2 在真实对局里的可用性）。

---

## 阶段 6：测量界面坐标

### 6.1 `map_viewport`（地图显示区域坐标 + 格子像素尺寸）[P0][依赖: 无，但通常和阶段5组D一起做效率最高]
- **验证什么**：地图显示区域在客户区内的矩形范围（`x`/`y`/`width`/`height`）以及每个地图格子在缩放=1时的像素尺寸（`tile_width`/`tile_height`）。
- **为什么需要**：`ui_layout/pk_1.1_cn.json` 目前唯一的元素、全部字段都是 `unknown: true`——游戏完全无法运行时只搭好了格式。`map_projection.py` 的坐标换算完全依赖这几个值，未测量时 `project_tile_to_client()` 直接抛 `UILayoutError`（不重试，直接失败，见 `docs/execution_research.md` 第3节第8条的重试策略说明）。
- **建议怎么做**：游戏窗口调整到一个固定分辨率/窗口大小（记录下来，因为 `ui_layout` 目前假定单一分辨率，`meta.assumed_client_resolution` 也待填），截图后用图像工具量出地图显示区域的像素矩形；格子尺寸可以数一段已知长度的地图边缘除以格数，或者用 AutoIt Window Info / Spy++ 之类工具直接读取控件坐标（如果地图区域本身是一个可识别的子窗口/控件）。**建议和 5.5/5.6（拖地图、点城池）在同一次操作里做**：先测量好视口坐标，再立刻用这些坐标去验证 camera/selection 字段是否读出了预期变化，一次操作两头对齐，减少来回验证的次数。
- **填到哪里**：`ui_layout/pk_1.1_cn.json` → `elements.map_viewport.{x,y,width,height,tile_width,tile_height}`，把 `unknown` 改 `false`，`meta.assumed_client_resolution` 和 `meta.verified` 一并填。

---

## 阶段 7：验证内政规则数值（可不依赖锚点，随时可做）

> 这一整块**不需要读内存**，纯靠"发起一个内政指令前后，界面上金/粮/体力数字的变化"来确认，所以如果阶段3的锚点问题一时解决不了，可以先做这部分，不浪费上机时间。`rules/domestic_actions_pk_1.1_cn.json` 里 8 种动作、每种 3 项资源（体力/金/粮），全部标 `unknown: true`——不是内存偏移问题，是规则数值本身没有实机验证途径。这里的 `unknown` 语义和 `offsets.py` 不同：`legal_actions.py` 不会因为规则未知就拒绝枚举动作，只会在对应 `Action.unverified_constraints` 里标记"这条约束没被真正检查过"（`rules/domestic_actions_pk_1.1_cn.json` → `meta.description` 有说明）。

### 7.1~7.8 八种内政动作的体力/金/粮消耗阈值 [P1][依赖: 无]

| # | 动作 (`ActionKind`) | 需要确认 | 填到哪个 JSON 路径 |
|---|---|---|---|
| 7.1 | `build_facility` 设施建设 | 体力/金/粮消耗（五种设施——农田/市场/兵营/马厩/弩楼——是否各自不同，还是统一价格） | `actions.build_facility.{min_general_stamina,gold_cost,food_cost}.value` |
| 7.2 | `recruit_troops` 征兵 | 体力/金/粮消耗（发起指令本身的门槛，不是"按人数计费"的具体费率） | `actions.recruit_troops.*` |
| 7.3 | `train_troops` 训练 | 体力/金/粮消耗 | `actions.train_troops.*` |
| 7.4 | `security_patrol` 治安/巡查 | 体力/金/粮消耗 | `actions.security_patrol.*` |
| 7.5 | `levy_gold` 征收（金） | 发起门槛（是否要求最低城池余额）、体力/粮消耗 | `actions.levy_gold.*` |
| 7.6 | `levy_food` 征收（粮） | 同上 | `actions.levy_food.*` |
| 7.7 | `diplomacy` 外交 | 体力/金/粮消耗，五种子类型（同盟/停战/婚姻/贸易/恫吓）是否各自费用不同 | `actions.diplomacy.*` |
| 7.8 | `stratagem` 计略 | 体力/金/粮消耗，五种子类型（离间/煽动/流言/破坏/劫略）是否各自费用不同 | `actions.stratagem.*` |

- **为什么需要**：这些数值目前全部 unknown，`unverified_constraints` 会一直挂在每个枚举出的 Action 上，下游（未来的 LLM prompt/Execute）拿到的每条动作都带着"资源消耗未经验证"的标记，没法做真正的资源可行性判断。
- **建议怎么做**：对每种动作，找一位符合条件的己方武将，记录发起指令前的体力/该城金/粮，执行后再记录一次，差值就是消耗。子类型不同的（`build_facility`/`diplomacy`/`stratagem`）建议每种子类型都单独测一次。这部分工作量较大（最多 8×3=24 个具体数值，加上子类型细分更多），建议按优先级分批做，不必一次做完；`unverified_constraints` 机制保证了"没测的部分"不会被误当作"已确认无消耗"。

---

## 阶段 8：验证设计假设与规则细节

> 以下各项不是"内存资料里没找到的事实"，而是各里程碑为了让代码能跑起来，自行做出的**未经真实游戏验证的设计假设**。多数不需要专门的内存工具，靠观察游戏行为/界面即可确认，所以同样**大部分不依赖阶段3的锚点解决**，可以提前做（已在每项标注依赖）。

### 数据语义类（依赖阶段4/5，需要能读到对应字段的值）

#### 8.1 `general.location` 编码规则 [P1][依赖: 4.3]
- **验证什么**：">87 表示在部队中，减87=部队ID，≤87 是别的编码"这条注释里的猜测是否成立。
- **为什么需要**：`legal_actions.py` 的 `default_is_general_in_city()`（第150行）默认假设 `location == city.index` 来判断"武将是否在这座城"，这个假设的合理性直接依赖 `location` 字段的编码规则是否如此。
- **建议怎么做**：观察若干武将在"在城中"和"在部队中"两种状态下 `location` 的实际数值，看是否符合">87在部队中"的规律。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.general.fields.location.note`（更新说明），如需要新增编码规则文档。

#### 8.2 `location == city.index` 假设是否成立 [P0][依赖: 8.1]
- **验证什么**："武将在这座城"是否真的等价于 `General.location == City.index`。
- **为什么需要**：这是 M4 `enumerate_legal_actions()` 判断"这位武将能不能在这座城发起内政动作"的默认实现，如果假设错了，会导致武将被错误地排除或错误地放行。
- **建议怎么做**：找几位明确在某座城里任职的武将，核对其 `location` 值是否等于该城 `index`。
- **填到哪里**：如果假设成立，在 `docs/legal_actions_research.md` 里补充确认记录；如果不成立，需要修改 `legal_actions.py` 的 `default_is_general_in_city()`。

#### 8.3 `FREE_AGENT_FACTION_ID = -1` 假设 [P1][依赖: 4.3]
- **验证什么**："在野武将"（无势力归属）的 `faction_id` 是否真的是 `-1`。
- **为什么需要**：`boundary.py` 第31行这个常量是根据其它字段（`death_year`/`special_skill_id`/`vice_general_*_id` 在"无"时都用 `-1`）的代码风格类推出来的假设，不是资料明确写的事实。用错会导致 M2 过滤器对在野武将的可见性判断错误。
- **建议怎么做**：找一位确认在野（无主）的武将，核对其 `faction_id` 字段实际值。
- **填到哪里**：`san11agent/boundary.py` 第31行注释更新为已确认状态，或改成实测到的正确哨兵值。

#### 8.4 `faction.player_marker` 语义 [P2][依赖: 4.3]
- **验证什么**：这个字段到底是"索引"还是"布尔标志"。
- **为什么需要**：`confidence: low`，M2 特意没有用它来派生 `player_faction_id`（改成显式传入），如果语义确认了，可以加一个"从内存派生并和显式值交叉校验"的辅助功能（锦上添花，非必须）。
- **建议怎么做**：核对该字段在你自己控制的势力记录里的具体数值，和其它势力记录对比。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.faction.fields.player_marker`。

#### 8.5 `general.base_stats` 字节顺序 [P2][依赖: 4.3]（已在 4.3 覆盖，此处仅强调）
- 见 4.3，五维属性（统率/武力/智力/政治/魅力）的字节顺序需要和界面对照确认。

#### 8.6 `display_stats_wound`/`display_stats_normal` 字节顺序 [P2][依赖: 4.3]（已在 4.3 覆盖，此处仅强调）
- 见 4.3，`confidence: low`，需要单独核对。

#### 8.7 `faction.relations_table` 单项字节数 [P2][依赖: 4.3]
- **验证什么**：47个势力好感度表，原资料写"48字节对47个势力"，字节数与数量不完全对应，每一项到底占几字节。
- **为什么需要**：目前该字段整体按 `bytes` 类型原样暴露、不做二次解析，如果要在未来把它解析成"每个势力对应的好感度数值"列表，需要先确认单项字节数。
- **建议怎么做**：找一个势力对其余各势力的好感度在界面上的显示值，和这块内存区域按不同字节宽度（1字节/2字节）切分后的数值比对，看哪种切分方式能对上。
- **填到哪里**：`offsets/pk_1.1_cn.json` → `structs.faction.fields.relations_table.note`。

### 游戏规则类（大多不依赖内存，靠观察游戏机制/UI）

#### 8.8 "治安"和"巡查"是否为同一指令 [P1][依赖: 无]
- **验证什么**：游戏里是否存在两个独立的指令，还是同一指令的两种叫法。
- **为什么需要**：`rules/domestic_actions_pk_1.1_cn.json` 目前把两者合并成一个 `security_patrol`，本表没有独立证据支持这个合并。如果实际是两个独立指令，`ActionKind`/对应 dataclass 都要拆开。
- **建议怎么做**：直接在游戏内政菜单里查看有没有两个分开的选项。
- **填到哪里**：`rules/domestic_actions_pk_1.1_cn.json` → `actions.security_patrol`（如需拆分，需要新增 `ActionKind` 和 dataclass，属于代码改动，不在本次文档整合范围内，届时另行处理）。

#### 8.9 `levy_gold`/`levy_food` 是否应合并成一个"征收"指令 [P1][依赖: 无]
- **验证什么**：游戏里"征收"是一次性同时拿金+粮，还是分开两条指令可以分别选。
- **为什么需要**：影响 `ActionKind` 的动作类型设计是否正确。
- **建议怎么做**：查看游戏内政菜单里的"征收"选项数量和交互方式。
- **填到哪里**：同 8.8，如需合并需要代码改动。

#### 8.10 `build_facility` 五种设施类型是否完整、准确 [P1][依赖: 无]
- **验证什么**：农田/市场/兵营/马厩/弩楼是否是该版本游戏里完整、准确的设施清单，名称有无出入。
- **为什么需要**：这五种是需求里直接列出的，没有独立验证过。
- **建议怎么做**：游戏内建设菜单直接核对完整列表。
- **填到哪里**：`rules/domestic_actions_pk_1.1_cn.json` → `actions.build_facility.facility_types`。

#### 8.11 `BuildFacilityAction.target_tile` 精度问题 [P2][依赖: 阶段5]
- **验证什么**：内政建设用地是否是多格网格（很可能是），而不是当前 `domestic_land_x/y` 这一组唯一坐标所暗示的单点。
- **为什么需要**：如果确实是多格网格，`GameState.City` 需要在 M1 层面解析出完整的空位列表，`LegalActions` 才能精确枚举"建在哪一格"，现在只能笼统带出这一组坐标并标 `target_tile_precision` 未验证。
- **建议怎么做**：观察游戏内建设界面，看是否能选择具体建在哪一格空地。
- **填到哪里**：这一项如果确认是多格网格，需要先扩展 `offsets/pk_1.1_cn.json` 的 `city` struct（新增完整空位列表字段），是一项后续的 M1 扩展工作，不只是填个数值。

#### 8.12 外交"已接触"前置条件是否存在 [P2][依赖: 无]
- **验证什么**：游戏里发起外交是否要求"已经知晓/接触过"该势力，还是对所有势力都能直接发起。
- **为什么需要**：`legal_actions.py` 目前对所有非己方势力都枚举外交动作，可能过度宽松。
- **建议怎么做**：观察游戏内外交菜单是否对尚未接触的势力有限制。
- **填到哪里**：`docs/legal_actions_research.md` 补充确认记录；如需建模，`GameState`/`VisibleGameState` 需要新增"是否已接触"字段，属于后续扩展。

#### 8.13 计略目标可达性/邻接要求是否存在 [P2][依赖: 无]
- **验证什么**：计略是否要求目标城池与己方接壤/在一定范围内。
- **为什么需要**：`legal_actions.py` 目前对所有归属已知的非己方城池一视同仁，可能过度宽松。
- **建议怎么做**：观察游戏内计略界面对可选目标城池的限制。
- **填到哪里**：同 8.12，如需建模可以先用现有 `city.adjacent_cities` 做粗略邻接判断。

### 执行层/坐标类（部分依赖阶段5组D/阶段6）

#### 8.14 地图网格形状：正交 vs 菱形/错位 [P0][依赖: 无，纯观察]
- **验证什么**：三国志11地图在游戏内实际是正交网格还是菱形/错位网格。
- **为什么需要**：`map_projection.py` 的坐标换算公式假设"正交网格+线性缩放"，如果实际是菱形网格，这个公式需要整体换成菱形坐标变换，不是简单调参数能解决的——直接决定 M3 执行链路的地图点击对不对。
- **建议怎么做**：直接观察游戏战略地图的视觉呈现即可判断，不需要任何工具。
- **填到哪里**：`san11agent/map_projection.py` 模块文档字符串更新确认结果；如果是菱形网格，`project_tile_to_client()` 需要重写坐标变换公式（代码改动，届时另行处理）。

#### 8.15 `zoom_level` 数值语义 [P1][依赖: 5.5]
- **验证什么**：`zoom_level` 是否可以线性换算成缩放比例（比如除以100），还是索引进一张预设缩放挡位表（比如只有5级缩放）。
- **为什么需要**：直接影响 `map_projection.py` 里 `ZOOM_LEVEL_DENOMINATOR = 100` 这个换算公式是否正确。
- **建议怎么做**：在 5.5 定位到 `zoom_level` 字段后，切换游戏内几个不同的缩放挡位，记录每挡对应的数值，看是否等间距（暗示线性）还是任意值（暗示索引表）。
- **填到哪里**：`san11agent/map_projection.py` 的 `ZOOM_LEVEL_DENOMINATOR` 或整个换算逻辑。

#### 8.16 `camera.offset_x/offset_y` 单位：格子 vs 像素 [P1][依赖: 5.5]
- **验证什么**：摄像机偏移的单位是地图格子数还是像素数。
- **为什么需要**：如果是像素单位，`project_tile_to_client()` 换算公式要相应调整（不再乘以格子像素尺寸）。
- **建议怎么做**：在 5.5 定位字段后，拖动地图一段已知格数的距离，观察该字段变化量是否等于格数（而非像素数）。
- **填到哪里**：`san11agent/map_projection.py` 换算公式，如果单位是像素需要改动。

#### 8.17 地图滚动的输入方式 [P1][依赖: 无，纯观察/尝试]
- **验证什么**：游戏内滚动地图到底是方向键、鼠标拖拽、鼠标停靠屏幕边缘触发滚动、还是点击小地图跳转（`execution.py` `_nudge_map()` 当前假设方向键，理由是"最不容易误触发其它功能"，但未经验证）。
- **为什么需要**：直接决定 M3 `CitySelector` 滚动进视野这一步的实现是否有效。
- **建议怎么做**：在游戏内直接尝试这几种输入方式，看哪种能让地图滚动。
- **填到哪里**：`san11agent/execution.py` 的 `_nudge_map()`，如果不是方向键需要改成对应的输入方式（代码改动）。

#### 8.18 `SendInput` 是否被游戏感知 [P0][依赖: 阶段6完成，需要能实际点击测试]
- **验证什么**：`input_backend.py` 的 `SendInputBackend`（标准 Win32 `SendInput` 消息注入）游戏是否真的能响应，还是游戏用 DirectInput/Raw Input 直接轮询硬件状态导致 `SendInput` 完全不起作用。
- **为什么需要**：这是 M3 `--live` 模式能否真正操作游戏的**前提性问题**——如果不认，`SendInputBackend` 整个失效，需要换成 `pydirectinput` 或虚拟 HID 驱动方案。
- **建议怎么做**：等阶段6坐标测量完成后，用 `select-city --live` 命令对一个已知坐标发起一次真实点击（**注意：这是本清单里少数会真正操作游戏窗口的验证项，执行前确认游戏处于安全可以随意点击的状态**），观察游戏是否有响应（城池是否真的被选中，配合 5.6 `selected_city_index` 一起验证）。
- **填到哪里**：如果不起作用，`san11agent/input_backend.py` 需要新增/替换实现（代码改动，届时另行处理）。

#### 8.19 窗口查找启发式是否适用 [P2][依赖: 阶段1（游戏已启动）]
- **验证什么**：`window.py` `_find_main_window_for_pid()` 用"属于目标pid、可见、标题非空"的第一个顶层窗口作为游戏主窗口，这个启发式对 `San11WPK.exe` 是否有效（尤其如果游戏是无边框全屏、或标题为空）。
- **为什么需要**：如果启发式失效，`Win32GameWindow.attach_by_pid()` 会找不到窗口，`--live` 模式直接报错。
- **建议怎么做**：可以用任意窗口枚举工具（比如 Spy++）查看游戏窗口的标题和可见性属性；或者更简单——直接跑一次 `select-city --live`，看这一步是否报错。
- **填到哪里**：`san11agent/window.py` 的 `_find_main_window_for_pid()`，如果启发式不适用需要调整判断条件。

---

## 附录A：不是"验证项"、是需要你拍板的设计决策

这两条不属于"内存里有没有这个值"或"游戏规则是什么"，是代码已经做了但可以商榷的设计取舍，**不需要实机验证，只需要你确认是否认可当前做法**：

1. **`MapProjectionError`（camera 未知触发）和真正的"滚动多次找不到目标格子"是否应该区别对待**：目前两者都被同一个 `except` 分支捕获，会被归位重试 `max_retries` 次；但 `UILayoutError`（ui_layout 未知触发）不会被捕获，直接抛出不重试。这个不一致点在 `docs/execution_research.md` 第3节第8条已经指出，如果你认为"配置缺失"（camera 或 ui_layout 任一未知）都不该重试，`execution.py` 里需要调整一处 `except` 分支。
2. **`rules/*.json` 的 `unknown` 语义选择"不拦截、只标记"**（`domestic_rules.py` 顶部文档字符串有完整说明）：这是和 `offsets.py`"unknown 就拒绝读取"相反的默认行为。当前选择是为了让 M4 现阶段能产出动作列表；如果你更看重"宁可枚举不全，也不要输出未经验证资源消耗的动作"，`legal_actions.py` 的 `_check_resource()` 一处逻辑需要反转。

## 附录B：辅助验证小工具（已实现）

这两个工具已经实现，接入了 `san11agent/cli.py`，复用现有的 `MemoryReader`/
`DumpMemoryReader` 抽象和 `perception.py` 的校验逻辑，不需要新的依赖。核心逻辑在
`san11agent/mem_snapshot.py`、`san11agent/mem_diff.py`、`san11agent/anchor_probe.py`，
单元测试在 `tests/test_mem_snapshot.py`、`tests/test_mem_diff.py`、
`tests/test_anchor_probe.py`、`tests/test_cli.py`。

1. **原始内存快照 + diff 工具**（`mem-dump` + `mem-diff` 子命令）：给定一个或多个
   地址范围，从真实进程抓取快照写成 dump json；`mem-diff` 对比两份或多份快照，
   按连续区间分组报告哪些地址变了、变化前后的字节内容（附带 u8/u16/i32/GBK 等
   几种类型解读），支持按地址范围/最小变化字节数过滤、按地址或变化幅度排序。
   三份及以上快照时会额外做"相邻快照两两 diff"的交叉比对，报告"每次过渡都变化
   的地址"和"只在某一次过渡里变化的地址"。示例：
   ```
   python -m san11agent.cli mem-dump --process San11WPK.exe --region 0x07201958:0x2000 --out before.json --label before
   （切换到内政界面）
   python -m san11agent.cli mem-dump --process San11WPK.exe --region 0x07201958:0x2000 --out after.json --label after
   python -m san11agent.cli mem-diff before.json after.json --base 0x07201958
   ```
2. **锚点候选批量验证工具**（`probe-anchor` 子命令）：给定一批候选 RVA/绝对地址/
   指针链（命令行参数或候选文件），对每个候选解析出 GAME_DATA_BASE，跑一遍
   `perception.validate_constants()` 现成的启动常量校验，报告每个候选通过/不通过、
   不通过时具体是哪个常量、期望值/实际读到的值分别是什么。示例：
   ```
   python -m san11agent.cli probe-anchor --offsets offsets/pk_1.1_cn.json --process San11WPK.exe \
       --rva 0x1958 --pointer-chain 0x1a2b3c,0x10,0x20
   ```

详细用法、设计取舍、测试覆盖见对应的实现报告（聊天记录）。

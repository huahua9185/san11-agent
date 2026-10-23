# REA：城池选择与命令上下文（2026-10-23）

## 本轮结论

**已确认（静态）**：城池指令菜单的调度入口是 `FUN_005756b0`。它接收一个
城池/据点对象指针 `param_1`，先用 `FUN_0047a750(param_1)` 校验，再通过对象
虚表 `+0x40` 取 0..0x2e 的城池索引，进入一个 47 个 case 的指令分派 switch。
`case 3` 调用 `FUN_005cbdf0`（巡察面板包装），`case 0x17` 调用
`FUN_005b7040`（另一个内政面板包装）；两个包装函数分别把同一个 `param_1`
传给 `FUN_0060b4e0` / `FUN_005fecf0` 面板函数。

**已确认（静态）**：命令执行回调 `FUN_00576650` 从 `in_ECX[8]`（this+0x20）
取城池对象指针，校验后直接调用 `FUN_005756b0(in_ECX[8], in_ECX[9],
in_ECX[10])`。也就是说，**当前操作目标城池不是通过一个裸 index 传入，而是
由命令/UI 上下文对象在 +0x20 处携带一个对象指针**。

**已确认（静态）**：面板对象把城池指针存在 `panel+0x18c`；`panel+0x190`
起是 3 个“已选执行武将”指针槽，`panel+0x1a0` 是候选迭代器。`FUN_0060b450`
从 `panel+0x1a0` 指向的候选列表里取最多 3 个指针，经 `FUN_0047a750` 校验后
写入 `+0x190/+0x194/+0x198`。`FUN_0060af30` 再逐个读取这三个槽。

**待验证（重要）**：`FUN_005756b0` 用对象虚表 `+0x40` 的返回值做 0..0x2e
的索引检查；`FUN_0060b4e0` / `FUN_005fecf0` 用 `+0x44` 的返回值去调
`FUN_00490d00`（已确认的军团访问器）。但“城市/据点对象”的虚表布局本身仍未
确认——对 `ctx+0x13c` 同类对象的 vtable 抽样显示 `+0x40/+0x44` 更像 UI/几何
方法（`FUN_00475890` / `FUN_004d67f0`），不能把这两个槽当成所有对象统一的
index getter。

**待验证（重要）**：全局上下文 `DAT_091ba048` 的 `+0x13c` / `+0x140` 不是
城池数组指针。运行时只读读取到：

```text
module_base=0x400000, GAME_DATA_BASE=0x7201958
DAT_091ba048 -> ctx=0x4EFD660 (双读稳定)
ctx+0x13C -> 0x4EFF7C0 (双读稳定)
ctx+0x140 -> 0x4EFF980 (双读稳定)
city_array=0x7201B30..0x7207B00
0x4EFF7C0 不在 city_array 内
```

`0x4EFF7C0` 的首 dword 是 `0x00835BC8`（vtable 样式），对象内部还有指回
`ctx` 的字段，形态更像 UI/列表对象而不是城池记录。因此，当前生产配置里
`selection.selected_city_index` 这个“单一全局裸 index”的模型未必成立：
城池选择更可能是**对象指针**，且可能随命令上下文/UI 对象变化。

## 追加发现：可读的“选中城市对象”候选

**已确认（静态 + 运行时只读）**：命令管理器全局 `DAT_096a58f0` 的
`+0x64` 存放当前选中的城池对象指针。当前进程读到：

```text
DAT_096a58f0              = 0x464D250
[0x464D250 + 0x64]        = 0x728B328
GAME_DATA_BASE            = 0x7201958
对象数组基址 +0x89730     = 0x728B088（布局步长 0x38）
(0x728B328 - 0x728B088)/0x38 = 12
city[12]                  = 陳留，force_id=0
对象+0x1C 高 16 位 / +0x20 低 16 位 = (108, 79)
city[12].domestic_land_x/y = (103, 74)
```

`FUN_004919a0` 的伪代码正好是：

```c
iVar1 = (param_1 - (in_ECX + 0x89730)) / 0x38;
if (-1 < iVar1 && iVar1 < 0x4000) return iVar1;
return -1;
```

也就是说，**该函数把“选中对象指针”换算成数组索引**，与当前
`0x728B328 -> index 12` 完全吻合。

**已确认（静态反汇编）**：在未被 Ghidra 识别为函数的 `0x574608` 附近，
选择流程把对象指针写入命令上下文：

```asm
0x57466B  mov eax, [0x96a58f0]       ; 命令管理器
0x574670  mov esi, [eax+0x64]        ; 选中对象
0x574674  call 0x47a750              ; 通用对象校验
0x574692  mov ecx, 0x7201958
0x574697  call 0x4919a0              ; 指针 -> 数组索引
0x5746C1  mov [ebp+0x1C], 1          ; 命令状态 = 已选中
0x5746C8  mov [ebp+0x20], esi        ; 命令上下文保存选中对象
```

这与 `FUN_00576650` 从 `in_ECX[8]`（+0x20）取对象、再调用
`FUN_005756b0` 的链完全闭合。

**候选读取路径（尚未写入生产 offsets）**：

```text
command_manager = read_u32(module_base + (0x96A58F0 - 0x400000))
selected_object = read_u32(command_manager + 0x64)
if GAME_DATA_BASE + 0x89730 <= selected_object < ... + 0x4000*0x38:
    selected_city_index = (selected_object - (GAME_DATA_BASE + 0x89730)) // 0x38
    map_x = read_u32(selected_object + 0x1C) >> 16
    map_y = read_u32(selected_object + 0x20) & 0xFFFF
```

**坐标证据**：对象数组前 42 项的 `(对象+0x1C 高 16 位, 对象+0x20 低 16 位)`
与 `city[i].domestic_land_x/y` 逐个城市比较，差值范围为 `x:-7..+14`、
`y:-11..+11`，空间关系一致；当前 `city[12]` 的 `(108,79)` 与
`domestic_land (103,74)` 相差 `+5/+5`。因此对象坐标很可能是
**城池在地图上的格子坐标**，与内政用地坐标相近但不同。

**仍不能直接上线**：对象数组前 42 项与 city 索引的对齐已有 42 城坐标相关性
和多点（濮陽/南皮菜单、濮陽/南皮纯悬停）支持，但 `+0x1C/+0x20` 是否就是
`city.map_x/map_y` 仍需更多城市/地图坐标对照。生产 `offsets` 仍未修改。

### A/B 受控验证结果（2026-10-23）

用户实际点击了**濮陽**和**南皮**的城池菜单（只打开菜单，未执行任何指令）。
只读探针 `probe2.jsonl` 捕获到三次稳定状态：

| 状态 | manager | selected object | index | city | object coord | domestic_land |
|---|---|---:|---:|---|---:|---:|
| 空闲 | `0x0` | `None` | `None` | — | — | — |
| 濮陽菜单 | `0x464cad0` | `0x728b2f0` | `11` | 濮陽 (force 5) | `(120,71)` | `(109,70)` |
| 南皮菜单 | `0x46487d0` | `0x728b130` | `3` | 南皮 (force 5) | `(138,37)` | `(129,34)` |

**已确认（A/B）**：

- `[manager+0x64]` 确实随城池菜单切换；
- `(obj-(GAME_DATA_BASE+0x89730))/0x38` 对两座城都返回正确的 `city.index`；
- 对象 `+0x1C` 高 16 位 / `+0x20` 低 16 位与两城的 `domestic_land` 坐标
  方向一致，差值与 42 城统计一致。

**仍不能当成完整 selection 方案**：

- manager 只在城池菜单/命令上下文存在时非零，关闭菜单后回到 `0x0`；
- 这次验证的是“城池菜单目标”；后续纯悬停 probe4 已确认悬停时同一条链
  也会写入（见下节），因此可用于 `CitySelector` 的 hover 轮询；
- `map_x/map_y` 仍是候选，尚未写入生产 offsets。

证据：`probe2.jsonl`、`probe_summary.json`。两次 A/B 分别有 41/71 个稳定
采样点，空闲段 manager 为 0，排除了“只捕获到一次瞬时值”的可能。

### 纯悬停验证结果（probe4）

用户明确确认：本轮**只把鼠标悬停到城池上，没有点击**。探针 `probe4.jsonl`
捕获到：

```text
南皮菜单残留(14) -> 空闲(24) -> 濮陽悬停(17) -> 空闲(6)
-> 南皮悬停(11) -> 空闲(166)
```

| 状态 | manager | selected object | index | city | object coord |
|---|---|---:|---:|---|---:|
| 空闲 | `0x0` | `None` | `None` | — | — |
| 濮陽悬停 | `0x464cad0` | `0x728b2f0` | `11` | 濮陽 | `(120,71)` |
| 南皮悬停 | `0x46487d0` | `0x728b130` | `3` | 南皮 | `(138,37)` |

**已确认（纯悬停）**：

- 悬停本身就会写 `[manager+0x64]`，不需要点击城池；
- 鼠标移开后 manager 回到 `0x0`，所以 `CitySelector` 必须在 `move_mouse()`
  后立即轮询；
- `context+0x13c/+0x140` 全程不变，不是选中状态来源；
- 因此 `selection_reader` 可以直接作为 `CitySelector` 的 selection 来源。

### Reader 落地

新增 [selection_reader.py](san11agent/selection_reader.py)：

- `SelectionLayout` 把版本相关的地址集中在一个 dataclass 里，便于以后迁入
  offsets schema；
- `read_selected_city()` 返回 `SelectedCity(city_index, city_name, map_x,
  map_y, manager_address, object_address)`；空闲时返回 `None`；
- `read_city_map_coordinate()` 独立按 city index 读取对象数组候选坐标；
- 不发送输入、不写内存；对象数组/坐标仍标为候选。

6 项离线测试覆盖濮陽/南皮、空闲、非法指针、独立坐标读取，以及
`parse_selection_state()` 的 unknown 回退。当前 409 项离线测试通过。

`execution_state.parse_selection_state()` 现在优先读 offsets 的显式字段，
字段 unknown 时回退到该 reader；`CitySelector` 走同一个函数，因此纯悬停
链路已经具备可用的 selection 来源。camera 坐标仍是实际点击前的硬阻塞。

## 范围与方法

- 目标：Steam 繁中 `San11WPK.exe`，x86，SHA-256
  `f2a304b118e72673f4a788b1e87322fa891ff57218a8b89e671d4f8cb6aca041`。
- REA 6.4.0 / Ghidra 12.1.4，分析载体
  `.rea-tools/san11-loaded-text.pe.bin`，SHA-256
  `bc7f57cf26fc7a17f3e85d520543f397d93fbba7bea13a74162f32bbe6410e8f`。
  该载体只替换了加载后的 `.text`，不是原始 EXE；来源见
  `docs/rea/loaded_text_provenance_2026-10-15.json`。
- 本轮没有发送键鼠输入、没有写游戏内存、没有调用游戏内部函数、没有切换存档。
  运行时部分只做 `ReadProcessMemory` 双读。
- `FUN_0047a750` 的完整伪代码已用有界 `rea decompile` 取得：它先调用
  `FUN_00472160(param_1,4,1)`，再调用对象虚表 `+8`，是一个**通用对象校验器**，
  不区分城池/武将类型；因此不能靠它判断 `param_1` 是哪类对象。

## 关键证据

以下路径均相对 `docs/rea/2026-10-23-camera-selection/`；`ev_...` 为 Evidence ID。

| 观察 | 证据 |
|---|---|
| `FUN_004ec980` 返回 `DAT_091ba048`；`FUN_004ec990` 返回 `[ctx+0x13c]`；`FUN_004ec9b0` 返回 `[ctx+0x140]` | `ctx_accessor_4ec980_pseudo.json` / `ev_2b09fa304dd1374a5232b32e7a9bf6f0dcc5f51617a01c989649b7d89eca0a4c`；`selected_object_getter_4ec990.json` / `ev_3202be19c2b16873db7d10727574f741df19bd78c91f2e7cf51f045d73f117dc`；`ctx_accessor_4ec9b0_pseudo.json` / `ev_8ec388786b21324c6d8d45d5448f1805824b0f6d39c7e3a2b832cd5eea0b7407` |
| `FUN_004eca30` 安装全局上下文；`FUN_004ed540` 构造默认上下文 | `ctx_accessor_4eca30_pseudo.json` / `ev_88d9fec1d66a0dda5958ee03863c8f200e8f29cd10cfa32a4de1894aec19acf5`；`ctx_accessor_4ed540_pseudo.json` / `ev_032daa37f862a208dafddd9159019b9c32728d39314204ef2cb3eb02631b8e2a` |
| `FUN_005756b0` 以 `param_1` 城池对象进入 47 个 case 的指令分派；case 3/0x17 分别调用巡察/另一面板包装 | `command_dispatcher_5756b0.json` / `ev_7ffffee7d4daff6b420bfb27ea4a127938c1224338b93047df7ce0cbcf5790c9` |
| `FUN_00576650` 从 `in_ECX[8]`（+0x20）取城池指针并调用分派器 | `dispatcher_caller_576650.json` / `ev_aa694173223aa1d2eead093ac7193823a59d98c031d3cc1de960c9eb8fb23b1b` |
| `FUN_005ba0f0` 遍历 44 个命令条目，把城池指针传给条目虚方法 | `city_menu_builder_5ba0f0.json` / `ev_ed61ebd24b902e42ca54379b5d5c7c58b10a600b5d61ff9d5ab6f84846db95b7` |
| 两个面板包装 `FUN_005cbdf0` / `FUN_005b7040` 都被 `FUN_005756b0` 调用，并把 `param_1` 传给面板 | `patrol_panel_caller_5cbdf0.json` / `ev_c08fda468550cf1605f6a4ca51d26a906e9f6315a28b480c9518c458d2a53ae4`；`panel_caller_5b7040.json` / `ev_e74004b680534575e442cdf27f946e267a420cd305a214036469024cba7080ab` |
| 面板把城池指针存在 `+0x18c`，把 3 个执行武将指针存在 `+0x190` 起 | `panel_helper_60b450.json` / `ev_da6b51b33a2f9991959c2fe57512b0f5b171dfa31aa5307d19aa003fa94ce85a`；`panel_helper_60af30.json` / `ev_cb4e6af4d583bcf527af8afe62c6fba35041993018ae3434cf1d3a7737400c00`；`panel_helper_60ae50.json` / `ev_81895d6d9bc0739471222ce7feb35890d5d50e6d5b8c38a986ba22c4463ecb80` |
| 既有巡察面板证据：`+0x18c` 城池指针、`+0x44` 取军团、`+0x2c` 行動力 | `docs/rea/2026-10-23-budget/patrol_panel_60b4e0.json` / `ev_060e93e30f2ea41c07ab056cd5aa2e39a664f654e0bff9dbba501b0d2081b864`；`docs/rea/2026-10-22/followup/panel_5fecf0.json` / `ev_5349be912e33fbbe239a5207f4acf4442896dbe0a90380a12fee4160b415f7ab` |
| `FUN_0047a750` 是通用对象校验器：`FUN_00472160(param_1,4,1)` + 虚表 `+8`，不区分类型 | `validator_47a750_decompile.json` / `ev_938ff0230ec3db7488c06ee5adb1dffca4ce97381c5cea54776b3d0aa011c840` |
| `FUN_004919a0` 用 `(obj-(GAME_DATA_BASE+0x89730))/0x38` 计算索引，范围 0..0x3FFF | `selected_city_index_4919a0.json` / `ev_8ce79bebc4b53493fc0742ec2dc4b3ca9bfca8178ea7b3cc8119bd9d89aad0f0` |
| `FUN_00487d00` 以对象 `+8` 调 `FUN_00490dc0` 并检查结果 `+0xB4==4`；具体类型语义未完全解析 | `selected_object_check_487d00.json` / `ev_25b7da7cbe665ce94d85f5f0d858dc4ad69614781a0f8c80cd72142ae8805c81` |
| `FUN_00574f10` 初始化命令对象；`FUN_00574060` 用对象虚表 `+0x40` 生成状态 | `command_init_574f10.json` / `ev_cddb936852968aed68b3111e7fb716956f555abac2a68e2312b6c6b46b8071d9`；`command_helper_574060.json` / `ev_7c5e945d0885f2717ae314c76dab5f082752e7d2386b66faba873caff751331c` |
| `DAT_096a58f0` 引用点集中在 0x5746xx–0x57cfxx；其中 0x5746C8 写入命令上下文 `+0x20` | `command_global_96a58f0_xrefs.json` / `ev_db2e4854fa14f458aef626e65b4a61f4f389a170c326d2004388372c3451d9f7`；`command_selection_setter_disassembly.json`（Capstone 只读反汇编） |
| 当前 `DAT_096a58f0+0x64` 指向对象索引 12，对应 city[12]=陳留；对象坐标 (108,79)，domestic_land=(103,74) | `selected_city_probe.json`（本轮只读探针） |
| A/B 点击濮陽/南皮菜单后，manager+0x64 分别指向 index 11/3，city 名和坐标同步变化 | `probe2.jsonl`、`probe_summary.json`（只读轮询探针） |
| 纯悬停濮陽/南皮（无点击）同样写 manager+0x64；移开鼠标后回到 0 | `probe4.jsonl`、`probe4_summary.json`（用户确认只悬停） |
| `ctx+0x13c/+0x140` 同用 vtable `0x835bc8`；抽样槽位是 UI/几何方法而非 index getter | `vtable_473210.json` / `ev_596b05999d1d1e72b43a6d33bba8e0f8131ae86c8a8b4aed12af868b516567cf`；`vtable_475890.json` / `ev_712f7f9e96d3e5311050f9ef84399c98f4b8274b056de6ef143cae932e263bcd`；`vtable_4759d0.json` / `ev_c026b34d5d2298eaf0f1d15d9dc2ff3b83c8a01089b17b16a181c6197bd33a65`；`vtable_4eda70.json` / `ev_3c628a6e4e57bd73ce3bbc9ad9ae2dd4ad4da17337a239c2b8eb26ba2dbe27d2`；`vtable_4d67f0.json` / `ev_194f1b5a4e3c6a292bbb102c295f0585f4409a055358d53b026954d9631846ae` |
| 运行时 `ctx` / `+0x13c` / `+0x140` 双读稳定，且 `+0x13c` 不在城池数组内 | `selected_pointer_probe.json`（本轮只读探针，不是 REA Evidence） |

## 仍未确认

1. `ctx+0x13c` / `ctx+0x140` 指向的对象类型；它们是否是“当前选中城池”的
   另一种表示，还是 UI 列表项/菜单上下文，尚未证明。
2. 城市/据点对象的真实 vtable 布局，以及 `+0x40/+0x44` 在真实城市对象上的
   语义；`ctx+0x13c` 同类对象的 vtable 抽样不是 index getter，不能据此推断
   所有对象。
3. 对象数组前 42 项按 city index 对齐已有 42 城坐标相关性和菜单/悬停多点
   支持，但 `+0x1C/+0x20` 是否就是 `city.map_x/map_y` 仍需更多城市或地图
   坐标对照。
4. 悬停确认已经完成，但探针本身没有记录鼠标坐标；manager 只在悬停/菜单
   期间非零，轮询必须紧接 `move_mouse()`，离开后立即回到 0。
5. camera 的 `offset_x/offset_y/zoom_level` 本轮没有推进；`selection` 和
   camera 应作为两条独立链继续。

## 下一步

1. 用有界 CLI 分析 `FUN_00487d00` / `FUN_00490dc0`，确认对象 `+8` 的语义
   （当前 42 项大多为 0，不能直接当作势力 ID）。
2. 给 `CitySelector` 增加一个“selection 字段 unknown + reader 回退”的集成
   测试，确认 hover 轮询在真实 selection 路径上不会退回假的 `-1`。
3. 继续验证 `city.map_x/map_y`，再解决 camera；只有这两者都可用，地图点击
   才算真正打通。
4. camera 另行从地图滚动/投影调用链切入，不要与 selection 混在同一个候选里。

## 证据目录

`docs/rea/2026-10-23-camera-selection/`，包含本轮 open_binary、xrefs、
function 分析与运行时只读探针；其中 `validator_47a750.json` 是因 MCP
响应预算失败的错误记录，不代表该函数不存在。

# REA 研究记录

## 最新状态（2026-10-23整理）

**预算研究追加，已确认**：巡察的20点有效费用、所属军团余额门槛及扣减路径已
接入LegalActions的单条可负担性检查。其他动作不把基础标价当有效费用；巡察仍
保留patrol_preconditions，整批共享预算调度尚未实现。最新384项测试通过，完整
证据见[预算研究报告](rea_action_budget_2026-10-23.md)。本轮没有新增游戏操作。

**2026-10-23追加，已确认**：武将行动标志已定位并接入 `General+0x124` 位0，
只暴露己方布尔状态；LegalActions和摘要排除已行动者，未知值显式标记。
原 `+0x12A` 简单行动标志假设已被跨旬反例排除。完整来源与未解决的清位调用链见
[武将行动状态报告](rea_general_action_state_2026-10-23.md)。最新测试366项通过。

**2026-10-23追加，已做 A/B + 纯悬停（selection）**：城池指令菜单调度入口
`FUN_005756b0` 接收城池对象指针并进入 47 个 case 的分派；命令回调
`FUN_00576650` 从 `this+0x20` 取该指针。全局上下文
`DAT_091ba048+0x13c/+0x140` 是稳定的堆对象指针，但运行时不在城池数组内，
vtable 抽样也是 UI/几何方法而非 index getter，不能当裸城池 index。另发现
`DAT_096a58f0+0x64` 指向当前城池对象：A/B 分别点击濮陽/南皮**菜单**，
以及一次**只悬停、不点击**的濮陽/南皮测试，都返回 index 11/3，city 名和对象
`+0x1C/+0x20` 坐标同步变化；移开鼠标后 manager 回到 0。对象坐标是
`city.map_x/map_y` 候选。未修改生产 offsets。已实现 `selection_reader.py`，
并接入 `execution_state.parse_selection_state()` 的 unknown 回退；新增 6 项
离线测试，当前 422 项通过。详见
[城池选择与命令上下文报告](rea_selection_2026-10-23.md)。本轮无游戏输入。

**2026-10-23 camera阻塞（待处理）**：探针原先未做 DPI 感知，在 175% 缩放下
读到虚拟化 `1462×914`；加 `ensure_dpi_awareness()` 后客户区为 `2560×1600`，
`ui_layout` 视口匹配。但四点悬停/点击标定仍无法用二维等距公式拟合
（仿射最大残差约34px，成对 zoom 不一致），地图很可能是3D透视/地形视图，
camera字段仍未定位。已开始D3D静态排查：修正vtable偏移后找到4处
SetTransform，全部是WORLD(0x100)，没有VIEW/PROJECTION；42处`+0x178`
调用的语义仍待确认。未修改生产 offsets/ui_layout，未发送输入。详见
[camera报告](rea_camera_2026-10-23.md)和[D3D报告](rea_d3d_2026-10-23.md)。
已用 apitrace 抓取 D3D9 trace，取得真实 VIEW/PROJECTION 矩阵；4K四城验证
得到 map→world 仿射并固化到 `map_camera.py`；已实现 d3d9 代理 DLL，
实时 VIEW/PROJECTION 写入 `Local\San11Camera`，`camera_reader.py` 可读取。
当前422 passed。2026-10-23 实机 live hover 平原成功（selection None→4，只移动
鼠标未点击），见[D3D抓帧报告](rea_d3d_trace_2026-10-23.md)。

**已确认**：便携Ghidra/JDK已可用，游戏已进入可恢复存档并完成一次巡察和一次推进旬；
早期DirectX启动失败不再是当前阻塞。军团行動力 `Force+0x2C u8` 和表容量47
已由REA代码与实机对照建立证据，接入生产读取、己方过滤和摘要；356项测试通过。

完整事实基线、原始证据索引、实验范围和后续优先级见
[REA行動力研究报告](rea_action_points_2026-10-22.md)。
**待验证**：完整人员资格和跨旬清位调用链、共享预算及成本修正、界面状态与定位。
真实执行器和 `advance_turn()` 仍未实现；下文“尚未验收”“未修改生产offsets”
均是当时的历史记录，已被后续报告中的明确进展取代。

## 目标与验收

目标：在匹配版本和可恢复测试存档中，仅使用已确认的人类可见信息，完成一个内政动作，核对实际效果，推进一旬并确认玩家重新获得控制。

本记录区分代码事实、工具观察、推测和待验证事项；静态结果不能代替实机验证。

## 2026-10-15：P0-0 环境与版本检查

- 已确认（PowerShell Get-FileHash）：安装文件 `C:\Program Files (x86)\Steam\steamapps\common\San11WPK\San11WPK.exe` 的 SHA-256 为 `F2A304B118E72673F4A788B1E87322FA891FF57218A8B89E671D4F8CB6ACA041`，与 offsets/pk_1.1_cn.json 的历史身份记录一致。
- 已确认（san11 get_game_status）：检查时游戏未运行，compatibilityStatus=game_not_running；不能开展动态字段或动作验证。
- 已确认（REA binary_session）：REA package/server 版本均为 6.4.0；当前没有打开分析目标。
- 已确认（REA provider diagnostics）：Ghidra provider 未配置 GHIDRA_INSTALL_DIR，Java runtime 未找到；IDA provider 未配置 REA_IDA_MCP_CONFIG；Hopper 不支持当前 Windows 主机。
- 待验证：Ghidra/JDK 是否存在于其他未检查目录。上述诊断仅证明 provider 当前不可用，不证明整台机器未安装。
- 当前没有修改生产偏移、执行器或游戏状态；不能声称动作闭环已经完成。

## 下一步研究问题（按依赖顺序）

1. P0-1：菜单处理对象如何保存操作目标及界面状态？获取对象类型、ID/指针、菜单/确认/处理中状态；接入 execution_state.py 和执行轮询。
2. P0-2：城池如何关联地图设施？获取地图位置、相机投影参数；接入 perception.py、game_state.py、execution_state.py、map_projection.py。
3. P0-3：指令可用性判断读取哪些资源和资格？获取行動力真实归属、余额、人员行动状态和设施条件；接入 visible_state.py、boundary.py、legal_actions.py。
4. P0-4：选择一个实机流程明确的内政指令，追踪人员/参数选择和最终确认；接入真实 ActionExecutor，并以状态变化核对成功。
5. P0-5：追踪结束回合及控制权恢复；接入 RealGameStateSource.advance_turn()。
6. P1：核对人类可知信息规则，实现真实 VisibilitySource。

## 历史函数线索：全部待验证

来源为 docs/offset_research.md 的第三方资料引用；这些地址不是本轮确认的函数语义。即使 EXE 哈希匹配历史实机版本，第三方资料也可能针对其他版本。

| 历史 VA | 资料描述 | 当前研究用途 |
|---|---|---|
| 0x0047c4c0 | 城市到设施访问 | 推测可能提供城市地图位置或通用据点关系入口 |
| 0x004c0c30 | 城市信息命令分发 | 查找资源显示读取与设施关联的交叉引用 |
| 0x004c8720 | 武将信息命令分发 | 查找人员状态、所在对象和执行资格相关读取 |
| 0x004824b0/0x004824f0/0x00482530 | 当前年月日读取候选 | 低优先级辅助核对，不能据此认为回合控制流程已知 |

禁止直接调用这些历史函数或把候选偏移填入生产配置。

## 证据验收模板

每个发现记录：目标 SHA-256、REA/provider版本、Evidence ID、函数VA/RVA与文件映射、数据类型、地址解析方式、静态观察、推测语义、动态操作步骤、观察值、独立复现、反例和未覆盖范围。

动态验收至少覆盖：目标A/目标B/空地、取消、重复操作、重新加载、重启；资源归属还要对照同军团多城和同势力多军团。

实机前置：可恢复存档、玩家势力与允许的具体动作范围已知；录制/调试须有明确结束条件。未完成实机核对的字段保留 unknown。

## 本轮静态证据与动态阻塞

- 已确认（REA inspect_pe_resources）：PE32、machine=0x14c（x86），完整资源树覆盖305项目录条目、147个资源。Evidence ID：`ev_0c00ae947cdff0174d04ec7b1dcf3bbbfb8f5eea34250a10cd7550cfe2152b02`。完整证据保存在 `rea/pe_resources_2026-10-15.json`。
- 已确认（补充Python/Capstone检查，非REA反编译）：入口RVA为 `0x098b0310`，位于 `.bind` 节；六个历史地址的线性反汇编均产生异常指令片段。不能据此确认函数边界或原始语义。
- 推测：文件代码可能存在保护/变换，或者历史函数地址并不匹配。必须对照运行时加载后的代码，不能把这些磁盘片段解释为游戏业务实现。
- 已确认（字节检索）：七个关键词共59处匹配；`行動力` 的cp950字节在 `.rdata` 中有9处匹配，UTF-16LE没有匹配。字节命中不证明字符串边界、运行时引用或资源归属。
- 已确认（用户反馈）：远程桌面启动游戏提示 DirectX 初始化失败，无法打开；具体错误码及失败原因待验证。显示适配器枚举检测到 Intel Iris Xe、Intel Arc A770M、Microsoft Remote Display Adapter；这不能单独证明远程显示驱动就是根因。
- 已确认（本轮pytest）：当前工作区348项测试通过，耗时1.26秒；它们不证明真实动作闭环成功。
- 用户已授权下载官方Ghidra和JDK至项目内便携研究目录；不改变系统Java、PATH或全局REA注册。

补充静态线索由 `tools/collect_static_research.py` 生成，输出为 `rea/static_leads_2026-10-15.json`。脚本校验目标及REA资源证据哈希，仅读取文件，绝不执行游戏。需要机器上已有Capstone；它不是san11agent生产运行依赖。

## 便携工具链

已从官方来源下载，解压前校验SHA-256：

| 工具 | 官方来源 | SHA-256 |
|---|---|---|
| Ghidra 12.1.4 | https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build | ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db |
| Temurin JDK 21.0.12.1+1 Windows x64 | https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1 | f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e |

工具和下载包位于 `.rea-tools/`，已加入gitignore；入口 `tools/rea-portable.ps1` 只对被调用的CLI临时设置环境并在结束后恢复。

已确认（REA doctor）：Ghidra 12.1.4、64位完整JDK、headless、native decompiler、Windows原生进程与路径控制以及目标文件检查通过。完整结果：`rea/doctor_portable_2026-10-15.json`。其他客户端注册的提示不影响当前便携CLI分析，不修改无关客户端配置。

复用命令：

```powershell
& .\tools\rea-portable.ps1 doctor --provider ghidra --target 'C:\Program Files (x86)\Steam\steamapps\common\San11WPK\San11WPK.exe' --format json
```

已完成REA对真实PE入口VA `0x09cb0310` 的静态分析：provider=Ghidra 12.1.4，目标x86，Evidence ID=`ev_e27686d09fa1922e48830f5a68bc5dafb5154c547a4a9e5a15bd8d3052425712`。输出 `rea/entry_analysis_2026-10-15.json`。观察到入口调用候选函数 `FUN_09cb03a0`，反编译器同时警告栈空间跟踪不完整；未建立该函数的游戏业务语义或保护机制。

## 恢复游戏运行后的第一个实验

用户反馈远程桌面下DirectX初始化失败、游戏无法启动，因此本轮不能进行动态验收。不能把静态候选写成已验证偏移。

本地桌面能够启动游戏后，先运行只读代码对照，再执行任何游戏指令：

```powershell
python tools/capture_runtime_code.py --out .rea-tools/runtime_code_first.json
```

该工具核对实际进程EXE的SHA-256，将历史VA转为RVA并以当前模块基址定位，只读取六处128字节代码、各重复读取两次，保存稳定性和磁盘字节对照。不会启动或暂停目标、设置断点、注入或写入内存；已有输出拒绝覆盖。

已确认：两个研究Python脚本通过py_compile；游戏未运行时capture_runtime_code明确失败，未生成虚构的运行时证据。成功读取、ASLR换算的实机结果仍待验证。字节不同也不能单独证明加壳：重定位、补丁或代码变换均待排除。

## 同轮追加：进程出现后的只读代码核对

- 已确认（san11 get_game_status）：随后检测到PID14908，EXE身份匹配，模块基址0x00400000，x86；进程无主窗口标题。桥接器结构兼容性通过不等于已进入可操作存档，仍不发送键鼠输入。
- 已确认（ReadProcessMemory）：六处候选地址各读取128字节、每处重复两次；全部稳定，全部与磁盘对应字节不同。结果位于忽略目录 `.rea-tools/runtime_code_first.json`。这是有限代码范围的观察，不是游戏状态验证。
- 已确认：仅提取 `.text` 区域3461120字节，并以连续两次全区域一致作为保存条件；保留其他节的磁盘字节，创建独立分析副本 `.rea-tools/san11-loaded-text.pe.bin`。原游戏文件未改动，也不执行派生副本。
- 原始SHA-256：`f2a304b118e72673f4a788b1e87322fa891ff57218a8b89e671d4f8cb6aca041`；派生SHA-256：`bc7f57cf26fc7a17f3e85d520543f397d93fbba7bea13a74162f32bbe6410e8f`。来源记录：`rea/loaded_text_provenance_2026-10-15.json`。
- 限制：派生文件是“加载后代码+磁盘其他节”的混合分析载体，不是完整运行时映像，不保证资源/导入/可执行行为等价；REA结果必须引用派生哈希及来源链，不能当成原始EXE的静态代码证据。
- 已确认（REA/Ghidra）：原始入口后续函数0x09cb03a0反编译完成，Evidence ID=`ev_71b49917e8e58ab16aa0e8a5ae2bf35de1386c6594b46c26eb2f5843e417be77`；观察到MZ/PE签名比较和大量间接调用，存在类型推导未收敛警告。输出 `rea/startup_analysis_2026-10-15.json`；保护机制及业务语义仍待验证。
- REA对派生文件中历史候选0x0047c4c0的分析返回：`No procedure exists at the requested address`。完整诊断位于 `rea/loaded_city_accessor_2026-10-15.json`；这不证明地址没有指令，只证明此次Ghidra分析未建立该地址的函数入口。成功加载后的Capstone片段观察到多个相邻字段赋值，不能据此认定“城市到设施”功能成立。

接下来应优先追踪版本本身的 `行動力` 字符串引用，再核对其使用者，而不是把第三方历史函数地址当成可信入口。

只读代码比较的去字节摘要已保存为 `rea/runtime_code_comparison_2026-10-15.json`。后续再次执行状态快照时进程已退出，未取得可操作对局状态；不把短暂进程存在当作DirectX问题已解决。

## DirectX 前置问题的只读诊断

dxdiag报告当前远程显示适配器的DDrawStatus为Not Available、D3DStatus为Enabled；Intel Arc A770M的两项均为Enabled。摘要 `rea/display_diagnostics_2026-10-15.json`。

推测：当前会话下的显示接口能力差异可能参与初始化失败。但未取得游戏具体失败API/HRESULT，也没有本地桌面对照，不能确认根因或据此修改驱动、系统策略、DirectX组件。应先比较本地桌面启动结果。

## 已取得的下一阶段入口

REA在派生分析副本上查询 `0x007e8860`（磁盘cp950文本“行動力”）的引用完成，Evidence ID=`ev_c5a719dd6b736b929f8e7f822bff63d0b2da330434cb06e8ea00ded6f8d72420`，返回18处引用地址：

`0x5fdf6e, 0x5fee7b, 0x601a28, 0x6032ac, 0x605877, 0x60617f, 0x607083, 0x60943d, 0x60a190, 0x60acd5, 0x60b701, 0x60d2f8, 0x60e24b, 0x60e9c3, 0x60f6e3, 0x611981, 0x616f1a, 0x648d9c`。

完整REA证据：`rea/action_points_xrefs_2026-10-15.json`；基于这些指令地址的小范围补充反汇编：`rea/action_points_xref_contexts_2026-10-15.json`。这是明确的版本绑定研究入口，但还未确定行動力字段地址、资源归属或可用性谓词；引用地址不能直接作为函数入口。

当前状态：P0-0工具环境完成；P0-1/P0-3取得代码载体和引用线索，尚未完成业务语义确认；真实内政动作与推进回合仍未验收。生产offsets、规则与执行器未因本轮研究发生变更。

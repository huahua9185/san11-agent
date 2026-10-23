# REA：武将已行动状态（2026-10-23）

后续[预算研究](rea_action_budget_2026-10-23.md)已补强巡察经0x4A5760调用位0 setter的静态链，并接入巡察单条军团余额检查；最新384项测试通过。本报告其余内容保留当时范围，精确跨旬清除调用链仍待验证。

## 本轮结论与范围

**已确认（下述REA、历史巡察记录及本轮只读复核）**：匹配Steam繁中构建的武将记录 `General+0x124` 是位集合；位0与本次巡察中的已行动状态吻合。已接入己方 `has_acted: bool | None`，已行动者不再作为动作发起者或摘要中的可指派候选。其余位不对模型公开、不赋予语义。

**已确认**：上轮 `General+0x12A` 位1的行动状态猜测不能成立为简单布尔解释：三人跨旬后该处仍为2，桥接器 `hasActed` 已为false；REA显示它是一个5元素、步长2的取值器入口。**推测**：它属于能力经验之类的持续数值；本轮没有确认具体属性含义，未接入生产。

**已确认（操作范围）**：本轮仅读取游戏内存和已有分析载体，未执行新巡察、推进旬、载入/保存游戏、调用内部函数或写入游戏内存。独立便携REA会话已通过 `close_binary` 关闭，证据 `rea/2026-10-23/close_owned_session.json`。槽5的上轮恢复点未被本轮覆盖。

## 开发目标与问题对应

**已确认（README、`strategy_loop.py`、`boundary.py`）**：目标仍是“人类可见状态→LLM高层意图→规则战术动作→键鼠操作→状态反馈”。真实状态读取存在，模型后端、执行器与推进旬还未形成生产自动闭环。更完整的仓库事实基线见[上轮报告](rea_action_points_2026-10-22.md)。

**已确认（修改前源码）**：LegalActions只按本次调用传入的已指派集合排除人员，摘要也仅看本地指派记录和体力。上轮巡察三人的体力一直为100，但已行动状态变化。**推测**：从人工操作后的存档接手、agent重启或中途恢复时，仅凭空的调用历史可能重复选择已经行动的人员；本轮没有执行重复派遣来制造失败。

**已确认（本轮修改）**：真实标志与调用方历史同时参与排除。**待验证**：其他身份、任务、出征、多人选将等资格。`has_acted=False`只消除一项限制，不保证某条动作可以执行。

## 身份与方法

- **已确认**：原EXE SHA-256 `f2a304b118e72673f4a788b1e87322fa891ff57218a8b89e671d4f8cb6aca041`，x86、基址0x400000，PID33888；桥接器状态 `verified_readonly_structures_v1`。原始配置标识不等于所有字段都已完整验证。
- **已确认**：REA 6.4.0 / Ghidra12.1.4分析独立载体 `.rea-tools/san11-loaded-text.pe.bin`，SHA-256 `bc7f57cf26fc7a17f3e85d520543f397d93fbba7bea13a74162f32bbe6410e8f`。它仅以历史加载 `.text` 替换原文件对应节，其余节仍为磁盘字节；来源和边界见 `rea/loaded_text_provenance_2026-10-15.json`。
- **已确认**：本轮对 getter、setter、两个通用位操作器和5元素取值器的限定代码范围分别双读，均稳定且与派生载体相同。证据 `rea/2026-10-23/flag_helpers_runtime_bytes.json`。这验证这些范围的字节，不证明整个载体或全部调用者当前一致。
- **已确认（研究方法）**：先用补充Capstone字节搜索得到候选，再由REA确认函数边界、汇编、伪代码和引用。`acted_displacement_candidates.json`、`flags_124_candidates.json` 的重叠解码包含伪候选，不能逐条当作代码事实；例如 `0x49C96E` 的test是从真实mov指令内部起始的错误解码。位集合包装器使用 `add ecx,0x124`，只搜内存位移会漏掉它们。

## 静态证据索引

以下路径均相对于 `docs/rea/2026-10-23/`。地址是分析载体VA；函数名称为分析器自动命名，语义标签是本研究解释。

| 已确认的代码观察 | 文件／Evidence ID | 解释边界 |
|---|---|---|
| `0x489420` 将this+0x124和位号0传入通用读取器 | `general_flag0_getter_489420.json` / `ev_7efd43653401246a1d56cab53a603d0282dd4616a9dd0614c84ee118005275e5` | getter的伪代码推断为void，返回语义需结合汇编中未改写EAX的ret及调用者判断；不能盲信恢复的签名。 |
| `0x472680` 以 `(bit>>5)*4` 定位u32，用 `1<<(bit&31)` 测位 | `flags_472680.json` / `ev_b8f4957a2dd6339df5523a2ef44ca62b8ac32718ffef00fd20e58cd42403e2fd` | 位0对应+0x124的最低位，不是整个u32非零。 |
| `0x489E60` 调用位修改器(this+0x124,0,value)，随后调用两个通知函数 | `general_flag0_setter_489e60.json` / `ev_d67a0f154eb8738cc07b3cd0167cfc1aaa168b48a4fc3716f83e84072b88de27` | 两个通知函数的具体副作用待验证；生产代码只读，绝不调用setter。 |
| `0x472610` 非零value按mask置位，零value按反mask清位 | `bit_array_set_472610.json` / `ev_a6f265b3b140e9db51c2926842db89f8ed29d6c5b26a27bf43402ada5397b88a` | 保留其他位。 |
| `0x5B8520` 检查位0、其他人员条件和+0x158后才返回1；`0x62FB40`也将位0为0作为条件之一 | `caller_5b8520.json` / `ev_cd5de19a7dd1e1e808d68a602bb43253627e8beb2bddc6b03d09cabb5133c911`；`caller_62fb40.json` / `ev_839096ac08d0381fd6291bb3442a8620f04b72c9ee5b0fa194da49496699c66b` | **推测**为人员资格谓词；尚未证明适用于所有命令，不能把False标志当充分条件。 |
| `0x4BBC60` 在人员状态调整流程中向setter传1 | `caller_4bbc60.json` / `ev_a5995e3d4f8f25d706cfda3698891daabb6de3756026fbf45f1415c8f9d02190` | 该流程的具体游戏指令名称待验证，不能称为巡察执行函数。 |
| `0x4A19A0`、`0x4A1B40` 按人员状态/归属分支向setter传0；`0x5DC0E0` 另对3个人员ID循环清0 | `caller_4a19a0.json` / `ev_999ca780b34c42d3aa93760fca5547d4de33422a4ffd97bcbd6eda6f8d9d0c9a`；`caller_4a1b40.json` / `ev_3b5b165b7379744f6fe4d661cd5babfda79b895c509c156b60f44b10f1b67ee3`；`caller_5dc0e0.json` / `ev_8bc5e2a3057315f307c8d11855b87dc76a538cdfeb9529bbb96c395a15400f43` | 清零路径不止一个；尚未定位本次跨旬触发的确切调用链。 |
| `0x489480` 检查0≤index<5，读取this+0x12A+index*2的16位值 | `caller_489480.json` / `ev_51533d2e5e747af9b58ae4e23b0ab63debb19b79fdc775dba01f7dfdb2e482ef` | 数值语义待验证；足以纠正“该地址直接是已行动布尔值”的猜测。 |

**已确认**：getter16处引用，setter46处引用，保存于 `general_flag0_getter_xrefs.json`、`general_flag0_setter_xrefs.json`。未逐一反编译所有引用；搜索边界是当前Ghidra分析结果，间接调用可能不全。`reset_driver_58bf50.json`是某条清零路径的上游，未确认为推进旬入口。

## 动态证据与反例

**已确认**：上轮单次巡察的原始字节变化见 `../2026-10-22/patrol_general_byte_changes.json`；执行前记录原文件为 `.rea-tools/patrol_generals_before.json`。本轮将原样的记录hex与ID留存至 `general_records_before_patrol_retained.json`，附源文件SHA-256，省略原文件中编码损坏的姓名标签。姓名对应使用桥接器ID。另仅读取3名原执行者和1名对照人员，完整记录双读稳定，见 `general_flags_current.json`。下表是由上述记录生成的 `general_flags_timeline.json`，没有修改原采集文件。

| 人员ID | 巡察前+0x124 u32 | 巡察后 | 本轮复核 | +0x12A u16（前→后→复核） |
|---|---:|---:|---:|---|
| 78 夏侯淵 | 712 / 0x2C8 | 713 / 0x2C9 | 712 / 0x2C8 | 0→2→2 |
| 85 夏侯惇 | 712 / 0x2C8 | 713 / 0x2C9 | 712 / 0x2C8 | 0→2→2 |
| 343 曹操 | 760 / 0x2F8 | 761 / 0x2F9 | 760 / 0x2F8 | 0→2→2 |

**已确认**：桥接器记录三人 `hasActed` 为false→true→false，实验日期190-1-1→190-1-11；本轮复核日期仍为190-1-11、经过旬数1，当前15名己方人员均hasActed=false。来源 `../2026-10-22/live_patrol_and_turn.json` 与本轮 `general_flags_bridge_current.json`。对照人员于禁6的+0x124为648、位0为0，五个16位候选数值均0。

**限制／待验证**：本轮读取发生在上轮跨旬之后，不是清位瞬间的跟踪；桥接器也是结构解析器，不作为完全独立于内存的神谕。语义由上轮受控UI操作、字节变化、静态访问和桥接器共同支持。取消、重新载入、重启、特殊身份/任务及其他命令仍未独立覆盖；本轮没有为了重复实验新增游戏动作。

## 生产接入与验证

**已确认（源码）**：

```text
offsets.general.action_flags: +0x124, u32
 → parse_generals(): None 或 bool(flags & 1)
 → GameState.generals[].has_acted
 → filter_game_state(): 仅己方 VisibleGeneralFull.has_acted
 → RealGameStateSource.read()
   ├─ enumerate_legal_actions(): True排除；None候选附general_action_state
   └─ summarize_situation(): True排除；False/None分别显示未行动/未知
```

原始位集合不进入可见态，敌方公开武将类型没有 `has_acted` 属性。旧配置缺字段或标为unknown时保持None，不能伪造False。调用方的 `assigned_general_indices` 继续生效，即使内存尚未反映输入也能按本地历史排除。

**已确认（只读生产验收）**：`general_action_state_production_readback.json` 记录完整 `RealGameStateSource.read()` 读取己方15人、未知行动状态候选0、非己方字段泄漏false，并生成摘要。它不验证自动执行器或模型决策质量。

**已确认（离线验收）**：本轮新增10项测试，总计366项通过。覆盖0x2C8/0x2C9、0x2F8/0x2F9、其他位非零、全1标志、经验2且体力100、旧配置保持未知、己方字段边界，以及动作候选/摘要的排除和未知提示。测试通过不补足动态覆盖缺口。

## 后续研究顺序（待验证方案）

1. **P0 资格与跨旬清除链**：从已确认getter/clear调用者继续追踪具体巡察人员列表与旬结束分发；获取取消前后标志、任务状态、控制权恢复信号。接入更完整人员资格检查和 `execution_state.py`。验收：取消不置位、执行后置位、跨旬清位且事件退出；同一恢复点复现，区分任务完成导致的清位。
2. **P0 成本与共享预算**：以军团余额、城市force_id、选将人数、确认框成本与实际扣减作多城/多军团对照；接入 `domestic_rules`、LegalActions。规则不完整时保持未验证标记，不据单样本固定成本。
3. **P0 单动作执行反馈**：补充目标选择、相机/地图定位、确认框和玩家控制状态；让 `ActionExecutor` 核对目标、资源和人员差量。`StrategyLoop` 每条动作后重读并重算，避免一批旧快照；超时先核查结果，不能盲目重复确认。
4. **P0 真实推进旬**：在日期增量之外确认动画/事件结束及玩家可操作，才实现 `RealGameStateSource.advance_turn()`。本轮未定位精确跨旬调用链，不能因已找到一般清位函数就直接上线。

关键前置与验证：每次先校验EXE指纹、结构锚点和可恢复存档；版本变化即停止沿用字段。位0不是完整合法性证明，其他位不猜测。跨表读取不具备原子性，待验证方案是在稳定阶段读取并对日期/阶段前后复核。当前真实执行器和真实模型后端仍未完成。

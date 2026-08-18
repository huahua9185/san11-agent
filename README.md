# san11-agent

《三国志11：威力加强版》(san11pk.exe) LLM 代理研究项目。让 LLM 像人类玩家一样操作游戏、推进一局对局，衡量 AI 与人类玩家的决策差距。个人研究项目，游戏为本地单机离线游戏。

完整项目规格见对话记录 / 项目 wiki（本仓库暂未收录规格文档本身）。核心约束：**信息边界**——中间层必须显式过滤，只暴露人类玩家在界面上能看到的信息。M2 已经实现这一层过滤器，见下方"当前状态"。

## 当前状态：M2 — 信息边界过滤器

在 M1（内存读取与状态解析）之上加了一层白名单式过滤器，把完整 `GameState` 转换成人类可见的 `VisibleGameState`。

- [x] `VisibilitySource` 可见性来源抽象（`san11agent/visibility.py`）：`StaticVisibilitySource`（离线合成，供测试用）+ `UnresolvedVisibilitySource`（真实进程占位——探明/视野/武将发现相关内存字段还没找到，调用会显式报错，不猜测）
- [x] 白名单式人类可见状态类型（`san11agent/visible_state.py`）：默认不暴露，每个字段都要显式列出才会出现；城池/武将/势力按"是否需要额外权限查看细节"拆成 Summary/Detail、Public/Full 两级类型，而不是用 `Optional` 字段表达"看不到"
- [x] 过滤器本体（`san11agent/boundary.py`）：`filter_game_state(state, visibility) -> VisibleGameState`
- [x] 对比测试：完整 GameState fixture vs 过滤后结果逐字段断言禁止字段不泄漏 + 白名单字段集合回归测试（`tests/test_boundary.py`、`tests/test_visibility.py`）
- [ ] 真实进程场景下的实际验证——依赖 M1 的 `city.faction_id` 缺口和 M2 新发现的探明/视野/武将发现缺口，见 `docs/visibility_research.md`

**没有做**（有意，等你验证 M2 后再推进）：M3 及以后（写操作/键鼠模拟、LegalActions/Execute、LLM 接入、战斗）。CLI 暂未接入 `--visible` 之类的过滤开关——见提交报告里的说明。

## M1 — 内存读取与状态解析（已完成）

- [x] offsets 文件格式（`offsets/schema.json`）与候选偏移表（`offsets/pk_1.1_cn.json`）
- [x] 内存读取抽象层：真实进程（Win32 ReadProcessMemory）+ 离线 dump 两套实现，上层解析代码不关心用的是哪套
- [x] GameState 解析：武将表、城池表、部队表、势力表、全局参数（回合/日期）
- [x] 命令行快照工具
- [x] 单元测试（离线合成 fixture，不依赖真实游戏进程）
- [ ] **真实内存 dump 验证** —— 尚未在真实游戏进程上跑过，见下方"已知缺口"

## 目录结构

```
docs/offset_research.md      M1：内存偏移的调研报告——来源、可信度评估、所有未解决问题
docs/visibility_research.md  M2：可见性状态的调研报告——探明/视野/武将发现相关缺口
offsets/schema.json       offsets 文件的格式定义（人类可读的权威文档）
offsets/pk_1.1_cn.json    候选偏移表（未在真实进程验证过，meta.verified=false）
san11agent/
  memory.py                MemoryReader 抽象 + ProcessMemoryReader(真实进程) + DumpMemoryReader(离线dump)
  offsets.py                加载/校验 offsets json
  game_state.py             GameState 数据结构（General/City/Troop/Faction/GlobalState）—— M1，完整未过滤
  perception.py             anchor 解析 + 按 offsets 把内存字节解析成 GameState + 启动常量校验
  cli.py                     命令行快照工具
  visibility.py              M2：VisibilitySource 抽象 + StaticVisibilitySource(离线) + UnresolvedVisibilitySource(真实进程占位)
  visible_state.py           M2：白名单式人类可见状态类型（VisibleGameState 及其子结构）
  boundary.py                M2：filter_game_state()，GameState -> VisibleGameState 的过滤器本体
tests/
  test_offsets.py            offsets 文件加载与校验的单元测试
  test_perception.py          GameState 解析的单元测试（合成 fixture）
  test_cli.py                  命令行工具的单元测试
  test_visibility.py           VisibilitySource 各实现的单元测试
  test_boundary.py             M2 核心：完整 GameState fixture vs 过滤结果的对比测试 + 白名单字段回归测试
  fixtures/
    offsets_test.json          仅供测试用的最小偏移表（结构形状同生产文件，数值是编的）
    build_synthetic_dump.py    生成合成内存 dump 的脚本
    synthetic_dump.json        生成出来的合成内存 dump（build_synthetic_dump.py 的输出，已提交方便直接跑测试）
```

## ⚠ 已知缺口

**M1**（详见 docs/offset_research.md）：最重要的一条是 offsets/pk_1.1_cn.json 里 `anchor.resolution_method = "unknown"`——目前找到的开源资料只给出了"某次运行观测到的一个绝对地址"，完全没说明这个地址是编译期固定的静态地址、还是需要指针链才能定位的堆地址。在这个问题解决之前，`ProcessMemoryReader` 真实进程模式会在 `resolve_anchor()` 直接抛出 `AnchorResolutionError` 并拒绝继续——这是刻意设计，不是 bug。其余缺口：城池所属势力ID/地图坐标、当前年月日的直接字段、游戏阶段标志位——全部标记为 `unknown: true`，解析时会安静地返回 `None`，不会报错也不会编数据。

**M2**（详见 docs/visibility_research.md）：探明城池/视野内部队/已发现在野武将这三类可见性状态，在现有内存资料里完全没有找到对应字段。真实进程场景下调用 `UnresolvedVisibilitySource` 的对应方法会显式抛出 `VisibilityUnknownError`。另外，M1 里 `city.faction_id` 本身也是 unknown，导致过滤器目前无法在真实进程数据上正确判断"这座城是不是我的"——会保守地把所有城池当非己方处理（只给摘要，不泄漏，但也不好用），这两个缺口解决前，M2 过滤器在真实对局里还用不起来，但离线测试证明了过滤逻辑本身是对的。

## 运行

开发机上 `python`/`pip` 命令本身是 Windows Store 的执行别名占位符（不可用），但机器上装有独立的 Python 3.12（`%LOCALAPPDATA%\Programs\Python\Python312\python.exe`），已用它实际跑过下面的命令并确认可用（M1+M2 共 55 个测试全通过）。

```bash
pip install -r requirements-dev.txt

# 生成合成测试 dump（仓库里已经带了一份生成好的，一般不需要重新生成）
python tests/fixtures/build_synthetic_dump.py

# 跑单元测试
pytest

# 命令行工具：离线 dump 模式
python -m san11agent.cli snapshot --offsets tests/fixtures/offsets_test.json --dump tests/fixtures/synthetic_dump.json --summary

# 命令行工具：真实进程模式（预期会因为 anchor unknown 而报错退出，这是当前阶段的正确行为）
python -m san11agent.cli snapshot --offsets offsets/pk_1.1_cn.json --process san11pk.exe
```

运行时依赖：无第三方库，只用了标准库（`ctypes`/`json`/`dataclasses`/`argparse`）。测试依赖：`pytest`（见 `requirements-dev.txt`）。M2 的过滤器暂未接入 CLI（`san11agent.cli` 还没有 `--visible` 之类的开关），只能通过 Python API（`san11agent.boundary.filter_game_state`）调用——见提交报告里的说明。

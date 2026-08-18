# san11-agent

《三国志11：威力加强版》(san11pk.exe) LLM 代理研究项目。让 LLM 像人类玩家一样操作游戏、推进一局对局，衡量 AI 与人类玩家的决策差距。个人研究项目，游戏为本地单机离线游戏。

完整项目规格见对话记录 / 项目 wiki（本仓库暂未收录规格文档本身）。核心约束：**信息边界**——中间层必须显式过滤，只暴露人类玩家在界面上能看到的信息（这是 M2 的工作，M1 尚未实现）。

## 当前状态：M1 — 内存读取与状态解析

- [x] offsets 文件格式（`offsets/schema.json`）与候选偏移表（`offsets/pk_1.1_cn.json`）
- [x] 内存读取抽象层：真实进程（Win32 ReadProcessMemory）+ 离线 dump 两套实现，上层解析代码不关心用的是哪套
- [x] GameState 解析：武将表、城池表、部队表、势力表、全局参数（回合/日期）
- [x] 命令行快照工具
- [x] 单元测试（离线合成 fixture，不依赖真实游戏进程）
- [ ] **真实内存 dump 验证** —— 尚未在真实游戏进程上跑过，见下方"已知缺口"

**没有做**（有意，等你验证 M1 后再推进）：信息边界过滤（M2）、任何写操作/键鼠模拟（M3+）、LegalActions/Execute（M4）、LLM 接入（M5）、战斗（M6）。

## 目录结构

```
docs/offset_research.md   内存偏移的调研报告：来源、可信度评估、所有未解决问题
offsets/schema.json       offsets 文件的格式定义（人类可读的权威文档）
offsets/pk_1.1_cn.json    候选偏移表（未在真实进程验证过，meta.verified=false）
san11agent/
  memory.py                MemoryReader 抽象 + ProcessMemoryReader(真实进程) + DumpMemoryReader(离线dump)
  offsets.py                加载/校验 offsets json
  game_state.py             GameState 数据结构（General/City/Troop/Faction/GlobalState）
  perception.py             anchor 解析 + 按 offsets 把内存字节解析成 GameState + 启动常量校验
  cli.py                     命令行快照工具
tests/
  test_offsets.py            offsets 文件加载与校验的单元测试
  test_perception.py          GameState 解析的单元测试（合成 fixture）
  test_cli.py                  命令行工具的单元测试
  fixtures/
    offsets_test.json          仅供测试用的最小偏移表（结构形状同生产文件，数值是编的）
    build_synthetic_dump.py    生成合成内存 dump 的脚本
    synthetic_dump.json        生成出来的合成内存 dump（build_synthetic_dump.py 的输出，已提交方便直接跑测试）
```

## ⚠ 已知缺口（详见 docs/offset_research.md）

最重要的一条：**offsets/pk_1.1_cn.json 里 `anchor.resolution_method = "unknown"`**——目前找到的开源资料只给出了"某次运行观测到的一个绝对地址"，完全没说明这个地址是编译期固定的静态地址、还是需要指针链才能定位的堆地址。在这个问题解决之前，`ProcessMemoryReader` 真实进程模式会在 `resolve_anchor()` 直接抛出 `AnchorResolutionError` 并拒绝继续——这是刻意设计，不是 bug。

其余缺口：城池所属势力ID/地图坐标、当前年月日的直接字段、游戏阶段标志位——全部标记为 `unknown: true`，解析时会安静地返回 `None`，不会报错也不会编数据。

## 运行

**这台开发机上没有装 Python 解释器**（只有 Windows Store 的执行别名占位符），所以下面这些命令我还没有机会实际跑过，需要你在有 Python 的环境里验证。

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

运行时依赖：无第三方库，只用了标准库（`ctypes`/`json`/`dataclasses`/`argparse`）。测试依赖：`pytest`（见 `requirements-dev.txt`）。

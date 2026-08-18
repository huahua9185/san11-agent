# 执行层调研与设计取舍报告（M3）

> 本文档记录 M3（执行层最小链路脚手架）依赖、但目前**无法从真实游戏内存/窗口
> 里确定**的信息，以及这次新写的执行逻辑里包含哪些**未经真实游戏验证的设计
> 假设**。做法与 docs/offset_research.md（M1）、docs/visibility_research.md
> （M2）一致：找不到依据的地方明确标 unknown 并列出来，不猜测填值；新写的
> 代码逻辑里如果包含"猜"的成分（比如坐标换算公式），也明确写出来，不假装
> 它是已验证的事实。

## 0. 本次范围

用户明确要求：本次**不接触真实游戏**（游戏当前无法运行——用户机器锁屏、
人在远程，且 M1 的 GAME_DATA_BASE 锚点仍未解决），只搭建可离线测试的执行层
基础设施（InputBackend 抽象、坐标计算、轮询/超时/重试机制、归位例程、动作
日志），用假后端 + 假内存 + 可注入时钟完全离线验证。所以本文档里列出的
"缺口"，没有一项是这次尝试去解决又没解决的——而是这次的工作范围本来就不
包含"去定位这些内存字段/测量这些屏幕坐标"，全部是新识别、新记录的缺口。

## 1. 新增的内存缺口

M3 执行链路（"读城池坐标 -> 滚动地图 -> 点击 -> 轮询确认选中状态变更"）
额外依赖两组在 M1/M2 阶段都不需要的内存字段，这次为它们在
`offsets/pk_1.1_cn.json` 里新增了 `camera` 和 `selection` 两个 struct，
和 M1 其余未知字段一样标记 `unknown: true`：

1. **camera.offset_x / offset_y / zoom_level**（地图摄像机偏移/缩放）——
   `map_projection.py` 需要它才能把地图格子坐标换算成屏幕坐标。311MemoryResearch
   资料库里没有检索到跟"摄像机/地图滚动/缩放"相关的字段（这次也没有重新
   专门去查——不在本次范围内），需要之后专门定位，比如对比拖动/滚动地图
   前后的内存快照差异。
2. **selection.selected_city_index**（当前选中/高亮的城池 index）——
   `execution.py` 用它轮询确认"点击城池"这个动作是否生效。同样没有找到
   对应字段，需要之后对比点击不同城池前后的内存快照差异来定位。

这两组字段解决之前，`CitySelector.select_city()` 在真实进程场景下会在
`project_tile_to_client()`（camera 未知）处直接抛出 `MapProjectionError`，
不会用编出来的坐标点到游戏里的未知位置——这是刻意的，和 M1/M2 的一贯做法
一致。

## 2. 界面坐标缺口：ui_layout 完全没有测量数据

新增了 `ui_layout/` 目录（跟 `offsets/` 平行，但存的是屏幕像素坐标而不是
内存偏移，来源是"实际测量运行中的游戏窗口"而不是"逆向内存资料"，两者验证
方式不同故意分开成两套文件格式）。目前 `ui_layout/pk_1.1_cn.json` 里唯一的
元素 `map_viewport`（地图显示区域的矩形范围 + 每格像素尺寸）全部是
`unknown: true`——游戏无法运行，完全没有任何截图或测量数据。等游戏能跑
起来后，需要实际测量（截图量坐标，或用 Spy++/AutoIt Window Info 之类工具）
填入。

## 3. 这次新写的代码里包含的、未经验证的设计假设

以下几条不是"内存资料里没找到的事实"，而是这次为了让执行层脚手架能跑起来
自己设计的逻辑，**其正确性完全没有被真实游戏验证过**，游戏能跑之后需要
逐条确认或修正：

1. **地图坐标换算公式假设正交网格 + 线性缩放**
   （`map_projection.py` `project_tile_to_client()`）：
   `client = viewport原点 + (格子坐标 - camera偏移) * 格子像素尺寸 * 缩放比例`。
   三国志11的地图观感上更接近菱形/错位网格，如果实际如此，这个公式需要换成
   菱形坐标变换，不是简单调参数能解决的。
2. **zoom_level 的数值语义假设为线性缩放比例**（除以100得到缩放系数）：
   也可能是索引进一张预设缩放挡位表（比如只有5级缩放），需要实机确认。
3. **camera.offset_x/offset_y 的单位假设是"格子"**，不是"像素"：如果实际
   是像素单位，换算公式要相应调整（不再乘以格子像素尺寸）。
4. **地图滚动的具体输入方式假设是方向键**（`execution.py` `_nudge_map()`：
   按左右上下方向键）。也可能是鼠标拖拽、鼠标停靠屏幕边缘触发滚动、或点击
   小地图跳转。选方向键是因为它是几种可能方式里最不容易误触发游戏内其它
   功能（比如拖拽可能误选中部队）的一种，是这次脚手架阶段的默认假设，不是
   已验证的正确做法。
5. **归位例程的"已知界面"校验能力有上限**（`execution.py` `_home()`）：
   归位只能做到"连续发送 N 次 Esc"，无法真正验证退回到了哪个界面——因为
   `GlobalState.phase`（游戏阶段标志位，M1 就已知未知，见
   docs/offset_research.md 4.5节）仍然是 unknown。等这个字段解决后，归位
   例程里应该补一次"读 phase 确认确实回到了预期界面"的校验，现在这一步
   是空的。
6. **窗口查找启发式**（`window.py` `_find_main_window_for_pid()`）：用
   "属于目标 pid、可见、标题非空"的第一个顶层窗口作为游戏主窗口，没有针对
   san11pk.exe 实机验证过。如果游戏窗口是无边框全屏、或标题为空，这个启发
   式会找不到窗口。
7. **SendInput 是否会被游戏感知，未经验证**（`input_backend.py`）：
   `SendInputBackend` 注入的是标准 Win32 输入消息。如果 san11pk.exe 用
   DirectInput 或 Raw Input 直接轮询硬件状态而不是从系统消息队列取输入，
   SendInput 可能完全不起作用。备选方案是 pydirectinput 或虚拟 HID 驱动，
   需要你确认后再切换实现，这次没有做。
8. **MapProjectionError 和 UILayoutError 在"是否会被重试"上处理不同**
   （`execution.py` `select_city()`）：`camera` 字段 unknown 触发的
   `MapProjectionError`，和"滚动多次仍找不到目标格子"的 `MapProjectionError`，
   目前被同一个 `except` 分支捕获、一样会被归位重试 `max_retries` 次再放弃；
   但 `UILayoutError`（ui_layout 元素 unknown）不会被捕获，会直接从
   `select_city()` 抛出，不重试。这个区分背后的意图是"配置缺失重试也没用"，
   但严格来说 camera 字段 unknown 同样是配置缺失，目前却被归进"可重试"的
   分支里——这是可以商榷的设计取舍，见下方"需要你确认的问题"第3条。

## 4. 已经做到、可以离线验证的部分

- 轮询/超时/重试机制（`polling.py`）：可注入 Clock，测试完全不真的等待。
- 完整动作日志（`action_log.py`）：时间/意图/参数/结果/状态差异，`ActionLog`
  用的时钟和轮询用的是同一个，时间戳可以互相对照。
- InputBackend 抽象两套实现（`input_backend.py`）：`FakeInputBackend` 支持
  `on_click`/`on_key_press` 回调，可以在测试里模拟"游戏对输入做出反应"。
- 可写的离线内存镜像 `MutableMemoryReader`（`memory.py`）：仅供测试模拟内存
  值随"游戏反应"变化，明确不代表、也不应该被理解为本项目具备写真实游戏
  进程内存的能力——真实进程场景下依然只做 `ReadProcessMemory`（只读），
  游戏交互只通过键鼠输入进行。
- `CitySelector` 完整链路（`execution.py`）在假后端+假内存+可控时钟下的
  全部关键分支：目标已在视野内直接点击成功、目标在视野外先滚动再点击成功、
  点击未生效触发归位重试、重试耗尽后失败、camera/ui_layout 配置缺失时的
  报错行为区别，见 `tests/test_execution.py`。

## 5. 需要你确认的问题（汇总）

1. `camera.offset_x/offset_y/zoom_level`、`selection.selected_city_index`
   这两组内存字段完全没有定位。你是否有额外资料（CE 表、SCP 插件源码）能
   提供，或者打算之后一起对着运行中的游戏做内存搜索（对比拖动地图/点击
   不同城池前后的内存快照差异）来定位？
2. `ui_layout/pk_1.1_cn.json` 里 `map_viewport` 的屏幕坐标完全没有测量。
   游戏能运行后，是打算你截图告诉我坐标，还是我们一起用某个工具（比如
   AutoIt Window Info）现场量？
3. 第3节列出的8条设计假设，尤其是：
   - 地图网格是正交还是菱形/错位（直接决定坐标换算公式对不对）；
   - 地图滚动到底是方向键、鼠标拖拽、还是边缘滚动；
   - SendInput 这种消息注入方式游戏到底认不认——如果不认，需要换成
     pydirectinput 或虚拟 HID 驱动；
   - `MapProjectionError`（camera 未知触发的那种）要不要和 `UILayoutError`
     一样"不重试直接报错"，而不是现在这样被归位重试 `max_retries` 次；

   这几条都需要你在游戏可以实际运行后帮忙确认或指出应该怎么改，这次没有
   替你做决定。
4. 归位例程目前只能"发 Esc"，无法校验是否真的回到了已知界面——这个限制
   会一直存在，直到 `GlobalState.phase` 字段被定位（M1 遗留缺口，见
   docs/offset_research.md 第5节第5条）。是否需要提高这个缺口的优先级？

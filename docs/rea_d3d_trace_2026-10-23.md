# REA：D3D9 抓帧得到 view/projection 矩阵（2026-10-23）

## 方法

RenderDoc 不支持 D3D9，因此改用 **apitrace 14.0**（win32，含 d3d9 包装器）。

直接把 `San11WPK.exe` 放到 apitrace 下启动会以退出码 53 结束；这是 Steam
启动环境问题，不是 apitrace 本身。可行做法：

1. 把 `lib/wrappers/d3d9.dll` 复制到游戏目录；
2. 通过 Steam（appid `628070`）启动游戏；
3. 正常读档、进入地图、退出；
4. trace 写到桌面 `San11WPK.trace`；
5. 抓完后删除游戏目录里的临时 `d3d9.dll`。

本次 trace：

```text
frames = 1733
container = 3,157,093,015 bytes
actual data = 1,434,296,394 bytes
```

没有修改生产 `offsets` / `ui_layout`；没有发送键鼠输入。

## 抓到的 view/projection 矩阵

`SetTransform` 在 trace 里有大量调用。最终地图阶段出现 30 个不同 VIEW、
5 个不同 PROJECTION（矩阵随相机旋转/平移变化）。

### 经典等距视角（疑似初始地图）

```text
VIEW:
[ 0.7071068, -0.5000001, -0.4999999, 0 ]
[ 0,          0.7071065, -0.7071069, 0 ]
[-0.7071068, -0.5000001, -0.4999999, 0 ]
[ 0,          2548.687,   2981.313,  1 ]

PROJECTION:
[ 0.003011876, 0,           0,           0 ]
[ 0,           0.005354447, 0,           0 ]
[ 0,           0,           0.001468428, 0.00143472 ]
[ 0,           0,          -0.02349485,  0 ]
```

由 VIEW 反推相机位置约：

```text
(2108.1, -311.5, 3292.9)
```

### 另一组地图/城市视角

```text
VIEW:
[ 0.9999577,  0.006422902, 0.006564574, 0 ]
[ 0,          0.7147775,  -0.6993518,   0 ]
[ 0.009184078,-0.6993222, -0.7147474,   0 ]
[-3144.552,   1156.04,     1470.293,    1 ]

PROJECTION:
[ 0.004198557, 0,           0,           0 ]
[ 0,           0.007464102, 0,           0 ]
[ 0,           0,           0.002066116, 0.002 ]
[ 0,           0,          -0.03305785,  0 ]
```

由 VIEW 反推相机位置约：

```text
(3130.9, 222.1, 1880.0)
```

这些矩阵已经是真正的 D3D9 视图/投影矩阵，不再是静态猜测。

## 与城市坐标的关系

现在可以确定：

- 之前的静态 `.text` 扫描没有覆盖到这些 VIEW/PROJECTION 调用，说明它们
  来自被包装/动态分派的渲染路径；
- `+0x1C/+0x20` 的城市坐标不能直接当作世界坐标使用，仍缺少
  **世界坐标缩放/轴映射**；
- 以相机位置反推，城市坐标大概需要乘以 20 左右才接近相机位置量级，
  但这只是量级线索，不能直接写死；
- 需要把城市点、屏幕点和当前 VIEW/PROJECTION 三者对齐后，才能实现
  world-to-screen。

## 同帧 cursor/矩阵复核

第二次抓帧同时运行了 cursor/selection 探针（`probe5.jsonl`），得到：

| 城 | map 坐标 | cursor client |
|---|---:|---:|
| 濮陽 | `(120,71)` | `(1031,557)` |
| 南皮 | `(138,37)` | `(1028,576)` |
| 小沛 | `(136,77)` | `(1040,620)` |
| 平原 | `(129,54)` | `(1033,621)` |

四个点仍然挤在约 60×60 像素内。用抓到的 VIEW/PROJECTION 反投影到地图平面，
四座城的世界坐标只相差约 10 个单位：

```text
濮陽 ≈ (3301.5, 1256.7)
南皮 ≈ (3301.3, 1259.8)
小沛 ≈ (3303.1, 1266.9)
平原 ≈ (3302.3, 1267.0)
```

这说明当前悬停点**不足以确定世界坐标的轴和缩放**：它们在地图上太接近，
或者悬停落在名字/缩放后的城池图标上，而不是分散的格子中心。

## 放大后的同帧尝试

第三次抓帧时用户先把地图放大了 2~3 档，四座城的悬停点这次明显分开：

| 城 | map 坐标 | cursor client | 样本 |
|---|---:|---:|---:|
| 濮陽 | `(120,71)` | `(951,343)` | 14 |
| 南皮 | `(138,37)` | `(1015,587)` | 22 |
| 小沛 | `(136,77)` | `(728,816)` | 20 |
| 平原 | `(129,54)` | `(1033,600)` | 14 |

但这一轮 trace 出现 **1013 组 VIEW、67 组 PROJECTION**，说明缩放/移动地图
让相机在四次悬停之间变化了。逐组尝试后，**没有任何单一 VIEW/PROJECTION
能同时拟合这四个点**。

因此这轮仍然不能确定坐标轴/缩放，但已经排除了“点太近导致无法拟合”的解释；
问题变成了**矩阵与悬停点不是同一时刻**。

## 静止相机三点求解（有希望的结果）

第四次抓帧时用户保持相机静止，只悬停三座城：

| 城 | map 坐标 | cursor client |
|---|---:|---:|
| 濮陽 | `(120,71)` | `(255,733)` |
| 平原 | `(129,54)` | `(963,48)` |
| 小沛 | `(136,77)` | `(1501,1095)` |

使用 trace 中出现最多的地图 VIEW/PROJECTION：

```text
VIEW:
[ 0.999925,  0.0085805, 0.0087459, 0 ]
[ 0,         0.7138249,-0.7003241, 0 ]
[ 0.0122522,-0.7002715,-0.7137713, 0 ]
[-3203.13,  1318.281,  1966.541,   1 ]

PROJECTION:
[ 0.0020993, 0,         0,         0 ]
[ 0,         0.0037321, 0,         0 ]
[ 0,         0,         0.0010163, 0.001 ]
[ 0,         0,        -0.0162602, 0 ]
```

把屏幕点反投影到地图平面，得到：

```text
濮陽 ≈ (2936.95, 1898.09)
平原 ≈ (3084.67, 1618.93)
小沛 ≈ (3225.38, 2001.89)
```

三点仿射拟合得到：

```text
world_x = 17.7599 * map_x + 0.7128 * map_y + 755.15
world_z =  0.2750 * map_x + 16.5668 * map_y + 688.85
```

这组系数很接近“地图坐标乘以约 17~18 的均匀缩放，再加少量旋转/偏移”，
比前几轮合理得多。**这是目前最可信的坐标映射候选**，但还只有三个点，
需要第四座城做独立验证。

## 第四点验证尝试

用户换到城池较多的区域，依次悬停：

| 地点 | index | map 坐标 | cursor client | 类型 |
|---|---:|---:|---:|---|
| 鄴 | 6 | `(109,53)` | `(1704,93)` | 城 |
| 濮陽 | 11 | `(120,71)` | `(1671,959)` | 城 |
| 陳留 | 12 | `(108,79)` | `(480,808)` | 城 |
| 白馬港 | 55 | `(110,63)` | `(1414,321)` | 港口/`name=None` |

用鄴、濮陽、陳留三座城拟合：

```text
world_x = 18.225 * map_x - 0.334 * map_y + 689.65
world_z = -2.869 * map_x + 15.912 * map_y + 1181.37
```

把白馬港当第四点做验证时，世界坐标残差约 **11.9**。它很可能不是普通城池
（index 55、`name=None`），不能当第四座城使用。

因此：

- 三座城仍然给出一致的 **~18 / ~16** 世界缩放；
- 但还缺一个真正的第四座**城**做独立验证；
- 港口/特殊对象需要单独处理，不能混进城市坐标拟合。

## 4K 四城验证（通过）

用户把分辨率切到 4K，找到同时可见的四座**真实城池**，再次静止相机采集：

| 城 | map 坐标 | screen 坐标 |
|---|---:|---:|
| 平原 | `(129,54)` | `(3623,179)` |
| 小沛 | `(136,77)` | `(2825,2110)` |
| 濮陽 | `(120,71)` | `(1785,563)` |
| 陳留 | `(108,79)` | `(296,357)` |

使用 4K trace 中唯一的静态 VIEW/PROJECTION，四点拟合得到：

```text
world_x = 19.8861 * map_x + 0.2369 * map_y + 565.19
world_z =  0.2722 * map_x + 20.2024 * map_y + 520.42
```

结果：

- 世界缩放约 **20**，接近均匀缩放；
- 四点最大世界残差约 **4.7**（不到 1/4 个 tile）；
- 像素重投影误差最大约 **17px**，其余在 ~5px 以内；
- 这比之前的三点候选更可信，**四城验证通过**。

注意：4K 下 `ScreenToClient` 返回了 `None`，这次使用 `cursor_screen`；
如果窗口客户区原点不在 `(0,0)`，只会影响平移项，不影响缩放/交叉项。

## 代码落地

新增 [map_camera.py](san11agent/map_camera.py)：

- `MapCalibration` 固化四城验证得到的 map -> world 仿射；
- `CameraMatrices` 接收外部传入的 D3D9 view/projection 和屏幕尺寸；
- `project_world()` / `project_map_point()` 按行向量约定做 world-to-screen；
- `DEFAULT_MAP_CALIBRATION` 明确标为 4K 四城验证候选，不是生产 offsets。

新增 6 项离线测试（`tests/test_map_camera.py`）：已知 map->world、四城投影
误差 <20px、自定义 calibration、非法矩阵、退化投影。当前全部 **422 passed**。

仍未完成：运行时读取 VIEW/PROJECTION 矩阵。代码层已经不再依赖
`camera.offset_x/offset_y/zoom_level` 这组未确认字段。

## 运行时矩阵内存扫描（未找到）

游戏在本机 4K 下有两个窗口：

```text
D3DProxyWindow      3840x2160，实际渲染窗口，隐藏
KOEI_SAN_11_WINDOW  276x45，位于 (-32000,-32000)，被 Win32GameWindow 误选
```

这解释了 4K 下 `ScreenToClient` 返回 `None`：探针选到了最小化的 KOEI 窗口，
而不是 D3DProxyWindow。实际客户区原点仍是 `(0,0)`。

随后扫描了约 **825MB** 可读内存（private/image/mapped），按 float 和 double
查找 4K trace 里的 projection/view 分量：

- `0.0020993 / 0.0037321 / 0.0010163 / -0.0162602` 均未找到；
- view 的 `2573.048 / 3195.677` 也未找到；
- 只找到一些无关的 `0.7071069 / -0.4999996` 常量。

结论：当前游戏没有把 4K 矩阵以普通 4x4 float/double 块放在可读内存里；
要么矩阵是运行时计算/保存在 D3D 设备内部状态，要么当前视角的 projection
与 trace 里的值不同。仅靠内存扫描无法完成运行时读取。

## 运行时矩阵已打通（代理 DLL）

新增研究用 32-bit d3d9 代理：

- `tools/d3d9_camera_proxy/d3d9_proxy.cpp`；
- 转发 `Direct3DCreate9` 到 SysWOW64 的真实 d3d9.dll；
- 等待 `San11WPK.exe+0x6AD6F74`（VA `0x6ED6F74`）出现设备指针；
- patch `IDirect3DDevice9` vtable 的 `SetTransform`（index 44）；
- 把 VIEW/PROJECTION 写入 `Local\San11Camera`。

实机读到：

```text
version 4302
view_sequence 2151
projection_sequence 2151
view[0]  = 0.7071069478988647
proj[0]  = 0.0020992786157876253
```

与 4K trace 的矩阵一致。

新增 [camera_reader.py](san11agent/camera_reader.py)：

- 解析 140 字节共享内存；
- `CameraSnapshot.as_camera(width, height)` 直接得到 `CameraMatrices`；
- 共享内存缺失/全零时抛 `CameraReadError`，不会拿零矩阵继续算。

新增 4 项离线测试（`tests/test_camera_reader.py`）。当前 **422 passed**。
注意：代理是研究工具，编译产物不提交；使用后要删除游戏目录里的
`d3d9.dll`。

## CitySelector 接入

`CitySelector` 新增可选 `live_camera` 回调：

```python
CitySelector(..., live_camera=lambda: snapshot.as_camera(3840, 2160))
```

有回调时：

- 不读旧 `CameraState`；
- 用 `project_map_point()` 直接算目标屏幕坐标；
- 目标在屏幕外时明确抛 `MapProjectionError`，不猜边缘平移方向；
- 原有离线/旧字段路径保留为 fallback。

新增 3 项测试（`tests/test_live_city_selector.py`）：live 投影成功、屏幕外
拒绝、camera 读取异常不静默。当前全部 **422 passed**。

## 实机 live hover 验证

2026-10-23 在游戏地图内用真实 `SendInputBackend` 执行了一次 live hover：

```text
目标：平原 index=4 map=(129,54)
projected client=(3627.73, 183.21)
selection before=None
selection after=4
```

只发送了鼠标移动，没有点击；`home_esc_presses=0`，避免额外 Esc 改变界面。
selection reader 确认 `selected_city_index` 从 `None` 变为 `4`。

证据：`docs/rea/2026-10-23-live-hover.json`

## 下一步

1. 把 `camera_reader` + `map_camera` 接入 `CitySelector`，替换旧的二维
   等距 `map_projection` 路径；
2. 修正 4K 下客户区原点，避免 `cursor_screen` 与 client 混用；
3. 用另一组城市/缩放做独立回归，确认 `DEFAULT_MAP_CALIBRATION` 是否稳定；
4. 矩阵读取可用后，把 `map_camera.py` 接入 `CitySelector` 的屏幕坐标
   计算，不再依赖 `camera.offset_x/offset_y/zoom_level` 这组未确认字段。

证据：

- `docs/rea/2026-10-23-d3d9-trace/trace_info.json`
- `docs/rea/2026-10-23-d3d9-trace/settransform_summary.json`
- `docs/rea/2026-10-23-d3d9-trace/settransform_summary2.json`
- `docs/rea/2026-10-23-d3d9-trace/settransform_summary3.json`
- `docs/rea/2026-10-23-d3d9-trace/same_frame_probe.json`
- `docs/rea/2026-10-23-d3d9-trace/same_frame_probe2.json`
- `docs/rea/2026-10-23-d3d9-trace/trace_info2.json`
- `docs/rea/2026-10-23-d3d9-trace/trace_info3.json`
- `docs/rea/2026-10-23-d3d9-trace/trace_info4.json`
- `docs/rea/2026-10-23-d3d9-trace/settransform_summary4.json`
- `docs/rea/2026-10-23-d3d9-trace/settransform_summary5.json`
- `docs/rea/2026-10-23-d3d9-trace/settransform_summary6.json`
- `docs/rea/2026-10-23-camera-calibration/matrix_memory_scan.json`
- `tools/d3d9_camera_proxy/d3d9_proxy.cpp`
- `tools/d3d9_camera_proxy/README.md`
- `san11agent/camera_reader.py`
- `tests/test_camera_reader.py`
- `tests/test_live_city_selector.py`
- `docs/rea/2026-10-23-d3d9-trace/camera_solve.json`
- `docs/rea/2026-10-23-d3d9-trace/camera_solve3.json`
- `docs/rea/2026-10-23-d3d9-trace/trace_info6.json`
- `docs/rea/2026-10-23-d3d9-trace/camera_solve2.json`
- `docs/rea/2026-10-23-d3d9-trace/trace_info5.json`
- `docs/rea/2026-10-23-d3d9-trace/settransform_dump.txt`

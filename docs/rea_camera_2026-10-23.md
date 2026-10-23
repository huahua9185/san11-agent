# REA：camera 标定与 3D 投影问题（2026-10-23）

## 结论

**已确认**：之前读到的 `1462×914` 客户区不是游戏真实分辨率，而是探针进程
没有 DPI 感知、在 Windows 175% 缩放下读到的虚拟化坐标。给
[camera 探针](tools/probe_camera.py) 加上 `ensure_dpi_awareness()` 后：

```text
client size = 2560 × 1600
ui_layout.map_viewport = (471, 12, 1772, 1542)   # 现在落在客户区内
```

所以 `ui_layout` 的 2560×1600 基准本身是对的；之前“分辨率不匹配”的结论
需要修正为 **DPI 感知问题**。

但 camera 仍然没有解决。DPI 感知后，用户点击濮陽/南皮/小沛/平原，稳定
采集到：

| 城 | map 坐标候选 | cursor client |
|---|---:|---:|
| 濮陽 | `(120,71)` | `(1217,740)` |
| 南皮 | `(138,37)` | `(1287,810)` |
| 小沛 | `(136,77)` | `(1291,850)` |
| 平原 | `(129,54)` | `(1303,824)` |

用 `map_projection.py` 的二维等距公式拟合：

- 两两算出的 `zoom` 符号和量级不一致；
- 仿射拟合最大残差约 **34px**；
- 拟合矩阵不满足等距结构的列关系。

因此，**当前二维等距投影假设无法解释这四个屏幕点**。可能原因：

1. 游戏地图实际是**3D 透视/地形视图**，不是平面等距网格；
2. 点击点落在城池名字/菜单锚点，而不是格子中心；
3. `+0x1C/+0x20` 不是世界地图投影坐标，或语义仍不完整。

仅靠“城市地图坐标 + 鼠标点”反推 camera 这条路，在当前数据下不可靠。

## 影响

- `camera.offset_x/offset_y/zoom_level` 仍未定位；
- `map_projection.py` 的二维等距公式需要重新评估，不能直接用于真实点击；
- `CitySelector` 的坐标换算、真实键鼠执行仍被 camera/投影阻塞；
- selection 的纯悬停读取不受影响；
- 未修改生产 `offsets` 或 `ui_layout`。

## 下一步建议

1. **暂停用城市坐标反推 camera**，避免把 3D 透视误判成二维等距误差；
2. 转向静态 REA：找 D3D 视图/投影矩阵、地图渲染调用链，或游戏自己的
   世界坐标到屏幕坐标函数；
3. 如果短期目标是执行器，可先评估“城池列表/菜单选择”这条不依赖地图
   坐标的路径；
4. 任何新的坐标探针必须先调用 `ensure_dpi_awareness()`，否则在缩放环境下
   坐标会再次出错。

证据：

- [layout_mismatch.json](docs/rea/2026-10-23-camera-calibration/layout_mismatch.json)
- [calibration_summary.json](docs/rea/2026-10-23-camera-calibration/calibration_summary.json)
- [probe4.jsonl](docs/rea/2026-10-23-camera-calibration/probe4.jsonl)

# d3d9 camera proxy（研究工具）

32-bit D3D9 代理 DLL，用于把 San11WPK 的实时 `D3DTS_VIEW` /
`D3DTS_PROJECTION` 矩阵写入命名共享内存 `Local\San11Camera`。

它只用于研究/标定，不是生产运行时依赖；编译产物不提交到仓库。

## 构建

需要 i686 MinGW（不是 64-bit 工具链）：

```powershell
g++ -m32 -O2 -shared -static-libgcc -static-libstdc++ `
    -Wl,--kill-at d3d9_proxy.cpp -o d3d9.dll `
    -ld3d9 -lole32 -luuid
```

`--kill-at` 很重要：游戏导入的是未修饰的 `Direct3DCreate9`，不是
`Direct3DCreate9@4`。

## 使用

1. 把编译出的 `d3d9.dll` 复制到 `San11WPK.exe` 同目录；
2. 通过 Steam 或带 `SteamAppId=628070` 的环境启动游戏；
3. 进入地图后，Python 用 `san11agent.camera_reader.read_camera_mapping()` 读取；
4. 退出游戏后删除该 `d3d9.dll`，恢复原状。

代理会：

- 转发 `Direct3DCreate9` 到 `C:\Windows\SysWOW64\d3d9.dll`；
- 等待 `San11WPK.exe+0x6AD6F74`（绝对地址 `0x6ED6F74`）出现设备指针；
- patch `IDirect3DDevice9` vtable 的 `SetTransform`（index 44）；
- 把 state 2/3 的 4×4 矩阵写入共享内存。

## 共享内存布局

```text
LONG   version              offset 0
DWORD  view_sequence        offset 4
DWORD  projection_sequence  offset 8
float  view[16]             offset 12
float  projection[16]       offset 76
total 140 bytes
```

## 版本绑定

- 设备全局 RVA：`0x6AD6F74`（image base `0x400000` → VA `0x6ED6F74`）；
- vtable index 44：`IDirect3DDevice9::SetTransform`。

换 EXE 版本/加壳方式后这些都必须重新确认；不要把它当成跨版本事实。

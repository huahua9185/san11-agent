"""生成 tests/fixtures/synthetic_execution_dump.json —— 配合
tests/fixtures/offsets_execution_test.json 使用的合成内存 dump，供 CLI 的
select-city 子命令做离线冒烟测试（--dump 模式，只读，不会真的变化，所以
CLI 测试只验证"链路能跑起来、轮询超时后能正常报错退出"，不验证点击成功——
那需要能写的 MutableMemoryReader，已经在 tests/test_execution.py 里覆盖过。

运行方式（从仓库根目录）：
    python tests/fixtures/build_synthetic_execution_dump.py
"""
from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

GAME_DATA_BASE = 0x1000
BUFFER_SIZE = 0x30
buf = bytearray(BUFFER_SIZE)


def write_i32(offset: int, value: int) -> None:
    buf[offset:offset + 4] = struct.pack("<i", value)


# ---- camera (base_offset 0x0) ----
write_i32(0x00, 0)    # offset_x
write_i32(0x04, 0)    # offset_y
write_i32(0x08, 100)  # zoom_level

# ---- selection (base_offset 0x20) ----
write_i32(0x20, -1)  # selected_city_index：初始未选中任何城池


def main() -> None:
    out = {
        "module_base": "0x00400000",
        "regions": [
            {
                "address": hex(GAME_DATA_BASE),
                "data_base64": base64.b64encode(bytes(buf)).decode("ascii"),
            }
        ],
    }
    out_path = Path(__file__).parent / "synthetic_execution_dump.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(buf)} bytes region)")


if __name__ == "__main__":
    main()

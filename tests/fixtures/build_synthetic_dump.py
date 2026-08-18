"""生成 tests/fixtures/synthetic_dump.json —— 配合 offsets_test.json 使用的合成内存 dump。

这不是真实游戏内存，是按 offsets_test.json 里的字段布局手工拼出来的字节，
用来验证"MemoryReader -> perception.parse_game_state -> GameState"这条链路本身是对的。
等拿到用户提供的真实内存 dump 后，会另外写一个转换脚本产出同样格式的 json，
不会复用这份合成数据。

运行方式（从仓库根目录）：
    python tests/fixtures/build_synthetic_dump.py
"""
from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

GAME_DATA_BASE = 0x1000

# 总大小要覆盖到最大偏移的结构体末尾：faction base 0x800 + 1*0x20 = 0x820
BUFFER_SIZE = 0x900
buf = bytearray(BUFFER_SIZE)


def write(offset: int, data: bytes) -> None:
    buf[offset:offset + len(data)] = data


def write_i32(offset: int, value: int) -> None:
    write(offset, struct.pack("<i", value))


def write_u16(offset: int, value: int) -> None:
    write(offset, struct.pack("<H", value))


def write_i16(offset: int, value: int) -> None:
    write(offset, struct.pack("<h", value))


def write_u8(offset: int, value: int) -> None:
    write(offset, struct.pack("<B", value))


def write_fixed_str(offset: int, size: int, text: str, encoding: str = "gbk") -> None:
    raw = text.encode(encoding)
    assert len(raw) < size, "字符串塞不进定长字段"
    write(offset, raw + b"\x00" * (size - len(raw)))


# ---- global (base_offset 0x0) ----
G = 0x0
write_i32(G + 0x00, 3)      # scenario_id
write_i32(G + 0x04, 190)    # start_year
write_i32(G + 0x08, 1)      # start_month
write_i32(G + 0x0C, 1)      # start_day
write_i32(G + 0x10, 0)      # emperor_general_id
write_i32(G + 0x14, 2)      # difficulty
write_i32(G + 0x18, 1)      # death_setting
write_i32(G + 0x1C, 7)      # current_xun

# ---- general (base_offset 0x100, struct_size 0x60, count 2) ----
GEN = 0x100
GEN_SIZE = 0x60


def write_general(i: int, name: str, faction_id: int, loyalty: int, stats: bytes) -> None:
    base = GEN + i * GEN_SIZE
    write_fixed_str(base + 0x00, 8, name)
    write_i32(base + 0x08, 100 + i)   # portrait_id
    write_i32(base + 0x0C, 0)          # gender
    write_i32(base + 0x10, 189)        # debut_year
    write_i32(base + 0x14, 155)        # birth_year
    write_i32(base + 0x18, -1)         # death_year (未死亡)
    write_i32(base + 0x1C, i)          # force_id
    write_i32(base + 0x20, faction_id)
    write_i32(base + 0x24, 0)          # location
    write_i32(base + 0x28, 1)          # identity
    write_i32(base + 0x2C, 5)          # office
    write_u16(base + 0x30, loyalty)
    write_u16(base + 0x32, 10)         # merit
    write(base + 0x34, stats)          # base_stats (5 bytes)
    write_i32(base + 0x3C, -1)         # special_skill_id
    write_u8(base + 0x40, 100)         # stamina
    write_i32(base + 0x44, 0)          # garrison_count
    write_i32(base + 0x48, 1)          # health
    write(base + 0x4C, bytes([90, 91, 92, 93, 94]))   # display_stats_wound
    write(base + 0x51, bytes([96, 97, 98, 99, 100]))  # display_stats_normal


write_general(0, "曹操", faction_id=0, loyalty=100, stats=bytes([96, 72, 90, 94, 96]))
write_general(1, "刘备", faction_id=1, loyalty=100, stats=bytes([78, 75, 70, 70, 100]))

# ---- city (base_offset 0x300, struct_size 0x60, count 2) ----
CITY = 0x300
CITY_SIZE = 0x60


def write_city(i: int, name: str, gold: int, food: int, troops: int) -> None:
    base = CITY + i * CITY_SIZE
    write_fixed_str(base + 0x00, 8, name)
    write_i32(base + 0x08, i)                       # province
    write(base + 0x0C, struct.pack("<6i", -1, -1, -1, -1, -1, -1))  # adjacent_cities
    write_i32(base + 0x24, i)                        # governor_general_id
    write_i32(base + 0x28, i)                         # force_id
    write_i32(base + 0x2C, 5000)                      # troop_capacity
    write_i32(base + 0x30, troops)
    write_i32(base + 0x34, gold)
    write_i32(base + 0x38, food)
    write_u8(base + 0x3C, 10)   # trade_price
    write_u8(base + 0x3D, 1)    # has_merchant
    write_u8(base + 0x3E, 80)   # morale
    write_u8(base + 0x3F, 90)   # security
    write_i32(base + 0x40, 0)   # policy
    write_i32(base + 0x44, 0)   # target
    write_i32(base + 0x48, 10)  # development_land_count
    write_i32(base + 0x4C, 8)   # developed_land_count
    write_i16(base + 0x50, 12)  # domestic_land_x
    write_i16(base + 0x52, 34)  # domestic_land_y


write_city(0, "许昌", gold=5000, food=8000, troops=3000)
write_city(1, "成都", gold=4000, food=7000, troops=2500)

# ---- troop (base_offset 0x500, struct_size 0xA0, count 2) ----
TROOP = 0x500
TROOP_SIZE = 0xA0


def write_troop(i: int, commander_id: int, faction_id: int, x: int, y: int, count: int) -> None:
    base = TROOP + i * TROOP_SIZE
    write_i32(base + 0x00, 0)               # type
    write_i32(base + 0x04, commander_id)
    write_i32(base + 0x08, -1)              # vice1
    write_i32(base + 0x0C, -1)              # vice2
    write_u16(base + 0x10, count)
    write_u8(base + 0x12, 80)               # morale
    write_i32(base + 0x14, 100)             # gold
    write_i32(base + 0x18, 200)             # food
    write_i32(base + 0x1C, 0)               # status
    write_i32(base + 0x20, 0)               # status_duration
    write_i16(base + 0x24, x)
    write_i16(base + 0x26, y)
    write_i32(base + 0x28, 0)               # has_acted
    write_i32(base + 0x2C, faction_id)
    write(base + 0x30, bytes(96))           # equipment_slots
    write_i32(base + 0x90, 1)               # current_unit_type
    write(base + 0x94, bytes([80, 60, 70, 65, 75]))  # display_stats
    write_u8(base + 0x99, 55)   # display_attack
    write_u8(base + 0x9A, 45)   # display_defense
    write_u8(base + 0x9B, 30)   # display_construction


write_troop(0, commander_id=0, faction_id=0, x=50, y=60, count=3000)
write_troop(1, commander_id=1, faction_id=1, x=10, y=20, count=2500)

# ---- faction (base_offset 0x800, struct_size 0x20, count 1) ----
FACTION = 0x800
write_i32(FACTION + 0x00, 0)   # ruler_general_id
write_i32(FACTION + 0x04, -1)  # advisor_general_id
write(FACTION + 0x08, bytes([1, 2, 3, 4]))  # relations_table
write_i32(FACTION + 0x0C, 1)   # player_marker
write_i32(FACTION + 0x10, -1)  # researching_tech_id
write_u16(FACTION + 0x14, 50)  # skill_points


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
    out_path = Path(__file__).parent / "synthetic_dump.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(buf)} bytes region)")


if __name__ == "__main__":
    main()

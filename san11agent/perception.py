"""把 MemoryReader 里的原始字节，按 offsets 配置解析成 GameState。

这里刻意分成两步：
1. resolve_anchor()：算出 GAME_DATA_BASE 的绝对地址。
2. parse_*()：从 GAME_DATA_BASE 出发，用 offsets 里记录的相对偏移读出各个结构体数组。

第 1 步是当前 M1 最大的坑：pk_1.1_cn.json 里 anchor.resolution_method="unknown"，
意味着对真实进程调用 resolve_anchor() 会直接抛 AnchorResolutionError，
不会用一个未经验证的绝对地址去猜。测试用的 offsets 文件会显式声明
resolution_method="static_rva" 或 "fixed_for_fixture" 来让解析链路可测。
"""
from __future__ import annotations

from .game_state import City, Faction, GameState, General, GlobalState, Troop
from .memory import MemoryReader
from .offsets import FieldSpec, OffsetsConfig, StructSpec


class AnchorResolutionError(Exception):
    """anchor.resolution_method 是 unknown，或者解析过程本身失败。"""


class ValidationError(Exception):
    """启动时的常量校验没通过——很可能是偏移表用错了版本，或者锚点解析错了。"""


def resolve_anchor(reader: MemoryReader, offsets: OffsetsConfig) -> int:
    anchor = offsets.anchor
    method = anchor.resolution_method

    if method == "unknown":
        raise AnchorResolutionError(
            "offsets 文件里 anchor.resolution_method 是 'unknown'：还没有任何已知的、"
            "可靠的方法能从模块基址算出 GAME_DATA_BASE。这不是代码 bug，是数据缺口——"
            "需要你提供指针链（比如用 Cheat Engine 做一次指针扫描）或确认其它定位方法，"
            "详见 docs/offset_research.md 第5节。程序拒绝用一个未经验证的绝对地址继续。"
        )

    if method == "static_rva":
        if anchor.rva is None:
            raise AnchorResolutionError("resolution_method=static_rva 但没有给 rva")
        return reader.module_base + anchor.rva

    if method == "pointer_chain":
        if not anchor.pointer_chain:
            raise AnchorResolutionError("resolution_method=pointer_chain 但没有给 pointer_chain")
        chain = anchor.pointer_chain
        address = reader.module_base + chain[0]
        for extra_offset in chain[1:]:
            address = reader.read_u32(address) + extra_offset
        return address

    if method == "fixed_for_fixture":
        if anchor.fixture_absolute_address is None:
            raise AnchorResolutionError("resolution_method=fixed_for_fixture 但没有给 fixture_absolute_address")
        return anchor.fixture_absolute_address

    raise AnchorResolutionError(f"未知的 resolution_method={method!r}")


def _read_field(reader: MemoryReader, record_address: int, spec: FieldSpec):
    """按 FieldSpec.type 读取一个字段；unknown 字段直接返回 None，不读内存。"""
    if spec.unknown or spec.offset is None:
        return None
    address = record_address + spec.offset
    t = spec.type
    if t == "u8":
        return reader.read_u8(address)
    if t == "i8":
        return reader.read_i8(address)
    if t == "u16":
        return reader.read_u16(address)
    if t == "i16":
        return reader.read_i16(address)
    if t == "u32":
        return reader.read_u32(address)
    if t == "i32":
        return reader.read_i32(address)
    if t == "f32":
        return reader.read_f32(address)
    if t == "fixed_str":
        return reader.read_fixed_str(address, spec.size)
    if t == "bytes":
        return reader.read_bytes(address, spec.size)
    if t == "i32_array":
        return reader.read_i32_array(address, spec.array_len)
    raise ValueError(f"字段 {spec.name!r} 的类型 {t!r} 不支持")


def _record_address(struct_spec: StructSpec, game_data_base: int, index: int) -> int:
    if struct_spec.base_offset is None:
        raise AnchorResolutionError(
            f"结构体 {struct_spec.name!r} 没有唯一的 base_offset（可能只有 candidates），"
            f"不能直接解析，需要先确认用哪个候选值。"
        )
    if struct_spec.struct_size is None:
        raise AnchorResolutionError(f"结构体 {struct_spec.name!r} 没有 struct_size")
    array_base = game_data_base + struct_spec.base_offset
    return array_base + index * struct_spec.struct_size


def parse_global_state(reader: MemoryReader, offsets: OffsetsConfig, game_data_base: int) -> GlobalState:
    spec = offsets.struct("global")
    base = game_data_base + (spec.base_offset or 0)
    f = {name: _read_field(reader, base, field_spec) for name, field_spec in spec.fields.items()}
    return GlobalState(
        scenario_id=f["scenario_id"],
        start_year=f["start_year"],
        start_month=f["start_month"],
        start_day=f["start_day"],
        emperor_general_id=f["emperor_general_id"],
        difficulty=f["difficulty"],
        death_setting=f["death_setting"],
        current_xun=f["current_xun"],
        current_year=f.get("current_year"),
        current_month=f.get("current_month"),
        current_day=f.get("current_day"),
        phase=f.get("phase"),
    )


def parse_generals(reader: MemoryReader, offsets: OffsetsConfig, game_data_base: int) -> list[General]:
    spec = offsets.struct("general")
    result = []
    for i in range(spec.count or 0):
        addr = _record_address(spec, game_data_base, i)
        f = {name: _read_field(reader, addr, fs) for name, fs in spec.fields.items()}
        result.append(General(
            index=i,
            name=f["name"],
            portrait_id=f["portrait_id"],
            gender=f["gender"],
            debut_year=f["debut_year"],
            birth_year=f["birth_year"],
            death_year=f["death_year"],
            force_id=f["force_id"],
            faction_id=f["faction_id"],
            location=f["location"],
            identity=f["identity"],
            office=f["office"],
            loyalty=f["loyalty"],
            merit=f["merit"],
            base_stats=f["base_stats"],
            special_skill_id=f["special_skill_id"],
            stamina=f["stamina"],
            garrison_count=f["garrison_count"],
            health=f["health"],
            display_stats_wound=f["display_stats_wound"],
            display_stats_normal=f["display_stats_normal"],
        ))
    return result


def parse_cities(reader: MemoryReader, offsets: OffsetsConfig, game_data_base: int) -> list[City]:
    spec = offsets.struct("city")
    result = []
    for i in range(spec.count or 0):
        addr = _record_address(spec, game_data_base, i)
        f = {name: _read_field(reader, addr, fs) for name, fs in spec.fields.items()}
        result.append(City(
            index=i,
            name=f["name"],
            province=f["province"],
            adjacent_cities=f["adjacent_cities"],
            governor_general_id=f["governor_general_id"],
            force_id=f["force_id"],
            troop_capacity=f["troop_capacity"],
            troops=f["troops"],
            gold=f["gold"],
            food=f["food"],
            trade_price=f["trade_price"],
            has_merchant=f["has_merchant"],
            morale=f["morale"],
            security=f["security"],
            policy=f["policy"],
            target=f["target"],
            development_land_count=f["development_land_count"],
            developed_land_count=f["developed_land_count"],
            domestic_land_x=f["domestic_land_x"],
            domestic_land_y=f["domestic_land_y"],
            faction_id=f.get("faction_id"),
            map_x=f.get("map_x"),
            map_y=f.get("map_y"),
        ))
    return result


def parse_troops(reader: MemoryReader, offsets: OffsetsConfig, game_data_base: int) -> list[Troop]:
    spec = offsets.struct("troop")
    result = []
    for i in range(spec.count or 0):
        addr = _record_address(spec, game_data_base, i)
        f = {name: _read_field(reader, addr, fs) for name, fs in spec.fields.items()}
        result.append(Troop(
            index=i,
            type=f["type"],
            commander_general_id=f["commander_general_id"],
            vice_general_1_id=f["vice_general_1_id"],
            vice_general_2_id=f["vice_general_2_id"],
            troop_count=f["troop_count"],
            morale=f["morale"],
            gold=f["gold"],
            food=f["food"],
            status=f["status"],
            status_duration=f["status_duration"],
            x=f["x"],
            y=f["y"],
            has_acted=f["has_acted"],
            faction_id=f["faction_id"],
            equipment_slots=f["equipment_slots"],
            current_unit_type=f["current_unit_type"],
            display_stats=f["display_stats"],
            display_attack=f["display_attack"],
            display_defense=f["display_defense"],
            display_construction=f["display_construction"],
        ))
    return result


def parse_factions(reader: MemoryReader, offsets: OffsetsConfig, game_data_base: int) -> list[Faction]:
    spec = offsets.struct("faction")
    result = []
    for i in range(spec.count or 0):
        addr = _record_address(spec, game_data_base, i)
        f = {name: _read_field(reader, addr, fs) for name, fs in spec.fields.items()}
        result.append(Faction(
            index=i,
            ruler_general_id=f["ruler_general_id"],
            advisor_general_id=f["advisor_general_id"],
            relations_table=f["relations_table"],
            player_marker=f["player_marker"],
            researching_tech_id=f["researching_tech_id"],
            skill_points=f["skill_points"],
        ))
    return result


def validate_constants(offsets: OffsetsConfig, state: GameState) -> None:
    """启动时的常量校验：拿解析出来的数据和 offsets.validation 里的预期范围对一下。

    这是"尽力而为"版本——见 docs/offset_research.md 关于校验缺口的说明：
    我们手上没有一个能直接读到的、独立于结构体本身的"武将总数/剧本名"常量，
    所以校验主要是做合理性区间检查，不是精确比对。校验不通过时明确报错，
    不静默继续。
    """
    rules = offsets.validation
    errors = []

    expected_generals = rules.get("expected_general_count")
    if expected_generals is not None and len(state.generals) != expected_generals:
        errors.append(f"武将数量 {len(state.generals)} != 预期 {expected_generals}")

    expected_cities = rules.get("expected_city_count")
    if expected_cities is not None and len(state.cities) != expected_cities:
        errors.append(f"城池数量 {len(state.cities)} != 预期 {expected_cities}")

    expected_factions = rules.get("expected_faction_count")
    if expected_factions is not None and len(state.factions) != expected_factions:
        errors.append(f"势力数量 {len(state.factions)} != 预期 {expected_factions}")

    scenario_range = rules.get("scenario_id_range")
    if scenario_range and not (scenario_range[0] <= state.global_state.scenario_id <= scenario_range[1]):
        errors.append(f"剧本编号 {state.global_state.scenario_id} 超出预期范围 {scenario_range}")

    year_range = rules.get("start_year_range")
    if year_range and not (year_range[0] <= state.global_state.start_year <= year_range[1]):
        errors.append(f"开局年份 {state.global_state.start_year} 超出预期范围 {year_range}")

    if errors:
        raise ValidationError(
            "启动校验失败，读到的数据和预期不符，很可能是偏移表版本不对或锚点解析错误：\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def parse_game_state(reader: MemoryReader, offsets: OffsetsConfig, *, validate: bool = True) -> GameState:
    game_data_base = resolve_anchor(reader, offsets)
    state = GameState(
        global_state=parse_global_state(reader, offsets, game_data_base),
        generals=parse_generals(reader, offsets, game_data_base),
        cities=parse_cities(reader, offsets, game_data_base),
        troops=parse_troops(reader, offsets, game_data_base),
        factions=parse_factions(reader, offsets, game_data_base),
    )
    if validate:
        validate_constants(offsets, state)
    return state

"""把"这条记录属于哪个政治势力"这个问题，从 force_id 翻译成真正的势力 index。

## 为什么需要这一层

直觉上 `General.faction_id` / `Troop.faction_id` 这两个字段就该直接是"势力ID"
（原始资料也是这么标注的，confidence 一度是 high）。**但 2026-08-18 的实机验证
证明这个理解是错的**，见 docs/offset_research.md 第 7.9 / 7.10 节：

- 抽样 9 位驻守城池的武将，`General.faction_id` **精确等于他所在城池的 index**
  （比如張燕 faction_id=3，而 3 正是南皮的城池 index）。这 9 位全部效忠张角，
  不可能分属 9 个不同势力。
- 统计全部 1100 位武将的 `faction_id` 取值分布：413 位是 -1（在野），其余的
  分布形状对应"42 座城池各驻若干人"，而不是"十几个势力各领几十上百人"。
- `Troop.faction_id` 更离谱：1100 条部队记录里 1000 条是 -1，包括已确认真实
  活跃的 troop[6]（裴元紹隊）。

也就是说 `xxx.faction_id == player_faction_id` 这个"是不是我自己的"判断，在真实
内存下**几乎永远不会为真**——这不是"字段还没验证所以保守拒绝"的安全退化，是
比较的前提本身就不成立。

## 正确的路径

真正的势力归属要走"军团"(Force) 这一跳，这是 2026-08-18 才第一次在真实进程上
解析出来的结构体：

    General/City.force_id  ->  Force[force_id].faction_id  ->  Faction[faction_id]

## 各条路径的验证状态（重要，不要当成都一样可靠）

- `of_city()`：**已验证**。12 座城池交叉核对，全部给出符合黄巾之乱剧本的历史
  归属（北平→公孫瓚、薊→劉虞、南皮/平原/小沛/濮陽→張角、晉陽→丁原、鄴→何進、
  下邳→孫堅）。
- `of_general()`：**已验证**。9 位武将交叉核对，其中韓忠 force_id=6 解析出的
  势力与游戏内花名册"軍團"列显示的"2張角"吻合。
- `of_troop()`：**未验证**。Troop 结构体里根本没有 force_id 字段，只能绕两跳
  （commander_general_id -> General.force_id -> Force.faction_id）。这条路本身
  没有在实机上核对过，而且指挥官阵亡/换将等情况下是否仍然成立也不清楚。
  下次上机验证待办见 docs/verification_checklist.md 第 4.4 项。

解析不出来时一律返回 `None`，绝不猜测。调用方拿 `None` 和 `player_faction_id`
比较必然为假，也就是自动 fail-closed（宁可把己方误判成非己方而少给信息，也不
把非己方误判成己方而泄漏信息）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .game_state import City, Force, GameState, General, Troop

# 在野/无势力归属的哨兵值。2026-08-18 实机确认：1100 位武将里 413 位的
# faction_id 恰好是 -1，数量级与"黄巾之乱开局大部分历史人物尚未登场"吻合。
# 注意这里用的是 faction_id 而不是 force_id——"是不是在野"和"属于哪个势力"
# 是两个不同的问题，前者这个字段是可靠的，后者不可靠（见模块文档）。
FREE_AGENT_FACTION_ID = -1

# force_id 为该值表示"不属于任何军团"（比如无人管辖的空城）。
NO_FORCE_ID = -1


@dataclass(frozen=True)
class FactionResolver:
    """按 force_id -> faction_id 的映射回答"这条记录属于哪个势力"。

    用 `FactionResolver.from_state()` 构造。映射为空时（比如 offsets 文件没有
    定义 force 结构体、或者游戏还没加载存档）所有查询都返回 None，调用方会
    自动 fail-closed，不会误判归属。
    """

    force_to_faction: dict[int, int]
    general_force_by_index: dict[int, int]

    @classmethod
    def from_state(cls, state: GameState) -> "FactionResolver":
        return cls.from_parts(state.forces, state.generals)

    @classmethod
    def from_parts(cls, forces: list[Force], generals: list[General]) -> "FactionResolver":
        force_to_faction = {
            f.index: f.faction_id
            for f in forces
            if f.faction_id is not None and f.faction_id >= 0
        }
        general_force_by_index = {
            g.index: g.force_id for g in generals if g.force_id is not None
        }
        return cls(force_to_faction=force_to_faction, general_force_by_index=general_force_by_index)

    # -- 基础查询 ---------------------------------------------------------

    def faction_of_force(self, force_id: int | None) -> int | None:
        """军团 -> 势力。force_id 未知/无归属/查不到时返回 None。"""
        if force_id is None or force_id == NO_FORCE_ID:
            return None
        return self.force_to_faction.get(force_id)

    # -- 按记录类型查询 ---------------------------------------------------

    def of_city(self, city: City) -> int | None:
        """城池所属势力。**已实机验证**（12 座城池）。

        注意不要用 `City.faction_id`——那个字段在 offsets 里至今是 unknown，
        解析出来恒为 None。城池的归属就是靠这条链路拿到的。
        """
        return self.faction_of_force(city.force_id)

    def of_general(self, general: General) -> int | None:
        """武将所属势力。**已实机验证**（9 位武将）。

        在野武将（faction_id == -1）显式返回 None：他们不属于任何势力，这是
        "确实没有归属"，与"查不到归属"在下游的处理方式一致（都不算己方），
        但语义上应该由调用方用 is_free_agent() 单独区分。
        """
        if general.faction_id == FREE_AGENT_FACTION_ID:
            return None
        return self.faction_of_force(general.force_id)

    def of_troop(self, troop: Troop) -> int | None:
        """部队所属势力。**⚠ 未经实机验证**，见模块文档。

        Troop 结构体没有 force_id，只能绕两跳：先用主将 id 找到武将，再走武将的
        force_id。主将 id 非法/查不到时返回 None（fail-closed）。
        """
        commander = troop.commander_general_id
        if commander is None or commander < 0:
            return None
        return self.faction_of_force(self.general_force_by_index.get(commander))


def is_free_agent(general: General) -> bool:
    """是否在野（无势力归属）。2026-08-18 实机确认 -1 就是哨兵值。"""
    return general.faction_id == FREE_AGENT_FACTION_ID

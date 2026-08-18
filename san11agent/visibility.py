""""谁能看见什么"的抽象层 —— M2 信息边界过滤器依赖的可见性来源。

boundary.py 里的过滤逻辑只知道"城池/部队/武将是否可见"这几个布尔问题，
不关心答案是从哪里来的。这里提供两类实现：

- StaticVisibilitySource：显式传入探明城池集合/视野内部队集合/已发现武将集合，
  完全离线合成，供测试和未来任何"已经算好可见性"的场景使用。
- UnresolvedVisibilitySource：代表真实游戏进程场景。当前 M1 的内存研究
  （见 docs/offset_research.md）里没有找到任何字段能回答"这座城是否已探明""
  这支部队是否在我方视野内""这个在野武将是否已被发现"——迷雾/视野/情报
  相关的标志位全仓库检索未命中。这三个问题在真实内存里全部是 unknown，
  调用对应方法会显式抛出 VisibilityUnknownError，不会用任何猜测值替代。
  见 docs/visibility_research.md。

"玩家自己是哪个势力"（player_faction_id）单独处理：offsets 文件里唯一的候选
字段 faction.player_marker 语义本身未经实机验证（"是索引还是布尔标志未核实"，
confidence=low，见 offsets/pk_1.1_cn.json），所以这里不从内存派生它，而是
要求调用方显式传入——这本来就是玩家在开局时选择的、不需要靠猜内存来确定的
信息。等 player_marker 的语义被验证过，可以再加一个"从 GameState 派生"的
辅助函数交叉核对，但不会取代显式传入这个默认路径。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class VisibilityUnknownError(Exception):
    """真实游戏内存里还没有找到能回答这个可见性问题的字段。不是 bug，是数据缺口。"""


class VisibilitySource(ABC):
    """回答"某个实体对玩家是否可见"的抽象接口。"""

    @property
    @abstractmethod
    def player_faction_id(self) -> int:
        """玩家自己所属势力在 GameState.factions 里的 index。"""

    @abstractmethod
    def is_city_explored(self, city_index: int) -> bool:
        """该城池（非己方）内部详情（守军/武将配置/粮草储备等）是否已对玩家探明。"""

    @abstractmethod
    def is_troop_visible(self, troop_index: int) -> bool:
        """该部队（非己方）当前是否在玩家视野内（未被迷雾遮挡）。"""

    @abstractmethod
    def is_general_discovered(self, general_index: int) -> bool:
        """该在野（无势力归属）武将是否已被玩家发现。不适用于已有势力归属的武将——
        那些武将只要"已登场"就属于允许暴露的公开信息，见 docs/visibility_research.md。
        """


@dataclass(frozen=True)
class StaticVisibilitySource(VisibilitySource):
    """完全离线、显式给定的可见性来源。供测试和"可见性已经算好"的场景使用。

    三个集合默认为空——即"什么都没探明/看见/发现"，这跟过滤器的整体默认策略
    （默认不暴露，显式列出可见的）保持同一种保守方向。
    """

    _player_faction_id: int
    explored_city_indices: frozenset[int] = field(default_factory=frozenset)
    visible_troop_indices: frozenset[int] = field(default_factory=frozenset)
    discovered_general_indices: frozenset[int] = field(default_factory=frozenset)

    @property
    def player_faction_id(self) -> int:
        return self._player_faction_id

    def is_city_explored(self, city_index: int) -> bool:
        return city_index in self.explored_city_indices

    def is_troop_visible(self, troop_index: int) -> bool:
        return troop_index in self.visible_troop_indices

    def is_general_discovered(self, general_index: int) -> bool:
        return general_index in self.discovered_general_indices


class UnresolvedVisibilitySource(VisibilitySource):
    """真实游戏进程场景的占位实现：exploration/视野/武将发现状态目前全部 unknown。

    player_faction_id 仍然可以正常返回——它不依赖内存派生（见模块顶部说明），
    是调用方（比如 CLI 参数）显式提供的。真正未知的是另外三个问题，一旦被调用
    就抛出 VisibilityUnknownError，而不是返回一个可能悄悄泄漏信息的默认值
    （比如"默认当作已探明"）或者一个可能过度保守到不可用的默认值——两种默认值
    都是在没有真实依据的情况下编答案，所以选择显式报错。
    """

    def __init__(self, player_faction_id: int):
        self._player_faction_id = player_faction_id

    @property
    def player_faction_id(self) -> int:
        return self._player_faction_id

    def is_city_explored(self, city_index: int) -> bool:
        raise VisibilityUnknownError(
            "无法判断城池是否已探明：真实游戏内存里尚未找到迷雾/情报相关的标志位，"
            "见 docs/visibility_research.md。在这个问题解决之前，非己方城池一律"
            "按未探明处理（filter 层会在到达这里之前，先用 StaticVisibilitySource "
            "或其它已知来源提供答案；如果代码走到了这里，说明当前用的是真实进程场景，"
            "而这个场景本来就不该被静默放行）。"
        )

    def is_troop_visible(self, troop_index: int) -> bool:
        raise VisibilityUnknownError(
            "无法判断部队是否在视野内：真实游戏内存里尚未找到视野/迷雾相关的标志位，"
            "见 docs/visibility_research.md。"
        )

    def is_general_discovered(self, general_index: int) -> bool:
        raise VisibilityUnknownError(
            "无法判断在野武将是否已被发现：真实游戏内存里尚未找到武将登场/发现相关的"
            "标志位，见 docs/visibility_research.md。"
        )

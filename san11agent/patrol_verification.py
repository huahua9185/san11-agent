"""M3/M5：巡察动作的后置验证器。

真实执行器不能把“已经发出键鼠输入”当成成功。一次巡察在真实游戏里应当产生
可观察的状态变化：

- 所属己方军团的 `action_points` 减少 20；
- 执行城池的 `gold` 减少 100；
- 执行城池的 `security` 上升；
- 选中的执行武将 `has_acted` 从 false/未知变为 true。

本模块只消费 M2 的 `VisibleGameState` 前后快照，不读内存、不发送输入、不依赖
camera/selection 等尚未定位的界面字段，所以可以先离线测试，等真实
`ActionExecutor` 做出来后再直接复用。

**三值结论**（和项目其它地方一样，不把“没看到”当成“失败”或“成功”）：

- `CONFIRMED`：所有检查都通过；
- `FAILED`：至少一项检查明确与预期矛盾（比如行动力只少了 19、资金没变、
  武将仍显示未行动）；
- `INCONCLUSIVE`：没有发现矛盾，但存在缺失/未知状态，不能确认动作生效
  （比如军团余额未知、城池只可见摘要、执行前 `has_acted` 已经是 true）。

**为什么金/行動力要求精确差值**：这两个值在一次巡察的确认框和扣费链里是固定
的 100 金 / 20 行動力，且执行器后置核对应紧邻动作完成——如果前后快照之间还
发生了其它动作或回合推进，精确差值本来就不再成立，此时应重读或重做实验，
而不是放宽成“只要减少就算成功”。

**为什么治安只要求上升**：REA 已确认治安会变化（受控实验 80→91），但具体
增量公式尚未完全解析；这里只检查方向，不把未知公式编成一个固定值。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from .legal_actions import SecurityPatrolAction
from .visible_state import VisibleCityDetail, VisibleGameState, VisibleGeneralFull


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    CONFIRMED = "confirmed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class VerificationCheck:
    """一项可观察的后置条件及其判定。"""

    name: str
    status: CheckStatus
    before: object
    after: object
    detail: str = ""


@dataclass(frozen=True)
class PatrolExpectation:
    """一次巡察的预期效果。

    `general_indices` 至少包含动作里的发起武将；真实游戏允许 1~3 名执行者，
    但当前 `SecurityPatrolAction` 只表达单个 `general_index`，所以额外执行者
    由调用方显式传入，等动作模型扩展后再改成直接读取 Action。
    """

    city_index: int
    general_indices: tuple[int, ...]
    action_points_cost: int = 20
    gold_cost: int = 100

    def __post_init__(self) -> None:
        if self.action_points_cost < 0:
            raise ValueError("action_points_cost 不能为负")
        if self.gold_cost < 0:
            raise ValueError("gold_cost 不能为负")
        if not self.general_indices:
            raise ValueError("PatrolExpectation 至少需要一个执行武将")

    @classmethod
    def from_action(
        cls,
        action: SecurityPatrolAction,
        *,
        extra_general_indices: Sequence[int] = (),
    ) -> "PatrolExpectation":
        """从单个 Action 构造预期，允许调用方补上多人巡察的额外执行者。"""
        indices = tuple(dict.fromkeys((action.general_index, *extra_general_indices)))
        return cls(city_index=action.city_index, general_indices=indices)


@dataclass(frozen=True)
class PatrolSnapshot:
    """巡察前后需要比较的己方可见状态切片。"""

    city_index: int
    force_index: int | None
    action_points: int | None
    gold: int | None
    security: int | None
    has_acted: tuple[tuple[int, bool | None], ...]


@dataclass(frozen=True)
class PatrolVerification:
    """一次后置验证的完整结果，逐项保留以便写进 ActionLog。"""

    status: VerificationStatus
    checks: tuple[VerificationCheck, ...]

    def check(self, name: str) -> VerificationCheck:
        for item in self.checks:
            if item.name == name:
                return item
        raise KeyError(name)

    def to_dict(self) -> dict[str, object]:
        """JSON 友好形式，供 ActionLog/测试/调试输出使用。"""
        return {
            "status": self.status.value,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "before": c.before,
                    "after": c.after,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


def capture_patrol_snapshot(
    state: VisibleGameState,
    expectation: PatrolExpectation,
) -> PatrolSnapshot:
    """从 VisibleGameState 截取巡察相关字段。

    城池不是 `VisibleCityDetail`、军团不存在、武将不是 `VisibleGeneralFull`
    时，对应字段保留 `None`，由验证器判为 unknown——不猜测、不补零。
    """
    city = next((c for c in state.cities if c.index == expectation.city_index), None)

    if isinstance(city, VisibleCityDetail):
        force_index = city.force_id
        gold: int | None = city.gold
        security: int | None = city.security
    else:
        force_index = None
        gold = None
        security = None

    force = (
        next((f for f in state.forces if f.index == force_index), None)
        if force_index is not None
        else None
    )
    action_points = force.action_points if force is not None else None

    generals_by_index = {g.index: g for g in state.generals}
    has_acted = tuple(
        (
            index,
            generals_by_index[index].has_acted
            if isinstance(generals_by_index.get(index), VisibleGeneralFull)
            else None,
        )
        for index in expectation.general_indices
    )

    return PatrolSnapshot(
        city_index=expectation.city_index,
        force_index=force_index,
        action_points=action_points,
        gold=gold,
        security=security,
        has_acted=has_acted,
    )


def _delta_check(name: str, before: int | None, after: int | None, expected: int, unit: str) -> VerificationCheck:
    if before is None or after is None:
        return VerificationCheck(
            name=name,
            status=CheckStatus.UNKNOWN,
            before=before,
            after=after,
            detail="执行前/后至少一侧没有可见值，不能确认该变化",
        )
    if after - before == expected:
        return VerificationCheck(
            name=name,
            status=CheckStatus.PASS,
            before=before,
            after=after,
            detail=f"{before} -> {after}，变化 {expected:+d}{unit}",
        )
    return VerificationCheck(
        name=name,
        status=CheckStatus.FAIL,
        before=before,
        after=after,
        detail=f"{before} -> {after}，预期变化 {expected:+d}{unit}",
    )


def _security_check(before: int | None, after: int | None) -> VerificationCheck:
    if before is None or after is None:
        return VerificationCheck(
            name="security",
            status=CheckStatus.UNKNOWN,
            before=before,
            after=after,
            detail="执行前/后至少一侧没有可见值，不能确认治安变化",
        )
    if after > before:
        return VerificationCheck(
            name="security",
            status=CheckStatus.PASS,
            before=before,
            after=after,
            detail=f"{before} -> {after}，治安上升",
        )
    return VerificationCheck(
        name="security",
        status=CheckStatus.FAIL,
        before=before,
        after=after,
        detail=f"{before} -> {after}，治安没有上升",
    )


def _has_acted_check(
    general_index: int,
    before: bool | None,
    after: bool | None,
) -> VerificationCheck:
    name = f"general[{general_index}].has_acted"
    if after is None:
        return VerificationCheck(
            name=name,
            status=CheckStatus.UNKNOWN,
            before=before,
            after=after,
            detail="执行后未读到己方该武将的 has_acted",
        )
    if after is False:
        return VerificationCheck(
            name=name,
            status=CheckStatus.FAIL,
            before=before,
            after=after,
            detail="执行后仍显示未行动",
        )
    if before is True:
        return VerificationCheck(
            name=name,
            status=CheckStatus.UNKNOWN,
            before=before,
            after=after,
            detail="执行前已经是已行动状态，无法用它证明本次动作生效",
        )
    if before is None:
        return VerificationCheck(
            name=name,
            status=CheckStatus.UNKNOWN,
            before=before,
            after=after,
            detail="执行前状态未知，无法确认是否发生了 false -> true 的变化",
        )
    return VerificationCheck(
        name=name,
        status=CheckStatus.PASS,
        before=before,
        after=after,
        detail="false -> true",
    )


def verify_patrol_effect(
    before: PatrolSnapshot,
    after: PatrolSnapshot,
    expectation: PatrolExpectation,
) -> PatrolVerification:
    """比较前后快照，返回 confirmed / failed / inconclusive。"""
    checks: list[VerificationCheck] = []

    if before.city_index != after.city_index or before.city_index != expectation.city_index:
        checks.append(
            VerificationCheck(
                name="city_identity",
                status=CheckStatus.FAIL,
                before=before.city_index,
                after=after.city_index,
                detail="前后快照或预期目标不是同一座城",
            )
        )

    if before.force_index != after.force_index:
        if before.force_index is None or after.force_index is None:
            force_status = CheckStatus.UNKNOWN
            force_detail = "执行前/后至少一侧没有军团归属，不能确认行动力属于同一军团"
        else:
            force_status = CheckStatus.FAIL
            force_detail = "前后快照的军团归属发生变化"
        checks.append(
            VerificationCheck(
                name="force_identity",
                status=force_status,
                before=before.force_index,
                after=after.force_index,
                detail=force_detail,
            )
        )

    checks.append(
        _delta_check(
            "action_points",
            before.action_points,
            after.action_points,
            -expectation.action_points_cost,
            " 行動力",
        )
    )
    checks.append(
        _delta_check(
            "gold",
            before.gold,
            after.gold,
            -expectation.gold_cost,
            " 金",
        )
    )
    checks.append(_security_check(before.security, after.security))

    after_acted = dict(after.has_acted)
    for general_index in expectation.general_indices:
        before_value = dict(before.has_acted).get(general_index)
        after_value = after_acted.get(general_index)
        checks.append(_has_acted_check(general_index, before_value, after_value))

    statuses = {c.status for c in checks}
    if CheckStatus.FAIL in statuses:
        status = VerificationStatus.FAILED
    elif checks and statuses == {CheckStatus.PASS}:
        status = VerificationStatus.CONFIRMED
    else:
        status = VerificationStatus.INCONCLUSIVE

    return PatrolVerification(status=status, checks=tuple(checks))


def verify_patrol_action(
    before_state: VisibleGameState,
    after_state: VisibleGameState,
    action: SecurityPatrolAction,
    *,
    extra_general_indices: Sequence[int] = (),
) -> PatrolVerification:
    """便利入口：从动作和前后 VisibleGameState 直接完成一次验证。"""
    expectation = PatrolExpectation.from_action(
        action, extra_general_indices=extra_general_indices
    )
    return verify_patrol_effect(
        capture_patrol_snapshot(before_state, expectation),
        capture_patrol_snapshot(after_state, expectation),
        expectation,
    )

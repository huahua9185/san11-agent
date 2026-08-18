"""M3 执行层最小链路：给定目标城池的地图格子坐标，把它点出来，并轮询内存
确认选中状态已经变化。对应项目规格里的验收标准：

    从内存读某城池格子坐标 -> 滚动地图使其进入视野 -> 点击 -> 轮询确认内存中
    "当前选中城池"已变更。

设计原则（详见 docs/execution_research.md 和提交报告"设计取舍"一节）：
- 禁止固定 sleep：所有等待都走 polling.poll_until()，可注入 Clock。
- 动作序列可重入：select_city() 每次调用都先执行归位例程，不依赖上一次调用
  留下的中间状态；失败就整个归位重来，不做"从哪一步接着修"的中途状态恢复。
- 完整动作日志：每一步都记录到 ActionLog，包含执行前后的关键状态差异。

真实游戏场景下，这条链路目前完全跑不起来：camera 偏移/缩放、当前选中城池
两组内存字段都是 unknown（见 offsets/pk_1.1_cn.json 的 camera/selection
struct），map_viewport 界面坐标也完全没有测量数据（见 ui_layout/pk_1.1_cn.json）。
这是刻意的：在这些缺口解决前，代码会在 project_tile_to_client()/
UIElement.require_known() 处显式抛出清楚的错误，不会用编出来的坐标点到游戏
里的未知位置。

一个重要区分：坐标/配置缺失（MapProjectionError 由"camera 字段 unknown"触发、
或 UILayoutError）不属于"重试也许能修好"的偶发失败——重试并不能凭空生成一个
没有的偏移值，所以只有"camera 已知但这次点击没在轮询超时内生效"这类
PollTimeoutError，以及"camera 已知但滚动多次仍找不到目标格子"这类
MapProjectionError（滚动超时导致），才会触发归位重试；UILayoutError 会直接
从 select_city() 抛出，不会被吞掉进重试循环。
"""
from __future__ import annotations

from dataclasses import dataclass

from .action_log import ActionLog
from .clock import Clock
from .execution_state import CameraState, SelectionState, parse_camera_state, parse_selection_state
from .input_backend import VK_DOWN, VK_ESCAPE, VK_LEFT, VK_RIGHT, VK_UP, InputBackend
from .map_projection import MapProjectionError, ScreenPoint, TileCoord, project_tile_to_client
from .memory import MemoryReader
from .offsets import OffsetsConfig
from .perception import resolve_anchor
from .polling import PollTimeoutError, poll_until
from .ui_layout import UIElement, UILayoutConfig
from .window import GameWindow

_SCROLL_KEYS = {"left": VK_LEFT, "up": VK_UP, "right": VK_RIGHT, "down": VK_DOWN}


class ExecutionFailedError(Exception):
    """一个动作序列在归位重试用尽后仍未达成目标。"""


@dataclass(frozen=True)
class ExecutionConfig:
    poll_timeout: float = 2.0
    poll_interval: float = 0.1
    max_retries: int = 2  # 首次尝试之外，再重试几次
    home_esc_presses: int = 3
    max_scroll_nudges: int = 20
    scroll_poll_timeout: float = 1.0
    scroll_poll_interval: float = 0.05


class CitySelector:
    """执行"点某座城池并确认选中状态已变更"这一条最小链路。"""

    def __init__(
        self,
        *,
        reader: MemoryReader,
        offsets: OffsetsConfig,
        ui_layout: UILayoutConfig,
        input_backend: InputBackend,
        window: GameWindow,
        clock: Clock,
        action_log: ActionLog,
        config: ExecutionConfig = ExecutionConfig(),
    ):
        self._reader = reader
        self._offsets = offsets
        self._ui_layout = ui_layout
        self._input = input_backend
        self._window = window
        self._clock = clock
        self._log = action_log
        self._config = config

    def select_city(self, city_index: int, target_tile: TileCoord) -> None:
        """把 (city_index, target_tile) 对应的城池点出来。

        target_tile 由调用方从 GameState.City.map_x/map_y 读取提供——那是 M1
        的职责（见 game_state.City），M3 不重复解析 GameState，只负责"给定
        目标格子坐标，操作鼠标键盘把它选中"这一段。这样解耦也符合"城池地图
        坐标目前 unknown"这个 M1 缺口不阻塞 M3 脚手架开发的既有原则。
        """
        last_error: Exception | None = None
        for attempt in range(1, self._config.max_retries + 2):
            self._home(attempt)
            try:
                self._attempt(city_index, target_tile, attempt)
                return
            except (PollTimeoutError, MapProjectionError) as exc:
                last_error = exc
                self._log.record(
                    intent="select_city.attempt_failed",
                    params={"city_index": city_index, "attempt": attempt},
                    result="failure",
                    detail=str(exc),
                )
        raise ExecutionFailedError(
            f"选择城池 {city_index} 失败：已重试 {self._config.max_retries} 次仍未确认选中"
            f"状态变更。最后一次错误: {last_error}"
        )

    def _home(self, attempt: int) -> None:
        """归位例程：连按 Esc 退回已知界面。

        当前没有可靠的内存标志位能验证"已知界面"具体是哪个界面
        （GlobalState.phase 仍是 unknown，见 offsets/pk_1.1_cn.json），所以这里
        能保证到的只是"发送了 N 次 Esc"，没法真正校验归位是否成功——这是当前
        设计能做到的极限，已在提交报告里列出，等 phase 字段解决后应该在这里
        补一次状态校验。
        """
        for _ in range(self._config.home_esc_presses):
            self._input.key_press(VK_ESCAPE)
        self._log.record(
            intent="home",
            params={"esc_presses": self._config.home_esc_presses, "attempt": attempt},
            result="sent",
            detail="无法校验归位后的界面状态，见 GlobalState.phase 字段 unknown 的说明",
        )

    def _game_data_base(self) -> int:
        return resolve_anchor(self._reader, self._offsets)

    def _read_camera(self, game_data_base: int) -> CameraState:
        return parse_camera_state(self._reader, self._offsets, game_data_base)

    def _read_selection(self, game_data_base: int) -> SelectionState:
        return parse_selection_state(self._reader, self._offsets, game_data_base)

    def _attempt(self, city_index: int, target_tile: TileCoord, attempt: int) -> None:
        game_data_base = self._game_data_base()
        viewport = self._ui_layout.element("map_viewport")
        camera = self._read_camera(game_data_base)

        screen_point = self._reveal(target_tile, camera, viewport, game_data_base)

        before = self._read_selection(game_data_base)
        screen_x, screen_y = self._window.client_to_screen(screen_point.x, screen_point.y)

        self._input.click(screen_x, screen_y)

        def _selected() -> bool:
            return self._read_selection(game_data_base).selected_city_index == city_index

        try:
            poll_attempts = poll_until(
                _selected,
                timeout=self._config.poll_timeout,
                interval=self._config.poll_interval,
                clock=self._clock,
                description=f"等待城池 {city_index} 被选中",
            )
        except PollTimeoutError:
            after = self._read_selection(game_data_base)
            self._log.record(
                intent="select_city.click",
                params={"city_index": city_index, "screen": (screen_x, screen_y), "attempt": attempt},
                result="timeout",
                state_before={"selected_city_index": before.selected_city_index},
                state_after={"selected_city_index": after.selected_city_index},
            )
            raise

        after = self._read_selection(game_data_base)
        self._log.record(
            intent="select_city.click",
            params={
                "city_index": city_index,
                "screen": (screen_x, screen_y),
                "attempt": attempt,
                "poll_attempts": poll_attempts,
            },
            result="success",
            state_before={"selected_city_index": before.selected_city_index},
            state_after={"selected_city_index": after.selected_city_index},
        )

    def _reveal(
        self, target_tile: TileCoord, camera: CameraState, viewport: UIElement, game_data_base: int
    ) -> ScreenPoint:
        """如果目标格子已经在视野内直接返回坐标；否则滚动地图直到进入视野，
        或者滚动次数用尽后放弃（转成 MapProjectionError，交给上层归位重试）。
        """
        point = project_tile_to_client(target_tile, camera, viewport)
        if point is not None:
            return point

        for nudge in range(1, self._config.max_scroll_nudges + 1):
            direction = self._pick_scroll_direction(target_tile, camera)
            self._nudge_map(direction)

            previous_camera = camera

            def _camera_changed() -> bool:
                return self._read_camera(game_data_base) != previous_camera

            try:
                poll_until(
                    _camera_changed,
                    timeout=self._config.scroll_poll_timeout,
                    interval=self._config.scroll_poll_interval,
                    clock=self._clock,
                    description=f"等待地图滚动响应 (第{nudge}次)",
                )
            except PollTimeoutError as exc:
                self._log.record(
                    intent="scroll_map",
                    params={"direction": direction, "nudge": nudge},
                    result="timeout",
                    detail=str(exc),
                )
                raise MapProjectionError(f"滚动地图第 {nudge} 次后摄像机没有变化: {exc}") from exc

            camera = self._read_camera(game_data_base)
            self._log.record(
                intent="scroll_map",
                params={"direction": direction, "nudge": nudge},
                result="success",
                state_before={"offset_x": previous_camera.offset_x, "offset_y": previous_camera.offset_y},
                state_after={"offset_x": camera.offset_x, "offset_y": camera.offset_y},
            )
            point = project_tile_to_client(target_tile, camera, viewport)
            if point is not None:
                return point

        raise MapProjectionError(
            f"滚动地图 {self._config.max_scroll_nudges} 次后目标格子 {target_tile} 仍不在视野内"
        )

    def _pick_scroll_direction(self, target_tile: TileCoord, camera: CameraState) -> str:
        """选一个滚动方向靠近目标格子。project_tile_to_client() 已经在走到这里
        之前校验过 camera 字段不是 None，这里不用再判断。
        """
        if target_tile.x < camera.offset_x:
            return "left"
        if target_tile.x > camera.offset_x:
            return "right"
        if target_tile.y < camera.offset_y:
            return "up"
        return "down"

    def _nudge_map(self, direction: str) -> None:
        """滚动地图的具体输入方式：按一次方向键。

        这是一个未经验证的假设——三国志11实际的地图滚动方式也可能是鼠标
        边缘滚动/拖拽/小地图点击，不是方向键。已在 docs/execution_research.md
        和提交报告里列为需要你在游戏可运行后确认的设计取舍。选方向键是因为
        它是几种可能方式里最不容易误触发游戏内其它功能（比如拖拽误选中部队）
        的一种，作为脚手架阶段的默认假设。
        """
        self._input.key_press(_SCROLL_KEYS[direction])

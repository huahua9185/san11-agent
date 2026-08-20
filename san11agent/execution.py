"""M3 执行层最小链路：给定目标城池的地图格子坐标，把鼠标悬停上去，并轮询
内存确认选中状态已经变化。对应项目规格里的验收标准：

    从内存读某城池格子坐标 -> 平移地图使其进入视野 -> 悬停 -> 轮询确认内存中
    "当前选中城池"已变更。

（"悬停"不是"点击"——2026-08-19 用户直接确认选中城池只需要鼠标悬停在上面，
点击会弹出该城池的一级指令菜单，见 CitySelector 类文档和 menu_execution.py。）

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
没有的偏移值，所以只有"camera 已知但这次悬停没在轮询超时内生效"这类
PollTimeoutError，以及"camera 已知但平移多次仍找不到目标格子"这类
MapProjectionError（平移超时导致），才会触发归位重试；UILayoutError 会直接
从 select_city() 抛出，不会被吞掉进重试循环。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .action_log import ActionLog
from .clock import Clock
from .execution_state import CameraState, SelectionState, parse_camera_state, parse_selection_state
from .input_backend import VK_ESCAPE, InputBackend
from .map_projection import MapProjectionError, ScreenPoint, TileCoord, project_tile_to_client
from .memory import MemoryReader
from .offsets import OffsetsConfig
from .perception import resolve_anchor
from .polling import PollTimeoutError, poll_until
from .ui_layout import UIElement, UILayoutConfig
from .window import GameWindow

# 平移地图的边缘停靠点跟视口边界的留白（像素），避免鼠标坐标正好落在视口
# 矩形边界上下界处的浮点/取整边缘情况。
_EDGE_MARGIN = 2


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


def reveal_tile(
    target_tile: TileCoord,
    camera: CameraState,
    viewport: UIElement,
    *,
    read_camera: "Callable[[], CameraState]",
    input_backend: InputBackend,
    window: GameWindow,
    clock: Clock,
    action_log: ActionLog,
    config: ExecutionConfig,
) -> ScreenPoint:
    """如果目标格子已经在视野内直接返回坐标；否则平移地图直到进入视野，
    或者尝试次数用尽后放弃（转成 MapProjectionError，交给上层归位重试）。

    从 CitySelector 里抽出来的独立函数——2026-08-19 新增的 menu_execution.py
    （打开城池指令菜单）需要同一段"把目标格子滚进视野"的逻辑，双击城池之前
    同样要先保证目标格子可见，跟 select_city() 点击城池之前的需求完全一样，
    没有理由各自维护一份。`read_camera` 用回调而不是直接传 reader/offsets/
    game_data_base，是因为调用方（CitySelector._attempt / menu_execution 里
    对应的方法）已经各自算好了 game_data_base，这里只需要"再读一次最新的
    camera"这个动作本身，不需要知道怎么算地址。

    平移方式：2026-08-19 实机确认（用户直接回答）——左右方向键在这个游戏里
    是**旋转相机视角**，不是平移地图；真正平移地图靠的是把鼠标移到屏幕边缘、
    游戏自动向那个方向滚动。这次改动之前的实现按方向键去平移是一个已确认
    的错误，不是"未经验证的假设"那种程度——之前代码如果真跑在 `--live` 下，
    点击流程会先把相机转乱而不是把目标格子挪进视野。现在改成移动鼠标到
    `viewport` 矩形对应方向的边缘（`_edge_point_for_direction()`），不点击，
    只是悬停，然后跟之前一样轮询摄像机是否变化。真实的边缘滚动是"鼠标停在
    那里的整段时间持续滚动"，不是像按键那样离散的一次性事件，所以这里的
    "一次 nudge"实际上是"移过去、等一段轮询间隔、看摄像机动没动"，不需要
    重复移动同一个点。
    """
    point = project_tile_to_client(target_tile, camera, viewport)
    if point is not None:
        return point

    for nudge in range(1, config.max_scroll_nudges + 1):
        direction = _pick_scroll_direction(target_tile, camera)
        edge_point = _edge_point_for_direction(direction, viewport)
        screen_x, screen_y = window.client_to_screen(edge_point.x, edge_point.y)
        input_backend.move_mouse(screen_x, screen_y)

        previous_camera = camera

        def _camera_changed() -> bool:
            return read_camera() != previous_camera

        try:
            poll_until(
                _camera_changed,
                timeout=config.scroll_poll_timeout,
                interval=config.scroll_poll_interval,
                clock=clock,
                description=f"等待地图平移响应 (第{nudge}次)",
            )
        except PollTimeoutError as exc:
            action_log.record(
                intent="pan_map",
                params={"direction": direction, "nudge": nudge, "edge_screen": (screen_x, screen_y)},
                result="timeout",
                detail=str(exc),
            )
            raise MapProjectionError(f"平移地图第 {nudge} 次后摄像机没有变化: {exc}") from exc

        camera = read_camera()
        action_log.record(
            intent="pan_map",
            params={"direction": direction, "nudge": nudge, "edge_screen": (screen_x, screen_y)},
            result="success",
            state_before={"offset_x": previous_camera.offset_x, "offset_y": previous_camera.offset_y},
            state_after={"offset_x": camera.offset_x, "offset_y": camera.offset_y},
        )
        point = project_tile_to_client(target_tile, camera, viewport)
        if point is not None:
            return point

    raise MapProjectionError(
        f"平移地图 {config.max_scroll_nudges} 次后目标格子 {target_tile} 仍不在视野内"
    )


def _pick_scroll_direction(target_tile: TileCoord, camera: CameraState) -> str:
    """选一个平移方向靠近目标格子。project_tile_to_client() 已经在走到这里
    之前校验过 camera 字段不是 None，这里不用再判断。

    等距菱形变换下屏幕横轴对应 (dx - dy)、屏幕纵轴对应 (dx + dy)（见
    map_projection.py 模块顶部公式），不能再直接拿 target_tile.x/y 跟
    camera.offset_x/offset_y 逐轴比较——那是旧的正交网格假设，2026-08-19
    已确认默认视角是等距投影后改成跟着同一套 (dx-dy, dx+dy) 关系判断屏幕
    方向。方向约定（哪个符号对应哪个屏幕方向）本身仍是未经验证的假设，
    见 map_projection.py 模块文档。
    """
    dx = target_tile.x - camera.offset_x
    dy = target_tile.y - camera.offset_y
    horizontal = dx - dy
    vertical = dx + dy
    if horizontal < 0:
        return "left"
    if horizontal > 0:
        return "right"
    if vertical < 0:
        return "up"
    return "down"


def _edge_point_for_direction(direction: str, viewport: UIElement) -> ScreenPoint:
    """viewport 矩形靠近某个方向边缘、贴着但不越界的一个客户区坐标点，鼠标
    停在这个位置触发游戏自动向该方向平移地图。viewport 在调用前已经过
    `require_known()` 校验（`project_tile_to_client()` 内部已经做过），
    这里不重复校验。
    """
    mid_x = viewport.x + viewport.width // 2
    mid_y = viewport.y + viewport.height // 2
    if direction == "left":
        return ScreenPoint(viewport.x + _EDGE_MARGIN, mid_y)
    if direction == "right":
        return ScreenPoint(viewport.x + viewport.width - 1 - _EDGE_MARGIN, mid_y)
    if direction == "up":
        return ScreenPoint(mid_x, viewport.y + _EDGE_MARGIN)
    if direction == "down":
        return ScreenPoint(mid_x, viewport.y + viewport.height - 1 - _EDGE_MARGIN)
    raise ValueError(f"未知的平移方向 {direction!r}")


class CitySelector:
    """执行"把鼠标悬停到某座城池上并确认选中状态已变更"这一条最小链路。

    2026-08-19 用户直接确认：选中城池只需要鼠标悬停在上面，不需要点击——
    点击（左键按下+抬起）在这个游戏里会弹出该城池的一级指令菜单（见
    `menu_execution.py`），如果这里还发送真正的点击，会把"只是选中/高亮"
    和"打开菜单"这两个不同的意图混在一起，弹出一个调用方没有要求的菜单。
    这之前是一个已确认的代码错误（不是"未经验证的假设"）：`_attempt()`
    原来调用 `input_backend.click()`，已改成 `move_mouse()`（只移动鼠标，
    不按下/抬起按键）。
    """

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
        """把鼠标悬停到 (city_index, target_tile) 对应的城池上，选中它。

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

        self._input.move_mouse(screen_x, screen_y)

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
                intent="select_city.hover",
                params={"city_index": city_index, "screen": (screen_x, screen_y), "attempt": attempt},
                result="timeout",
                state_before={"selected_city_index": before.selected_city_index},
                state_after={"selected_city_index": after.selected_city_index},
            )
            raise

        after = self._read_selection(game_data_base)
        self._log.record(
            intent="select_city.hover",
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

        实际逻辑在模块级函数 reveal_tile() 里——2026-08-19 抽出来给
        menu_execution.py 复用，见该函数的说明。
        """
        return reveal_tile(
            target_tile,
            camera,
            viewport,
            read_camera=lambda: self._read_camera(game_data_base),
            input_backend=self._input,
            window=self._window,
            clock=self._clock,
            action_log=self._log,
            config=self._config,
        )

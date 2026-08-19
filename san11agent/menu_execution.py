"""M3/M4 Execute 扩展：把 M4 `enumerate_legal_actions()` 产出的 `Action`
对象，转换成"单击城池弹出指令菜单 -> 点顶层菜单项 -> 点二级子菜单项"这一段
键鼠序列。`execution.py` 的 `CitySelector` 只做到"悬停城池、确认被选中"，
本模块接着往下做一步：把 M4 已经枚举出的合法动作真正点出来。

## 菜单结构是实机确认过的事实，但坐标不是

`TOP_MENU_ITEMS`/`SUBMENU_ITEMS` 两张表直接抄自 `docs/offset_research.md`
第8.1节——那是用户对着真实运行的游戏逐个菜单截图核实过的顺序和项数，不是
猜的。但**这两个菜单在客户区里的像素坐标完全没有测量**（`ui_layout/
pk_1.1_cn.json` 新增的 `city_top_menu`/`city_submenu` 两个元素都是
`unknown: true`），跟 `map_viewport`/`camera`/`selection` 是同一类缺口，
处理方式也一致：`UIElement.require_known()` 会在坐标未知时直接抛
`UILayoutError`，不会用编出来的坐标点击。

## 这条链路完全无法自我验证

`CitySelector.select_city()` 能靠 `selection.selected_city_index` 轮询
确认点击生效；本模块没有对应的东西可以确认——"当前打开的是哪个菜单"、
"哪一项被选中"这类状态目前没有任何已知的内存字段能读到（根源还是
`GlobalState.phase` 仍然 unknown，M1 就已知的老缺口，见
docs/offset_research.md 4.5节）。所以这里的每一步都只是"发送输入 + 记
日志"，**没有轮询、没有超时、也没有重试**——重试对着一个无法验证的状态
没有意义，只会徒增风险（比如把已经打开的菜单误按 Esc 关掉，或者对着一个
可能已经成功的动作重复发起）。这不是遗漏，是当前已知信息量能做到的极限，
等 `phase` 字段解决后应该回来给这里补验证。

## 明确没有实现的部分（不是遗漏，是这次的边界）

三类更深的交互，本次都没有做，因为它们跟"点垂直列表里第N项"是完全不同的
交互形态，没有任何截图或资料参考，实现了也是编的：

1. `BuildFacilityAction` 选具体设施类型——「開發」界面是19个设施图标组成
   的网格（见 docs/offset_research.md 8.3节的「設施數 0/12」「空地 15/15」
   等截图描述），不是列表，点击坐标算法完全不同。
2. `DiplomacyAction`/`StratagemAction` 选具体目标势力/城池——点完子类型
   之后大概率还有一层"选目标"的界面（列表？地图选点？），完全没有资料。
3. 多个游戏内指令流程末尾的"決定"确认按钮——这次会话早些时候的出征操作
   就卡在了这一步附近（见对话记录），本模块同样没有为它定位坐标。

`execute_action()` 对这三类动作会在完成能做的两级菜单点击后，明确抛出
`FurtherStepsNotImplementedError`，而不是假装完成了整个动作。
"""
from __future__ import annotations

from .action_log import ActionLog
from .clock import Clock
from .domestic_rules import DomesticRulesConfig
from .execution import ExecutionConfig, reveal_tile
from .execution_state import CameraState, parse_camera_state
from .input_backend import VK_ESCAPE, InputBackend
from .legal_actions import Action, ActionKind
from .map_projection import ScreenPoint, TileCoord
from .memory import MemoryReader
from .offsets import OffsetsConfig
from .perception import resolve_anchor
from .ui_layout import UIElement, UILayoutConfig
from .window import GameWindow

# docs/offset_research.md 8.1节：用户逐个菜单截图核实过的顶层菜单顺序。
TOP_MENU_ITEMS: tuple[str, ...] = ("都市", "軍事", "人材", "外交", "計略", "君主")

# 同一节：每个顶层菜单展开后的二级子菜单项，按界面顺序。
SUBMENU_ITEMS: dict[str, tuple[str, ...]] = {
    "都市": ("開發", "吸收合併", "徵兵", "生產兵裝", "巡察", "商人", "研究技巧"),
    "軍事": ("訓練", "出征", "輸送"),
    "人材": ("移動", "召喚", "探索人材", "登庸武將", "褒賞", "授與沒收"),
    "外交": ("親善", "同盟", "破棄", "停戰協定", "降伏勸告", "交換俘虜", "請求援軍"),
    "計略": ("二虎競食", "驅虎吞狼", "流言"),
    "君主": ("評定", "軍團", "軍師", "官職", "仲介", "流放", "研究能力", "培育武將"),
}

# ActionKind -> 对应的顶层菜单。docs/offset_research.md 8.2节⑤特别提醒过
# train_troops 在「軍事」下不在「都市」下，容易搞错。
_ACTION_TOP_MENU: dict[ActionKind, str] = {
    ActionKind.BUILD_FACILITY: "都市",
    ActionKind.RECRUIT_TROOPS: "都市",
    ActionKind.SECURITY_PATROL: "都市",
    ActionKind.TRAIN_TROOPS: "軍事",
    ActionKind.DIPLOMACY: "外交",
    ActionKind.STRATAGEM: "計略",
}

# 没有子类型的 ActionKind，对应的二级菜单项文字。DIPLOMACY/STRATAGEM 有
# 子类型（diplomacy_type/stratagem_type），子菜单项要动态从 rules 里的子
# 类型顺序解析，不在这张静态表里，见 resolve_menu_path()。
_ACTION_SUBMENU_LABEL: dict[ActionKind, str] = {
    ActionKind.BUILD_FACILITY: "開發",
    ActionKind.RECRUIT_TROOPS: "徵兵",
    ActionKind.SECURITY_PATROL: "巡察",
    ActionKind.TRAIN_TROOPS: "訓練",
}

# 点完二级菜单项之后，还需要至少一步本模块未实现的更深交互的动作类型，
# 见模块文档"明确没有实现的部分"。
_FURTHER_STEPS_REQUIRED = frozenset(
    {ActionKind.BUILD_FACILITY, ActionKind.DIPLOMACY, ActionKind.STRATAGEM}
)


class MenuExecutionError(Exception):
    """打开城池指令菜单/点选菜单项这条链路本身的错误。"""


class FurtherStepsNotImplementedError(MenuExecutionError):
    """已经点到了 Action 对应的二级菜单项，但这个 ActionKind 还需要至少一步
    更深的交互（设施类型/目标势力/目标城池选择），本次没有实现——见模块文档
    "明确没有实现的部分"。不代表前面已经点过的两级菜单点击失败了。
    """


def resolve_menu_path(action: Action, rules: DomesticRulesConfig) -> tuple[int, int]:
    """把一个 Action 翻译成 (顶层菜单下标, 二级菜单下标)。

    DIPLOMACY/STRATAGEM 的二级下标不是写死的——它由 action.diplomacy_type/
    stratagem_type 在 rules 里对应动作的 sub_types 字典中的插入顺序决定。
    这个顺序本身就是照着 docs/offset_research.md 8.1节的真实菜单顺序录入
    rules 文件的（见 rules/domestic_actions_pk_1.1_cn.json 里 diplomacy_types/
    stratagem_types 的 note），单一事实来源，这里不重复硬编码一份可能跟
    rules 文件走岔的下标表。
    """
    if action.kind not in _ACTION_TOP_MENU:
        raise MenuExecutionError(f"未知的 ActionKind {action.kind!r}，没有对应的菜单路径")

    top_label = _ACTION_TOP_MENU[action.kind]
    top_index = TOP_MENU_ITEMS.index(top_label)
    submenu_labels = SUBMENU_ITEMS[top_label]

    if action.kind is ActionKind.DIPLOMACY:
        sub_type_ids = list(rules.action("diplomacy").sub_types)
        sub_type_key, sub_type_value = "diplomacy_type", action.diplomacy_type
    elif action.kind is ActionKind.STRATAGEM:
        sub_type_ids = list(rules.action("stratagem").sub_types)
        sub_type_key, sub_type_value = "stratagem_type", action.stratagem_type
    else:
        return top_index, submenu_labels.index(_ACTION_SUBMENU_LABEL[action.kind])

    try:
        sub_index = sub_type_ids.index(sub_type_value)
    except ValueError as exc:
        raise MenuExecutionError(
            f"{sub_type_key} {sub_type_value!r} 不在规则表 {action.kind.value} 的 sub_types 里"
        ) from exc
    return top_index, sub_index


class ActionMenuExecutor:
    """把 Action 转换成"打开城池指令菜单 + 点选到具体指令项"这段键鼠序列。

    见模块文档："这条链路完全无法自我验证"——没有轮询、没有重试。
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

    def execute_action(self, action: Action, target_tile: TileCoord, rules: DomesticRulesConfig) -> None:
        """点出一个 Action 对应的菜单项。

        对 RECRUIT_TROOPS/TRAIN_TROOPS/SECURITY_PATROL 这三种不需要更深交互
        的动作，正常返回代表"已经把这条指令点出来了"（但仍然无法验证，见类
        文档）。对 BUILD_FACILITY/DIPLOMACY/STRATAGEM，点完二级菜单项之后
        会抛 FurtherStepsNotImplementedError——前面的点击仍然真实发生过，
        只是这个函数没有能力继续走完剩下的步骤。
        """
        top_index, sub_index = resolve_menu_path(action, rules)

        anchor = self.open_city_menu(action.city_index, target_tile)
        top_menu = self._ui_layout.element("city_top_menu")
        top_point = self._click_menu_item(anchor, top_menu, top_index)

        submenu = self._ui_layout.element("city_submenu")
        top_label = _ACTION_TOP_MENU[action.kind]
        expected_count = len(SUBMENU_ITEMS[top_label])
        self._click_menu_item(top_point, submenu, sub_index, expected_count=expected_count)

        self._log.record(
            intent="menu.execute_action",
            params={
                "kind": action.kind.value,
                "city_index": action.city_index,
                "general_index": action.general_index,
                "top_index": top_index,
                "sub_index": sub_index,
            },
            result="sent",
            detail="已点选到二级菜单项，无法验证是否真的生效，见 ActionMenuExecutor 类文档",
        )

        if action.kind in _FURTHER_STEPS_REQUIRED:
            raise FurtherStepsNotImplementedError(
                f"{action.kind.value} 需要至少一步更深的交互（设施类型选择是"
                f"图标网格 / 目标势力或城池选择界面未知），本次未实现，见 "
                f"menu_execution.py 模块文档'明确没有实现的部分'"
            )

    def open_city_menu(self, city_index: int, target_tile: TileCoord) -> ScreenPoint:
        """归位 -> 把目标城池滚进视野 -> 单击，弹出顶层指令菜单。

        返回点击点的客户区坐标，供后续计算菜单项位置用。跟
        `CitySelector.select_city()` 的悬停选中是两种不同的游戏交互，所以
        不直接复用 CitySelector，但复用它"先归位、再把目标格子滚进视野"
        这两步逻辑（`execution.reveal_tile()`），避免重复维护同一段平移
        地图的代码。

        2026-08-19 用户直接确认：弹出一级指令菜单是**单击**，不是双击——
        这之前是一个已确认的代码错误（不是"未经验证的假设"）：之前这里
        连续调用两次 `InputBackend.click()` 模拟双击，如果第一次点击已经
        弹出菜单，第二次点击可能会落在菜单上、误触发某个菜单项，不只是
        多余，是有实际风险的。已改成单次 `click()`。
        """
        for _ in range(self._config.home_esc_presses):
            self._input.key_press(VK_ESCAPE)
        self._log.record(
            intent="menu.home",
            params={"esc_presses": self._config.home_esc_presses},
            result="sent",
            detail="无法校验归位后的界面状态，见 GlobalState.phase 字段 unknown 的说明",
        )

        game_data_base = resolve_anchor(self._reader, self._offsets)
        viewport = self._ui_layout.element("map_viewport")
        camera = parse_camera_state(self._reader, self._offsets, game_data_base)

        def _read_camera() -> CameraState:
            return parse_camera_state(self._reader, self._offsets, game_data_base)

        screen_point = reveal_tile(
            target_tile,
            camera,
            viewport,
            read_camera=_read_camera,
            input_backend=self._input,
            window=self._window,
            clock=self._clock,
            action_log=self._log,
            config=self._config,
        )

        screen_x, screen_y = self._window.client_to_screen(screen_point.x, screen_point.y)
        self._input.click(screen_x, screen_y)
        self._log.record(
            intent="menu.open_city",
            params={"city_index": city_index, "screen": (screen_x, screen_y)},
            result="sent",
            detail="无法验证菜单是否真的弹出，见 ActionMenuExecutor 类文档",
        )
        return screen_point

    def _click_menu_item(
        self,
        anchor: ScreenPoint,
        element: UIElement,
        index: int,
        *,
        expected_count: int | None = None,
    ) -> ScreenPoint:
        """点击相对 anchor 偏移的第 index 项。anchor 对顶层菜单是点击点，对
        二级菜单是"刚点中的那个顶层菜单项"的位置——子菜单纵向对齐在被点开
        的那一项旁边（见对话记录里的出征菜单截图），不是相对城池点击点。
        """
        element.require_known()
        if element.item_height is None:
            raise MenuExecutionError(
                f"界面元素 {element.name!r} 没有 item_height，无法计算菜单项位置"
            )
        count = expected_count if expected_count is not None else element.item_count
        if count is not None and not (0 <= index < count):
            raise MenuExecutionError(
                f"菜单项下标 {index} 超出 {element.name!r} 的项数范围 [0, {count})"
            )

        point = ScreenPoint(anchor.x + element.x, anchor.y + element.y + index * element.item_height)
        screen_x, screen_y = self._window.client_to_screen(point.x, point.y)
        self._input.click(screen_x, screen_y)
        self._log.record(
            intent="menu.click_item",
            params={"element": element.name, "index": index, "screen": (screen_x, screen_y)},
            result="sent",
            detail="无法验证点击是否命中预期菜单项，见 ActionMenuExecutor 类文档",
        )
        return point

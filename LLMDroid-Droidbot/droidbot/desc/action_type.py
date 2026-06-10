# 文件作用：
# 1. 定义 LLMDroid 中使用的动作类型，如 START、STOP、BACK、CLICK、LONG_CLICK 和各方向滚动。
# 2. 定义控件 HTML 类型，用于把 Android UI 控件转换为 LLM 可理解的 HTML 描述。
# 3. 为 InputEvent、DeviceState、Widget 和 LLM 响应解析提供统一枚举。
from enum import Enum


class OperateType(Enum):
    NONE = 0
    Enable = 0b000001
    Clickable = 0b000010
    Checkable = 0b000100
    LongClickable = 0b001000
    Scrollable = 0b010000
    Editable = 0b100000


class ScrollType(Enum):
    ALL = 0
    Horizontal = 1
    Vertical = 2
    NONE = 3


class ActionType(Enum):
    NOP = ('NOP')
    START = ('START')
    STOP = ('STOP')
    RESTART = ('RESTART')
    BACK = ('BACK')
    CLICK = ('CLICK')
    LONG_CLICK = ('LONG_CLICK')
    SCROLL_TOP_DOWN = ('SCROLL_TOP_DOWN')
    SCROLL_BOTTOM_UP = ('SCROLL_BOTTOM_UP')
    SCROLL_LEFT_RIGHT = ('SCROLL_LEFT_RIGHT')
    SCROLL_RIGHT_LEFT = ('SCROLL_RIGHT_LEFT')
    INPUT = ('INPUT')
    SWIPE = ('SWIPE')
    OTHER = ('OTHER')

    def __new__(cls, string: str = ''):
        obj = object.__new__(cls)
        obj._value_ = len(cls.__members__) + 1
        obj.string = string
        obj.mask = 0x0001 << (obj._value_ - 1)
        return obj

    @classmethod
    def get_type_by_value(cls, value: int) -> 'ActionType':
        for action_type in cls:
            if action_type.value == value:
                return action_type
        raise ValueError(f"No ActionType with value {value}")


class HtmlClass(Enum):
    def __new__(cls, start_tag: str = '', end_tag: str = ''):
        obj = object.__new__(cls)
        obj._value_ = len(cls.__members__) + 1
        obj.start_tag = start_tag
        obj.end_tag = end_tag
        return obj

    BUTTON = ('<button', '</button>')
    CHECKBOX = ('<checkbox', '</checkbox>')
    SCROLLER = ('<scroller', '</scroller>')
    INPUT = ('<input', '</input>')
    P = ('<p', '</p>')

# print(ActionType.NOP.mask)
# print(ActionType.START.mask)
# print(ActionType.STOP.value)

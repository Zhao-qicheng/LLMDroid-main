# 文件作用：
# 1. 表示一次设备 UI 抓取得到的页面状态，保存 view hierarchy、截图、Activity 和页面哈希。
# 2. 从页面中生成候选输入事件，并将 UI 转换为 LLM 可读的紧凑 HTML 描述。
# 3. 提供页面相似度、控件匹配、事件匹配等能力，是 StateCluster 和 UTG 的基础。
import copy
import math
import os
import re
import threading
import time
import datetime
from collections import Counter, deque
from typing import Optional

from ..utils import md5, safe_dict_get
from ..input_event import UIEvent, TouchEvent, LongTouchEvent, ScrollEvent, SetTextEvent, KeyEvent, InputEvent
from .widget import Widget
from .action_type import *
from ..global_log import get_logger
from .state_cluster import StateCluster


DEFAULT_INPUT_TEXT = "Hello World"
DEFAULT_EMAIL_TEXT = "15839579125@163.com"
DEFAULT_PHONE_TEXT = "15839579125"
DEFAULT_NUMBER_TEXT = "123"
DEFAULT_DATE_TEXT = "2026-01-01"
DEFAULT_PASSWORD_TEXT = "Zqc123456@"
DEFAULT_SEARCH_TEXT = "低调"

HTML_MAX_TAGS = 100
HTML_MAX_DEPTH = 25
HTML_NAV_TOP_RATIO = 0.18
HTML_NAV_BOTTOM_RATIO = 0.18
HTML_NAV_KEYWORDS = (
    "toolbar", "actionbar", "appbar", "navigation", "nav", "bottom", "tab", "menu", "drawer"
)
HTML_IMPORTANT_KEYWORDS = (
    "search", "find", "query", "submit", "send", "save", "done", "next", "continue", "start",
    "confirm", "ok", "yes", "allow", "agree", "login", "log in", "sign in", "register",
    "skip", "guest", "not now", "稍后", "跳过", "游客", "登录", "注册", "确认", "同意", "继续",
    "完成", "保存", "搜索"
)
HTML_SYSTEM_BAR_RESOURCE_IDS = {
    'android:id/navigationBarBackground',
    'android:id/statusBarBackground'
}

SIMILARITY_STRUCTURE_WEIGHT = 0.40
SIMILARITY_ACTIONABLE_WEIGHT = 0.30
SIMILARITY_SEMANTIC_WEIGHT = 0.20
SIMILARITY_ACTIVITY_WEIGHT = 0.05
SIMILARITY_STATE_FLAG_WEIGHT = 0.05


class DeviceState(object):
    """
    the state of the current device

    中文说明：DeviceState 是一次 UI 抓取后的页面快照。
    它保存原始 view hierarchy、可执行事件、HTML 描述、页面哈希和 LLMDroid 的 Widget 抽象。
    """

    def __init__(self, device, views, foreground_activity, activity_stack, background_services,
                 tag=None, screenshot_path=None):
        self.logger = get_logger()
        self.device = device
        self.foreground_activity: str = foreground_activity
        self.activity_stack = activity_stack if isinstance(activity_stack, list) else []
        self.background_services = background_services
        if tag is None:
            from datetime import datetime
            tag = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.tag = tag
        self.screenshot_path = screenshot_path

        self.views = self.__parse_views(views)
        self.view_tree = {}
        self.__assemble_view_tree(self.view_tree, self.views)
        self.__generate_view_strs()

        # init widget from view
        # LLMDroid 在 DroidBot 原始 view 之上额外构造 Widget，
        # 用于 HTML 化、页面相似度计算和 LLM 返回控件 id 后的事件匹配。
        self.__widgets: list[Widget] = []
        self.__merged_widgets = {}
        root = self.__init_widgets()
        self.__root_widget = views[root]['widget'] if root != -1 and 0 <= root < len(views) else None
        self.__similarity_features = self.__build_similarity_features()

        self.state_str = self.__get_state_str()
        self.structure_str = self.__get_content_free_state_str()
        self.search_content = self.__get_search_content()
        self.text_representation = self.get_text_representation()
        self.possible_events = []
        self.width = device.get_width(refresh=True)
        self.height = device.get_height(refresh=False)

        self.__html_desc: str = ''
        self.__tab_count: int = 0
        self.__html_tag_count: int = 0
        self.__html_selected_widget_ids: set[int] = set()
        self.__id = -1
        self.__cluster: StateCluster = None
        self.__lock = threading.Lock()

    @property
    def activity_short_name(self):
        return self.foreground_activity.split('.')[-1]

    def to_dict(self):
        state = {'tag': self.tag,
                 'state_str': self.state_str,
                 'state_str_content_free': self.structure_str,
                 'foreground_activity': self.foreground_activity,
                 'activity_stack': self.activity_stack,
                 'background_services': self.background_services,
                 'width': self.width,
                 'height': self.height,
                 'views': self.to_html()}
        return state

    def to_json(self):
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __parse_views(self, raw_views):
        # 这里保留原始 UIAutomator view 字典；后续 Widget/事件生成都基于这些字段。
        views = []
        if not raw_views or len(raw_views) == 0:
            return views

        for view_dict in raw_views:
            # # Simplify resource_id
            # resource_id = view_dict['resource_id']
            # if resource_id is not None and ":" in resource_id:
            #     resource_id = resource_id[(resource_id.find(":") + 1):]
            #     view_dict['resource_id'] = resource_id
            views.append(view_dict)
        return views

    def __assemble_view_tree(self, root_view, views):
        if not len(self.view_tree):  # bootstrap
            if not len(views):  # to fix if views is empty
                return
            self.view_tree = copy.deepcopy(views[0])
            if 'widget' in self.view_tree:
                del self.view_tree['widget']
            self.__assemble_view_tree(self.view_tree, views)
        else:
            children = list(enumerate(root_view["children"]))
            if not len(children):
                return
            for i, j in children:
                root_view["children"][i] = copy.deepcopy(self.views[j])
                if 'widget' in root_view["children"][i]:
                    del root_view["children"][i]['widget']
                self.__assemble_view_tree(root_view["children"][i], views)

    def __generate_view_strs(self):
        for view_dict in self.views:
            self.__get_view_str(view_dict)
            # self.__get_view_structure(view_dict)

    @staticmethod
    def __calculate_depth(views):
        root_view = None
        for view in views:
            if DeviceState.__safe_dict_get(view, 'parent') == -1:
                root_view = view
                break
        DeviceState.__assign_depth(views, root_view, 0)

    @staticmethod
    def __assign_depth(views, view_dict, depth):
        view_dict['depth'] = depth
        for view_id in DeviceState.__safe_dict_get(view_dict, 'children', []):
            DeviceState.__assign_depth(views, views[view_id], depth + 1)

    def __get_state_str(self):
        state_str_raw = self.__get_state_str_raw()
        return md5(state_str_raw)

    def __get_state_str_raw(self):
        if self.device.humanoid is not None:
            import json
            from xmlrpc.client import ServerProxy
            proxy = ServerProxy("http://%s/" % self.device.humanoid)
            return proxy.render_view_tree(json.dumps({
                "view_tree": self.view_tree,
                "screen_res": [self.device.display_info["width"],
                               self.device.display_info["height"]]
            }))
        else:
            view_signatures = set()
            for view in self.views:
                if self.__safe_dict_get(view, 'visible', False):
                    view_signature = DeviceState.__get_view_signature(view)
                    if view_signature:
                        view_signatures.add(view_signature)
            return "%s{%s}" % (self.foreground_activity, ",".join(sorted(view_signatures)))

    def __get_content_free_state_str(self):
        if self.device.humanoid is not None:
            import json
            from xmlrpc.client import ServerProxy
            proxy = ServerProxy("http://%s/" % self.device.humanoid)
            state_str = proxy.render_content_free_view_tree(json.dumps({
                "view_tree": self.view_tree,
                "screen_res": [self.device.display_info["width"],
                               self.device.display_info["height"]]
            }))
        else:
            view_signatures = set()
            for view in self.views:
                if self.__safe_dict_get(view, 'visible', False):
                    view_signature = DeviceState.__get_content_free_view_signature(view)
                    if view_signature:
                        view_signatures.add(view_signature)
            state_str = "%s{%s}" % (self.foreground_activity, ",".join(sorted(view_signatures)))
        import hashlib
        return hashlib.md5(state_str.encode('utf-8')).hexdigest()

    def __get_search_content(self):
        """
        get a text for searching the state
        :return: str
        """
        words = [",".join(self.__get_property_from_all_views("resource_id")),
                 ",".join(self.__get_property_from_all_views("text"))]
        return "\n".join(words)

    def __get_property_from_all_views(self, property_name):
        """
        get the values of a property from all views
        :return: a list of property values
        """
        property_values = set()
        for view in self.views:
            property_value = DeviceState.__safe_dict_get(view, property_name, None)
            if property_value:
                property_values.add(property_value)
        return property_values

    def save2dir(self, output_dir=None):
        try:
            if output_dir is None:
                if self.device.output_dir is None:
                    return
                else:
                    output_dir = os.path.join(self.device.output_dir, "states")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

            # save screenshot
            if self.device.adapters[self.device.minicap]:
                dest_screenshot_path = "%s/screen_%s.jpg" % (output_dir, self.tag)
            else:
                dest_screenshot_path = "%s/screen_%s.png" % (output_dir, self.tag)
            import shutil
            shutil.copyfile(self.screenshot_path, dest_screenshot_path)
            os.remove(self.screenshot_path)
            self.screenshot_path = dest_screenshot_path
            # save json file
            dest_state_json_path = os.path.join(output_dir, f"state_{self.__id}.json")
            self.logger.debug(f"sava state to {dest_state_json_path}")
            # dest_state_json_path = "%s/state_%s.json" % (output_dir, self.__id)
            state_json_file = open(dest_state_json_path, "w", encoding='utf-8')
            state_json_file.write(self.to_json())
            state_json_file.close()

            # from PIL.Image import Image
            # if isinstance(self.screenshot_path, Image):
            #     self.screenshot_path.save(dest_screenshot_path)
        except Exception as e:
            self.logger.warning(e)

    def save_view_img(self, view_dict, output_dir=None):
        try:
            if output_dir is None:
                if self.device.output_dir is None:
                    return
                else:
                    output_dir = os.path.join(self.device.output_dir, "views")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            view_str = view_dict['view_str']
            if self.device.adapters[self.device.minicap]:
                view_file_path = "%s/view_%s.jpg" % (output_dir, view_str)
            else:
                view_file_path = "%s/view_%s.png" % (output_dir, view_str)
            if os.path.exists(view_file_path):
                return
            from PIL import Image
            # Load the original image:
            view_bound = view_dict['bounds']
            original_img = Image.open(self.screenshot_path)
            # view bound should be in original image bound
            view_img = original_img.crop((min(original_img.width - 1, max(0, view_bound[0][0])),
                                          min(original_img.height - 1, max(0, view_bound[0][1])),
                                          min(original_img.width, max(0, view_bound[1][0])),
                                          min(original_img.height, max(0, view_bound[1][1]))))
            view_img.convert("RGB").save(view_file_path)
        except Exception as e:
            self.device.logger.warning(e)

    def is_different_from(self, another_state):
        """
        compare this state with another
        @param another_state: DeviceState
        @return: boolean, true if this state is different from other_state
        """
        return self.state_str != another_state.state_str

    @staticmethod
    def __get_view_signature(view_dict):
        """
        get the signature of the given view
        @param view_dict: dict, an element of list DeviceState.views
        @return:
        """
        if 'signature' in view_dict:
            return view_dict['signature']

        view_text = DeviceState.__safe_dict_get(view_dict, 'text', "None")
        if view_text is None or len(view_text) > 50:
            view_text = "None"

        signature = "[class]%s[resource_id]%s[text]%s[%s,%s,%s]" % \
                    (DeviceState.__safe_dict_get(view_dict, 'class', "None"),
                     DeviceState.__safe_dict_get(view_dict, 'resource_id', "None"),
                     view_text,
                     DeviceState.__key_if_true(view_dict, 'enabled'),
                     DeviceState.__key_if_true(view_dict, 'checked'),
                     DeviceState.__key_if_true(view_dict, 'selected'))
        view_dict['signature'] = signature
        return signature

    @staticmethod
    def __get_content_free_view_signature(view_dict):
        """
        get the content-free signature of the given view
        @param view_dict: dict, an element of list DeviceState.views
        @return:
        """
        if 'content_free_signature' in view_dict:
            return view_dict['content_free_signature']
        content_free_signature = "[class]%s[resource_id]%s" % \
                                 (DeviceState.__safe_dict_get(view_dict, 'class', "None"),
                                  DeviceState.__safe_dict_get(view_dict, 'resource_id', "None"))
        view_dict['content_free_signature'] = content_free_signature
        return content_free_signature

    def __get_view_str(self, view_dict):
        """
        get a string which can represent the given view
        @param view_dict: dict, an element of list DeviceState.views
        @return:
        """
        if 'view_str' in view_dict:
            return view_dict['view_str']
        view_signature = DeviceState.__get_view_signature(view_dict)
        parent_strs = []
        for parent_id in self.get_all_ancestors(view_dict):
            parent_strs.append(DeviceState.__get_view_signature(self.views[parent_id]))
        parent_strs.reverse()
        child_strs = []
        for child_id in self.get_all_children(view_dict):
            child_strs.append(DeviceState.__get_view_signature(self.views[child_id]))
        child_strs.sort()
        view_str = "Activity:%s\nSelf:%s\nParents:%s\nChildren:%s" % \
                   (self.foreground_activity, view_signature, "//".join(parent_strs), "||".join(child_strs))
        import hashlib
        view_str = hashlib.md5(view_str.encode('utf-8')).hexdigest()
        view_dict['view_str'] = view_str
        return view_str

    def __get_view_structure(self, view_dict):
        """
        get the structure of the given view
        :param view_dict: dict, an element of list DeviceState.views
        :return: dict, representing the view structure
        """
        if 'view_structure' in view_dict:
            return view_dict['view_structure']
        width = DeviceState.get_view_width(view_dict)
        height = DeviceState.get_view_height(view_dict)
        class_name = DeviceState.__safe_dict_get(view_dict, 'class', "None")
        children = {}

        root_x = view_dict['bounds'][0][0]
        root_y = view_dict['bounds'][0][1]

        child_view_ids = self.__safe_dict_get(view_dict, 'children')
        if child_view_ids:
            for child_view_id in child_view_ids:
                child_view = self.views[child_view_id]
                child_x = child_view['bounds'][0][0]
                child_y = child_view['bounds'][0][1]
                relative_x, relative_y = child_x - root_x, child_y - root_y
                children["(%d,%d)" % (relative_x, relative_y)] = self.__get_view_structure(child_view)

        view_structure = {
            "%s(%d*%d)" % (class_name, width, height): children
        }
        view_dict['view_structure'] = view_structure
        return view_structure

    @staticmethod
    def __key_if_true(view_dict, key):
        return key if (key in view_dict and view_dict[key]) else ""

    @staticmethod
    def __safe_dict_get(view_dict, key, default=None):
        value = view_dict[key] if key in view_dict else None
        return value if value is not None else default

    @staticmethod
    def __get_input_field_info(view_dict):
        keys = ['resource_id', 'content_description', 'text', 'hint', 'input_type', 'inputType', 'class']
        parts = []
        for key in keys:
            value = DeviceState.__safe_dict_get(view_dict, key, '')
            if value:
                parts.append(str(value))
        if DeviceState.__safe_dict_get(view_dict, 'is_password', False):
            parts.append('password')
        return ' '.join(parts).lower()

    @staticmethod
    def __infer_default_input_text(view_dict):
        field_info = DeviceState.__get_input_field_info(view_dict)
        if not field_info:
            return DEFAULT_INPUT_TEXT
        if re.search(r'password|passwd|\bpwd\b', field_info):
            return DEFAULT_PASSWORD_TEXT
        if re.search(r'email|e-mail|mail', field_info):
            return DEFAULT_EMAIL_TEXT
        if re.search(r'phone|mobile|tel|contact', field_info):
            return DEFAULT_PHONE_TEXT
        if re.search(r'date|birthday|birth|calendar|time', field_info):
            return DEFAULT_DATE_TEXT
        if re.search(r'number|numeric|decimal|digit|amount|count|age|weight|height|bmi', field_info):
            return DEFAULT_NUMBER_TEXT
        if re.search(r'search|query|keyword', field_info):
            return DEFAULT_SEARCH_TEXT
        return DEFAULT_INPUT_TEXT

    @staticmethod
    def get_view_center(view_dict):
        """
        return the center point in a view
        @param view_dict: dict, an element of DeviceState.views
        @return: a pair of int
        """
        bounds = view_dict['bounds']
        return (bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2

    @staticmethod
    def get_view_width(view_dict):
        """
        return the width of a view
        @param view_dict: dict, an element of DeviceState.views
        @return: int
        """
        bounds = view_dict['bounds']
        return int(math.fabs(bounds[0][0] - bounds[1][0]))

    @staticmethod
    def get_view_height(view_dict):
        """
        return the height of a view
        @param view_dict: dict, an element of DeviceState.views
        @return: int
        """
        bounds = view_dict['bounds']
        return int(math.fabs(bounds[0][1] - bounds[1][1]))

    def get_all_ancestors(self, view_dict):
        """
        Get temp view ids of the given view's ancestors
        :param view_dict: dict, an element of DeviceState.views
        :return: list of int, each int is an ancestor node id
        """
        result = []
        parent_id = self.__safe_dict_get(view_dict, 'parent', -1)
        if 0 <= parent_id < len(self.views):
            result.append(parent_id)
            result += self.get_all_ancestors(self.views[parent_id])
        return result

    def get_all_children(self, view_dict, visited=None):
        """
        Get temp view ids of the given view's children
        :param view_dict: dict, an element of DeviceState.views
        :return: set of int, each int is a child node id
        """
        children = self.__safe_dict_get(view_dict, 'children')
        if not children:
            return set()
        if visited is None:
            visited = set()
        children = set(children)
        result = set()
        for child in list(children):
            if child in visited:
                continue
            visited.add(child)
            result.add(child)
            children_of_child = self.get_all_children(self.views[child], visited)
            result.update(children_of_child)
        return result

    def get_app_activity_depth(self, app):
        """
        Get the depth of the app's activity in the activity stack
        :param app: App
        :return: the depth of app's activity, -1 for not found
        """
        depth = 0
        for activity_str in self.activity_stack:
            if app.package_name in activity_str:
                return depth
            depth += 1
        return -1

    def get_possible_input(self):
        """
        Get a list of possible input events for this state
        :return: list of InputEvent
        """
        # 候选事件只生成一次并缓存。后续 DroidBot/LLM 都从同一批事件里选择，
        # 这样可以保证控件 id、Widget 和 InputEvent 之间保持一致。
        if self.possible_events:
            return [] + self.possible_events
        possible_events = []
        enabled_view_ids = []
        touch_exclude_view_ids = set()
        touch_event_view_ids = set()

        def append_touch_event(view_id):
            if view_id not in touch_event_view_ids:
                possible_events.append(TouchEvent(view=self.views[view_id]))
                touch_event_view_ids.add(view_id)

        for view_dict in self.views:
            # exclude navigation bar if exists
            # 过滤系统状态栏/导航栏，避免把系统 UI 当作被测 App 的功能入口。
            if self.__safe_dict_get(view_dict, 'enabled') and \
                    self.__safe_dict_get(view_dict, 'visible') and \
                    self.__safe_dict_get(view_dict, 'resource_id') not in \
                    ['android:id/navigationBarBackground',
                     'android:id/statusBarBackground']:
                enabled_view_ids.append(view_dict['temp_id'])
        # enabled_view_ids.reverse()

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'clickable'):
                # clickable view 生成点击事件，是 DroidBot 最主要的原子动作来源。
                append_touch_event(view_id)
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids.update(self.get_all_children(self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'scrollable'):
                # 对可滚动控件生成四个方向，具体是否有效由设备执行后的状态变化决定。
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="up"))
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="down"))
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="left"))
                possible_events.append(ScrollEvent(view=self.views[view_id], direction="right"))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'checkable'):
                append_touch_event(view_id)
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids.update(self.get_all_children(self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'long_clickable'):
                possible_events.append(LongTouchEvent(view=self.views[view_id]))

        for view_id in enabled_view_ids:
            if self.__safe_dict_get(self.views[view_id], 'editable'):
                # editable view 默认生成 SetTextEvent，LLM Guidance 阶段可覆盖其中的 text。
                append_touch_event(view_id)
                input_text = self.__infer_default_input_text(self.views[view_id])
                possible_events.append(SetTextEvent(view=self.views[view_id], text=input_text))
                touch_exclude_view_ids.add(view_id)
                touch_exclude_view_ids.update(self.get_all_children(self.views[view_id]))

        # Set click events for child components of clickable components
        # 对叶子节点补充点击事件，提升黑盒场景下可探索动作的召回率。
        for view_id in enabled_view_ids:
            if view_id in touch_exclude_view_ids:
                continue
            children = self.__safe_dict_get(self.views[view_id], 'children')
            if children and len(children) > 0:
                continue
            append_touch_event(view_id)

        # For old Android navigation bars
        # possible_events.append(KeyEvent(name="MENU"))

        self.possible_events = possible_events
        return [] + possible_events

    @staticmethod
    def llm_action_type_value(action_type: ActionType) -> Optional[int]:
        action_mapping = {
            ActionType.CLICK: 0,
            ActionType.LONG_CLICK: 1,
            ActionType.SCROLL_TOP_DOWN: 2,
            ActionType.SCROLL_BOTTOM_UP: 3,
            ActionType.SCROLL_LEFT_RIGHT: 4,
            ActionType.SCROLL_RIGHT_LEFT: 5,
            ActionType.INPUT: 6,
        }
        return action_mapping.get(action_type)

    def to_llm_action_candidates(self) -> list[dict]:
        candidates = []
        seen_actions = set()
        for event in self.get_possible_input():
            if not isinstance(event, UIEvent):
                continue
            widget = event.get_target()
            if not widget or not widget.get_visible():
                continue
            action_value = DeviceState.llm_action_type_value(event.get_action_type())
            if action_value is None:
                continue
            action_key = (widget.get_id(), action_value)
            if action_key in seen_actions:
                continue
            seen_actions.add(action_key)
            candidates.append({
                "element_id": widget.get_id(),
                "action_type": action_value,
                "action_name": event.get_action_type().string,
                "widget_html": widget.to_html().strip(),
                "text": widget.get_text(),
                "content_desc": widget.get_content_desc(),
                "resource_id": widget.get_resource_id(),
                "class": widget.get_class(),
                "visit_count": event.get_visit_count(),
            })
        return candidates

    def find_event_by_llm_action(self, widget_id: int, action_offset: int) -> Optional['InputEvent']:
        for event in self.get_possible_input():
            if not isinstance(event, UIEvent):
                continue
            target = event.get_target()
            if not target:
                continue
            if target.get_id() != widget_id:
                continue
            if DeviceState.llm_action_type_value(event.get_action_type()) == action_offset:
                return event
        self.logger.warning(f"State{self.__id}: No LLM candidate matched by widget{widget_id} and action {action_offset}")
        return None

    def get_text_representation(self, merge_buttons=False):
        """
        Get a text representation of current state
        """
        # DroidBot 原始文本化页面描述；LLMDroid 的 LLM prompt 主要使用后面的 to_html()。
        enabled_view_ids = []
        for view_dict in self.views:
            # exclude navigation bar if exists
            if self.__safe_dict_get(view_dict, 'visible') and \
                    self.__safe_dict_get(view_dict, 'resource_id') not in \
                    ['android:id/navigationBarBackground',
                     'android:id/statusBarBackground']:
                enabled_view_ids.append(view_dict['temp_id'])

        text_frame = "<p id=@ text='&' attr=null bounds=null>#</p>"
        btn_frame = "<button id=@ text='&' attr=null bounds=null>#</button>"
        checkbox_frame = "<checkbox id=@ text='&' attr=null bounds=null>#</checkbox>"
        input_frame = "<input id=@ text='&' attr=null bounds=null>#</input>"
        scroll_frame = "<scrollbar id=@ attr=null bounds=null></scrollbar>"

        view_descs = []
        indexed_views = []
        # available_actions = []
        removed_view_ids = []

        for view_id in enabled_view_ids:
            if view_id in removed_view_ids:
                continue
            # print(view_id)
            view = self.views[view_id]
            clickable = self._get_self_ancestors_property(view, 'clickable')
            scrollable = self.__safe_dict_get(view, 'scrollable')
            checkable = self._get_self_ancestors_property(view, 'checkable')
            long_clickable = self._get_self_ancestors_property(view, 'long_clickable')
            editable = self.__safe_dict_get(view, 'editable')
            actionable = clickable or scrollable or checkable or long_clickable or editable
            checked = self.__safe_dict_get(view, 'checked', default=False)
            selected = self.__safe_dict_get(view, 'selected', default=False)
            content_description = self.__safe_dict_get(view, 'content_description', default='')
            view_text = self.__safe_dict_get(view, 'text', default='')
            view_class = self.__safe_dict_get(view, 'class').split('.')[-1]
            bounds = self.__safe_dict_get(view, 'bounds')
            view_bounds = f'{bounds[0][0]},{bounds[0][1]},{bounds[1][0]},{bounds[1][1]}'
            if not content_description and not view_text and not scrollable:  # actionable?
                continue

            # text = self._merge_text(view_text, content_description)
            # view_status = ''
            view_local_id = str(len(view_descs))
            if editable:
                view_desc = input_frame.replace('@', view_local_id).replace('#', view_text)
                if content_description:
                    view_desc = view_desc.replace('&', content_description)
                else:
                    view_desc = view_desc.replace(" text='&'", "")
                # available_actions.append(SetTextEvent(view=view, text='HelloWorld'))
            elif checkable:
                view_desc = checkbox_frame.replace('@', view_local_id).replace('#', view_text)
                if content_description:
                    view_desc = view_desc.replace('&', content_description)
                else:
                    view_desc = view_desc.replace(" text='&'", "")
                # available_actions.append(TouchEvent(view=view))
            elif clickable:  # or long_clickable
                if merge_buttons:
                    # below is to merge buttons, led to bugs
                    clickable_ancestor_id = self._get_ancestor_id(view=view, key='clickable')
                    if not clickable_ancestor_id:
                        clickable_ancestor_id = self._get_ancestor_id(view=view, key='checkable')
                    clickable_children_ids = self._extract_all_children(id=clickable_ancestor_id)
                    if view_id not in clickable_children_ids:
                        clickable_children_ids.append(view_id)
                    view_text, content_description = self._merge_text(clickable_children_ids)
                    checked = self._get_children_checked(clickable_children_ids)
                    # end of merging buttons
                view_desc = btn_frame.replace('@', view_local_id).replace('#', view_text)
                if content_description:
                    view_desc = view_desc.replace('&', content_description)
                else:
                    view_desc = view_desc.replace(" text='&'", "")
                # available_actions.append(TouchEvent(view=view))
                if merge_buttons:
                    for clickable_child in clickable_children_ids:
                        if clickable_child in enabled_view_ids and clickable_child != view_id:
                            removed_view_ids.append(clickable_child)
            elif scrollable:
                # print(view_id, 'continued')
                view_desc = scroll_frame.replace('@', view_local_id)
                # available_actions.append(ScrollEvent(view=view, direction='DOWN'))
                # available_actions.append(ScrollEvent(view=view, direction='UP'))
            else:
                view_desc = text_frame.replace('@', view_local_id).replace('#', view_text)
                if content_description:
                    view_desc = view_desc.replace('&', content_description)
                else:
                    view_desc = view_desc.replace(" text='&'", "")
                # available_actions.append(TouchEvent(view=view))

            allowed_actions = ['touch']
            special_attrs = []
            if editable:
                allowed_actions.append('set_text')
            if checkable:
                allowed_actions.extend(['select', 'unselect'])
                allowed_actions.remove('touch')
            if scrollable:
                allowed_actions.extend(['scroll up', 'scroll down'])
                allowed_actions.remove('touch')
            if long_clickable:
                allowed_actions.append('long_touch')
            if checked or selected:
                special_attrs.append('selected')
            view['allowed_actions'] = allowed_actions
            view['special_attrs'] = special_attrs
            view['local_id'] = view_local_id
            if len(special_attrs) > 0:
                special_attrs = ','.join(special_attrs)
                view_desc = view_desc.replace("attr=null", f"attr={special_attrs}")
            else:
                view_desc = view_desc.replace(" attr=null", "")
            view_desc = view_desc.replace("bounds=null", f"bound_box={view_bounds}")
            view_descs.append(view_desc)
            view['desc'] = view_desc.replace(f' id={view_local_id}', '').replace(f' attr={special_attrs}', '')
            indexed_views.append(view)

        # prefix = 'The current state has the following UI elements: \n' #views and corresponding actions, with action id in parentheses:\n '
        state_desc = '\n'.join(view_descs)
        activity = self.foreground_activity.split('/')[-1]
        # print(views_without_id)
        return state_desc, activity, indexed_views

    def _get_self_ancestors_property(self, view, key, default=None):
        all_views = [view] + [self.views[i] for i in self.get_all_ancestors(view)]
        for v in all_views:
            value = self.__safe_dict_get(v, key)
            if value:
                return value
        return default

    def _merge_text(self, children_ids):
        texts, content_descriptions = [], []
        for childid in children_ids:
            if not self.__safe_dict_get(self.views[childid], 'visible') or \
                    self.__safe_dict_get(self.views[childid], 'resource_id') in \
                    ['android:id/navigationBarBackground',
                     'android:id/statusBarBackground']:
                # if the successor is not visible, then ignore it!
                continue

            text = self.__safe_dict_get(self.views[childid], 'text', default='')
            if len(text) > 50:
                text = text[:50]

            if text != '':
                # text = text + '  {'+ str(childid)+ '}'
                texts.append(text)

            content_description = self.__safe_dict_get(self.views[childid], 'content_description', default='')
            if len(content_description) > 50:
                content_description = content_description[:50]

            if content_description != '':
                content_descriptions.append(content_description)

        merged_text = '<br>'.join(texts) if len(texts) > 0 else ''
        merged_desc = '<br>'.join(content_descriptions) if len(content_descriptions) > 0 else ''
        return merged_text, merged_desc

    def __init_widgets(self) -> int:
        # create widgets
        # 只为可见 view 创建 Widget，随后按 hash 合并重复控件，减少页面相似度和 HTML 的噪声。
        first_visible = -1
        for i, view in enumerate(self.views):
            if self.__safe_dict_get(view, 'visible'):
                if first_visible == -1:
                    first_visible = i
                self.__widgets.append(Widget(view))
        if first_visible == -1:
            self.logger.error("Can't find ROOT(first visible) widget!!!")

        # merge widgets
        # 相同 hash 的控件被视为重复控件，保留一个代表，同时记录 position 方便后续找相似控件。
        final_widgets = []
        for widget in self.__widgets:
            hashcode = widget.get_hash()
            # add widget with same hash into merged_widgets
            if hashcode in self.__merged_widgets.keys():
                widget.set_position(len(self.__merged_widgets[hashcode]))
                self.__merged_widgets[hashcode].append(widget)
            else:
                final_widgets.append(widget)
                widget.set_position(-1)
                self.__merged_widgets[hashcode] = []
        # every widget in widgets has unique hash
        self.__widgets = final_widgets
        return first_visible

    def __should_merge(self, father: Widget, child: Widget):
        # button 只有一个普通文本子节点时，把文本合并进 button，降低 HTML 层级。
        if len(child.get_children()) == 0 and \
                child.get_html_class() == HtmlClass.P and \
                father.get_html_class() == HtmlClass.BUTTON:
            return True
        else:
            return False

    def __is_system_bar_view(self, view_dict) -> bool:
        return self.__safe_dict_get(view_dict, 'resource_id') in HTML_SYSTEM_BAR_RESOURCE_IDS

    def __widget_view(self, widget: Widget):
        widget_id = widget.get_id()
        if 0 <= widget_id < len(self.views):
            return self.views[widget_id]
        return None

    def __widget_text_blob(self, widget: Widget) -> str:
        view = self.__widget_view(widget) or {}
        parts = [
            widget.get_text(),
            widget.get_content_desc(),
            widget.get_resource_id(),
            widget.get_hint(),
            widget.get_class(),
            str(self.__safe_dict_get(view, 'resource_id', '')),
        ]
        return ' '.join([str(part) for part in parts if part]).lower()

    def __is_in_screen(self, widget: Widget) -> bool:
        view = self.__widget_view(widget)
        if not view:
            return False
        bounds = self.__safe_dict_get(view, 'bounds')
        if not bounds:
            return False
        left, top = bounds[0]
        right, bottom = bounds[1]
        return right > 0 and bottom > 0 and left < self.width and top < self.height

    def __is_nav_region(self, widget: Widget) -> bool:
        view = self.__widget_view(widget)
        if not view:
            return False
        bounds = self.__safe_dict_get(view, 'bounds')
        if not bounds or self.height <= 0:
            return False
        top = bounds[0][1]
        bottom = bounds[1][1]
        center_y = (top + bottom) / 2
        text_blob = self.__widget_text_blob(widget)
        in_vertical_nav = (
            center_y <= self.height * HTML_NAV_TOP_RATIO
            or center_y >= self.height * (1 - HTML_NAV_BOTTOM_RATIO)
        )
        has_nav_keyword = any(keyword in text_blob for keyword in HTML_NAV_KEYWORDS)
        return in_vertical_nav or has_nav_keyword

    def __has_important_text(self, widget: Widget) -> bool:
        text_blob = self.__widget_text_blob(widget)
        return any(keyword in text_blob for keyword in HTML_IMPORTANT_KEYWORDS)

    def __html_actionable_widget_ids(self) -> set[int]:
        actionable_ids = set()
        for event in self.get_possible_input():
            if not isinstance(event, UIEvent):
                continue
            target = event.get_target()
            if target and target.get_visible():
                actionable_ids.add(target.get_id())
        return actionable_ids

    def __widget_depth(self, widget: Widget) -> int:
        depth = 0
        parent_id = widget.parent
        while parent_id != -1:
            depth += 1
            parent = safe_dict_get(self.views[parent_id], 'widget', None)
            if not parent:
                break
            parent_id = parent.parent
        return depth

    def __html_widget_with_ancestors(self, widget: Widget) -> set[int]:
        ids = {widget.get_id()}
        parent_id = widget.parent
        while parent_id != -1:
            parent = safe_dict_get(self.views[parent_id], 'widget', None)
            if not parent or not parent.get_visible():
                break
            ids.add(parent.get_id())
            parent_id = parent.parent
        return ids

    def __widget_has_text(self, widget: Widget) -> bool:
        return bool(widget.get_text() or widget.get_content_desc() or widget.get_resource_id() or widget.get_hint())

    def __html_widget_score(self, widget: Widget, actionable_ids: set[int]) -> int:
        view = self.__widget_view(widget)
        if not view or self.__is_system_bar_view(view) or not widget.get_visible():
            return -100000

        score = 0
        html_class = widget.get_html_class()
        if widget.get_id() in actionable_ids:
            score += 1000
        if html_class == HtmlClass.INPUT:
            score += 350
        elif html_class == HtmlClass.CHECKBOX:
            score += 300
        elif html_class == HtmlClass.BUTTON:
            score += 260
        elif html_class == HtmlClass.SCROLLER:
            score += 180

        if self.__is_in_screen(widget):
            score += 140
        if self.__is_nav_region(widget):
            score += 120
        if self.__has_important_text(widget):
            score += 90
        if self.__widget_has_text(widget):
            score += 35
        if html_class == HtmlClass.P and not self.__widget_has_text(widget):
            score -= 160

        score -= self.__widget_depth(widget) * 2
        position = widget.get_position()
        if position > 0:
            score -= min(position, 20) * 3
        return score

    def __select_html_widget_ids(self) -> tuple[set[int], int, int]:
        visible_widgets = [
            widget for widget in self.get_all_widgets()
            if widget.get_visible()
            and not self.__is_system_bar_view(self.__widget_view(widget) or {})
        ]
        actionable_ids = self.__html_actionable_widget_ids()
        selected_ids = set()

        if self.__root_widget and self.__root_widget.get_visible():
            selected_ids.add(self.__root_widget.get_id())

        scored_widgets = []
        for order, widget in enumerate(visible_widgets):
            score = self.__html_widget_score(widget, actionable_ids)
            scored_widgets.append((score, -order, widget))

        scored_widgets.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _, _, widget in scored_widgets:
            if len(selected_ids) >= HTML_MAX_TAGS:
                break
            candidate_ids = self.__html_widget_with_ancestors(widget)
            if candidate_ids.issubset(selected_ids):
                continue
            if len(selected_ids | candidate_ids) <= HTML_MAX_TAGS:
                selected_ids.update(candidate_ids)

        return selected_ids, len(actionable_ids), len(visible_widgets)

    def __add_tab(self) -> None:
        for i in range(self.__tab_count):
            self.__html_desc += '\t'

    def __should_render_html_widget(self, widget: Widget) -> bool:
        return widget.get_id() in self.__html_selected_widget_ids

    def __generate_html_recursive(self, parent: Widget):
        # 将 Widget 树转成紧凑 HTML。LLM 看到的是这个 HTML，而不是原始 UIAutomator JSON。
        if not parent.get_visible():
            return
        if not self.__should_render_html_widget(parent):
            return

        if self.__tab_count >= HTML_MAX_DEPTH or self.__html_tag_count >= HTML_MAX_TAGS:
            # 防止复杂页面生成超长 prompt，牺牲部分细节换取模型可处理性和成本可控。
            return

        self.__html_tag_count += 1
        self.__tab_count += 1
        self.__add_tab()

        widget_to_merge = []
        widget_not_merge = []

        check_list: list[Widget] = [parent]
        # for id in parent.get_children():
        #     w = safe_dict_get(self.views[id], 'widget', None)
        #     if w:
        #         check_list.append(w)

        while len(check_list) != 0:
            widget = check_list[0]
            check_list.remove(widget)
            # [self.views[id]['widget'] for id in widget.get_children()]
            child_widgets = []
            for id in widget.get_children():
                w = safe_dict_get(self.views[id], 'widget', None)
                if w:
                    child_widgets.append(w)
            # Merge nested situations to reduce depth
            # There is only one child node, and the child node is of normal type
            # 单链路普通文本节点会被合并，避免无意义的深层嵌套干扰 LLM。
            if len(child_widgets) == 1 and child_widgets[0].get_html_class() == HtmlClass.P:
                widget_to_merge.append(child_widgets[0])
                # self.logger.debug(f'[to html] merge widget: {child_widgets[0].to_html()[:-1]}')
                # Keep checking down
                check_list.append(child_widgets[0])
            else:
                # Do not merge when there are more than 1 child nodes
                if len(child_widgets) > 1:
                    widget_not_merge += [widget for widget in child_widgets]
                else:
                    # There may be no child nodes, or only one child node
                    # Perform a general check, that is, whether button and child node p can merge text
                    for child in child_widgets:
                        # child_view = self.views[id]['widget']
                        if self.__should_merge(widget, child):
                            widget_to_merge.append(child)
                        else:
                            widget_not_merge.append(child)

        widget_not_merge = [
            widget for widget in widget_not_merge
            if self.__should_render_html_widget(widget)
        ]
        has_child: bool = True if widget_not_merge else False
        self.__html_desc += parent.to_html(widget_to_merge, has_child)

        for widget in widget_not_merge:
            if self.__html_tag_count >= HTML_MAX_TAGS:
                break
            self.__generate_html_recursive(widget)

        if has_child:
            self.__add_tab()
            self.__html_desc += parent.get_html_class().end_tag + '\n'
        self.__tab_count -= 1

    def to_html(self) -> str:
        """
        return state description in html format.
        only generate html once
        """
        # 线程锁保证 LLMAgent 子线程和主探索线程同时读取时不会重复生成/破坏 HTML。
        with self.__lock:
            if self.__html_desc:
                return self.__html_desc

            selected_ids, actionable_count, visible_count = self.__select_html_widget_ids()
            self.__html_selected_widget_ids = selected_ids
            self.__html_desc = ''
            self.__html_tag_count = 0
            self.__tab_count = -1
            if not self.__root_widget:
                return self.__html_desc
            self.__generate_html_recursive(self.__root_widget)
            clipped_count = max(0, visible_count - self.__html_tag_count)
            hit_budget = self.__html_tag_count >= HTML_MAX_TAGS
            self.logger.debug(
                "[to_html] visible=%d selected=%d tags=%d actionable=%d clipped=%d hit_budget=%s",
                visible_count,
                len(selected_ids),
                self.__html_tag_count,
                actionable_count,
                clipped_count,
                hit_budget,
            )

            return self.__html_desc

    def set_id(self, value) -> None:
        self.__id = value

    def get_id(self) -> int:
        return self.__id

    def __build_similarity_features(self) -> dict:
        structure_histogram = self.__wl_structure_histogram()
        structure_hashes = set()
        actionable_hashes = set()
        semantic_tokens = set()
        state_flags = set()

        for widget in self.__widgets:
            widget_hash = widget.get_hash()
            structure_hashes.add(widget_hash)

            if self.__is_actionable_widget(widget):
                actionable_hashes.add(widget_hash)

            semantic_tokens.update(self.__widget_semantic_tokens(widget))
            state_flags.update(self.__widget_state_flags(widget))

        return {
            'structure_histogram': structure_histogram,
            'structure_hashes': structure_hashes,
            'actionable_hashes': actionable_hashes,
            'semantic_tokens': semantic_tokens,
            'state_flags': state_flags,
        }

    def __wl_structure_histogram(self, iterations: int = 2) -> Counter:
        node_views, adj = self.__build_similarity_graph()
        if not node_views:
            return Counter()

        root = next(
            (
                idx for idx, view in enumerate(node_views)
                if self.__safe_dict_get(view, 'parent', -1) == -1
            ),
            0,
        )
        depths = self.__bfs_depth(adj, root)
        labels = {
            idx: self.__initial_wl_label(view, depths.get(idx, 0))
            for idx, view in enumerate(node_views)
        }

        for _ in range(iterations):
            labels = {
                idx: (
                    'wl',
                    labels[idx],
                    tuple(sorted(labels[neighbor] for neighbor in adj.get(idx, ()))),
                )
                for idx in range(len(node_views))
            }

        return Counter(labels.values())

    def __build_similarity_graph(self) -> tuple[list[dict], dict[int, set[int]]]:
        node_views = []
        temp_id_to_idx = {}

        for view in self.views:
            if not self.__safe_dict_get(view, 'visible'):
                continue
            if self.__is_system_bar_view(view):
                continue

            temp_id = self.__safe_dict_get(view, 'temp_id')
            if temp_id is None:
                continue

            temp_id_to_idx[temp_id] = len(node_views)
            node_views.append(view)

        adj = {idx: set() for idx in range(len(node_views))}

        def link(left: int, right: int):
            adj[left].add(right)
            adj[right].add(left)

        for idx, view in enumerate(node_views):
            parent_id = self.__safe_dict_get(view, 'parent', -1)
            if parent_id in temp_id_to_idx:
                link(idx, temp_id_to_idx[parent_id])

            for child_id in self.__safe_dict_get(view, 'children', []) or []:
                if child_id in temp_id_to_idx:
                    link(idx, temp_id_to_idx[child_id])

        return node_views, adj

    @staticmethod
    def __bfs_depth(adj: dict[int, set[int]], root: int) -> dict[int, int]:
        depths = {root: 0}
        queue = deque([root])
        while queue:
            current = queue.popleft()
            for neighbor in adj.get(current, ()):
                if neighbor in depths:
                    continue
                depths[neighbor] = depths[current] + 1
                queue.append(neighbor)
        return depths

    def __initial_wl_label(self, view: dict, depth: int) -> tuple:
        class_name = (self.__safe_dict_get(view, 'class', '') or 'Unknown').split('.')[-1]
        resource_id = (self.__safe_dict_get(view, 'resource_id', '') or '').split('/')[-1]
        role = self.__view_role(view)
        depth_bucket = min(depth // 2, 8)
        return ('view', class_name, resource_id, role, depth_bucket)

    @staticmethod
    def __view_role(view: dict) -> str:
        if DeviceState.__safe_dict_get(view, 'editable'):
            return 'input'
        if DeviceState.__safe_dict_get(view, 'checkable'):
            return 'check'
        if DeviceState.__safe_dict_get(view, 'scrollable'):
            return 'scroll'
        if DeviceState.__safe_dict_get(view, 'clickable'):
            return 'click'
        text = DeviceState.__safe_dict_get(view, 'text', '') or DeviceState.__safe_dict_get(
            view, 'content_description', ''
        )
        return 'text' if text and str(text).strip() else 'layout'

    @staticmethod
    def __cosine_counter(left: Counter, right: Counter) -> float:
        if not left or not right:
            return 0.0
        dot = sum(left[key] * right[key] for key in (set(left) & set(right)))
        left_norm = sum(value * value for value in left.values()) ** 0.5
        right_norm = sum(value * value for value in right.values()) ** 0.5
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def __dice_similarity(left: set, right: set) -> float:
        total = len(left) + len(right)
        if total == 0:
            return 0.0
        return (2 * len(left & right)) / total

    @staticmethod
    def __jaccard_similarity(left: set, right: set) -> float:
        union = left | right
        if len(union) == 0:
            return 0.0
        return len(left & right) / len(union)

    @staticmethod
    def __is_actionable_widget(widget: Widget) -> bool:
        return (
            widget.get_clickable()
            or widget.get_editable()
            or widget.get_checkable()
            or widget.get_scrollable()
        )

    @staticmethod
    def __is_layout_widget(widget: Widget) -> bool:
        class_name = widget.get_class().lower()
        return 'layout' in class_name or class_name in {
            'viewgroup',
            'view',
            'framelayout',
            'linearlayout',
            'relativelayout',
            'constraintlayout',
        }

    def __widget_semantic_tokens(self, widget: Widget) -> set[str]:
        if self.__is_layout_widget(widget) and not self.__is_actionable_widget(widget):
            return set()

        tokens = set()
        values = [
            widget.get_resource_id(),
            widget.get_content_desc(),
            widget.get_hint(),
            widget.get_class(),
        ]
        if self.__is_actionable_widget(widget):
            values.append(widget.get_text())
        for value in values:
            tokens.update(self.__normalize_tokens(value))
        return tokens

    @staticmethod
    def __normalize_tokens(value: str) -> set[str]:
        if not value:
            return set()
        value = str(value).strip().lower()
        if len(value) > 50:
            return set()
        if DeviceState.__is_dynamic_token(value):
            return set()

        tokens = set()
        for token in re.split(r'[^0-9a-zA-Z_]+', value):
            token = token.strip('_')
            if len(token) < 2:
                continue
            if DeviceState.__is_dynamic_token(token):
                continue
            tokens.add(token)
        return tokens

    @staticmethod
    def __is_dynamic_token(token: str) -> bool:
        if token.isdigit():
            return True
        if len(token) > 50:
            return True
        if re.fullmatch(r'\d{4}[-_/]?\d{1,2}[-_/]?\d{1,2}', token):
            return True
        if re.fullmatch(r'\d{1,2}:\d{2}(:\d{2})?', token):
            return True
        if re.fullmatch(r'[\w.+-]+@[\w-]+(\.[\w-]+)+', token):
            return True
        if re.fullmatch(r'1\d{10}', token):
            return True
        if re.fullmatch(r'[0-9a-f]{8}([0-9a-f]{4}){3}[0-9a-f]{12}', token):
            return True
        if re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', token):
            return True
        return False

    def __widget_state_flags(self, widget: Widget) -> set[str]:
        flags = set()
        class_name = widget.get_class()
        if widget.get_checked():
            flags.add(f'{class_name}:checked')
        if widget.get_selected():
            flags.add(f'{class_name}:selected')
        if widget.get_editable():
            flags.add(f'{class_name}:editable')
        if widget.get_scrollable():
            flags.add(f'{class_name}:scrollable:{widget.get_scroll_type().name.lower()}')
        return flags

    def __activity_similarity(self, other: 'DeviceState') -> float:
        if self.foreground_activity == other.foreground_activity:
            return 1.0

        def package_name(activity: str) -> str:
            return activity.split('/')[0] if activity else ''

        if package_name(self.foreground_activity) and package_name(self.foreground_activity) == package_name(other.foreground_activity):
            return 0.3
        return 0.0

    def compute_similarity(self, other: 'DeviceState') -> float:
        # 页面相似度用于 StateCluster 聚类：结构为主，关键控件和语义 token 辅助区分同结构页面。
        self_features = self.__similarity_features
        other_features = other.__similarity_features
        if not self_features['structure_histogram'] and not other_features['structure_histogram']:
            return 0.0

        structure_similarity = self.__cosine_counter(
            self_features['structure_histogram'],
            other_features['structure_histogram'],
        )
        actionable_similarity = self.__dice_similarity(
            self_features['actionable_hashes'],
            other_features['actionable_hashes'],
        )
        if not self_features['actionable_hashes'] and not other_features['actionable_hashes']:
            actionable_similarity = structure_similarity

        semantic_similarity = self.__jaccard_similarity(
            self_features['semantic_tokens'],
            other_features['semantic_tokens'],
        )
        activity_similarity = self.__activity_similarity(other)
        state_flag_similarity = self.__dice_similarity(
            self_features['state_flags'],
            other_features['state_flags'],
        )

        similarity = (
            SIMILARITY_STRUCTURE_WEIGHT * structure_similarity
            + SIMILARITY_ACTIONABLE_WEIGHT * actionable_similarity
            + SIMILARITY_SEMANTIC_WEIGHT * semantic_similarity
            + SIMILARITY_ACTIVITY_WEIGHT * activity_similarity
            + SIMILARITY_STATE_FLAG_WEIGHT * state_flag_similarity
        )
        similarity = max(0.0, min(1.0, similarity))

        # self.logger.debug(
        #     f"Similarity State{self.__id}-State{other.__id}: "
        #     f"total={similarity:.3f} "
        #     f"structure={structure_similarity:.3f} "
        #     f"actionable={actionable_similarity:.3f} "
        #     f"semantic={semantic_similarity:.3f} "
        #     f"activity={activity_similarity:.3f} "
        #     f"flags={state_flag_similarity:.3f}"
        # )
        return similarity

    def get_cluster(self) -> 'StateCluster':
        return self.__cluster

    def set_cluster(self, cluster: 'StateCluster'):
        self.__cluster = cluster

    def get_all_widgets(self) -> list[Widget]:
        all_widgets = []
        for widget in self.__widgets:
            all_widgets.append(widget)
            if widget.get_hash() in self.__merged_widgets:
                all_widgets.extend(self.__merged_widgets[widget.get_hash()])
        return all_widgets

    def find_widget_by_id(self, widget_id: int) -> Optional[Widget]:
        """
        Given the id of a widget, return the corresponding widget
        The widget_id should be the id of the widget inside the state, and should not come from the widget_id in other states.
        """
        # LLM 返回的 Element Id 最终会在当前 DeviceState 中解析为 Widget。
        for widget in self.get_all_widgets():
            if widget_id == widget.get_id():
                return widget
        return None

    def find_similar_widget(self, widget: Widget) -> Optional[Widget]:
        """
        Given a widget in another state, return similar widget in the current state
        First look for widget with the same hash, and then try to select widget with the same position.
        """
        # 导航过程中页面可能轻微变化，该方法用于在新页面上寻找“同类控件”以继续执行计划。
        hash_to_match = widget.get_hash()
        pos_to_match = widget.get_position()
        for w in self.__widgets:
            if w.get_hash() == hash_to_match:
                if pos_to_match == -1:
                    return w
                # similar widget may be in merged_widgets
                elif hash_to_match in self.__merged_widgets:
                    # find in merged_widgets
                    if pos_to_match < len(self.__merged_widgets[hash_to_match]):
                        return self.__merged_widgets[hash_to_match][pos_to_match]
                    elif len(self.__merged_widgets[hash_to_match]) > 0:
                        return self.__merged_widgets[hash_to_match][-1]
                    else:
                        return w
                else:
                    return w

        return None

    def print_events(self):
        events = []
        for event in self.get_possible_input():
            if event.get_visit_count() >= 1:
                events.append(event)
        self.logger.info("*******************visited event:")
        self.logger.info([event.to_description() for event in events])
        self.logger.info("*********************************")

    def find_similar_event(self, event: InputEvent) -> Optional[InputEvent]:
        # 根据动作类型 + 目标 Widget hash，在当前页面中寻找与历史路径事件等价的事件。
        # ActionType.CLICK.value <= event.get_action_type().value <= ActionType.SCROLL_RIGHT_LEFT
        if isinstance(event, UIEvent):
            action_type = event.get_action_type()
            widget = event.get_target()
            widget_hash = widget.get_hash()
            which_widget = widget.get_position()
            # Filter out all events with the same action type and the same target hash
            candidates = []
            for event in self.get_possible_input():
                if isinstance(event, UIEvent):
                    if event.get_target() and event.get_target().get_hash() == widget_hash and event.get_action_type() == action_type:
                        candidates.append(event)
            candidates = sorted(candidates, key=lambda x: abs(x.get_target().get_position() - which_widget))
            ret = None
            # Prioritize the widget with the same pos, and if it does not exist, select the widget closest to it.
            for candidate in candidates:
                if which_widget == candidate.get_target().get_position():
                    ret = candidate
                    break
            if ret is None and candidates:
                ret = candidates[0]
            return ret
        else:
            return event

    def find_event_by_id_and_type(self, widget_id: int, act_type: ActionType) -> Optional['InputEvent']:
        # 将 LLM 的结构化输出（控件 id + 动作类型）映射回 DroidBot 可执行的 InputEvent。
        for event in self.get_possible_input():
            if (isinstance(event, UIEvent)
                    and event.get_action_type() == act_type
                    and event.get_target().get_id() == widget_id):
                return event
        self.logger.warning(f"State{self.__id}: No qualified event matched by widget{widget_id} and {act_type}")
        return None

    def find_events_by_widget(self, widget: 'Widget') -> list['UIEvent']:
        """
        find all relevant events by widget
        """
        # StateCluster 会用它把某个功能绑定到具体 Widget 上可执行的动作。
        ret = []
        for event in self.get_possible_input():
            if isinstance(event, UIEvent) and event.get_target() == widget:
                ret.append(event)
        return ret

    def diff_widgets(self, target: 'DeviceState') -> list['Widget']:
        # return widget with different hash
        # ignore Layout
        # reanalysis 阶段只把与 root state 不同的控件提交给 LLM，减少 prompt 长度。
        if target == self:
            return []
        res: list['Widget'] = []
        target_hashes = target.__similarity_features['structure_hashes']
        for widget in self.__widgets:
            if widget.get_hash() not in target_hashes and widget.get_class().lower().find("layout") == -1:
                res.append(widget)
        return res

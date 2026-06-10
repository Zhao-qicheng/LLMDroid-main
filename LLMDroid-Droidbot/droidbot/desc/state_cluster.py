# 文件作用：
# 1. 将相似 DeviceState 合并为页面簇，保存页面概览、功能列表和功能优先级。
# 2. 接收 LLMAgent 的页面摘要/重分析结果，并把功能语义绑定到具体 Widget/事件。
# 3. 作为 ActionListener 监听动作执行，用于标记对应功能是否已经测试。
import threading

from ..global_log import get_logger
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypedDict, Optional
from ..policy.llm_agent import TopCluster

if TYPE_CHECKING:
    from .device_state import DeviceState
    from ..input_event import UIEvent


class FunctionDetail(TypedDict):
    # LLM 识别出的功能会绑定到一个 widget/state，并用 importance 表示优先级；0 表示已测试。
    widget_id: int
    importance: int
    state: 'DeviceState'


class ActionListener(ABC):
    # UIEvent 执行后回调的监听接口，StateCluster 用它把动作和功能完成状态关联起来。
    @abstractmethod
    def on_action_executed(self, event: 'UIEvent'):
        pass


class StateCluster(ActionListener):
    """
    中文说明：StateCluster 把相似页面合并成一个“页面簇”。
    LLM 对 cluster 做页面摘要和功能识别，后续 Guidance 也是在 cluster/function 层面选目标。
    """

    def __init__(self, state: 'DeviceState', total: int):
        self.logger = get_logger()
        self.__root_state = state
        self.__states: set['DeviceState'] = set()
        self.__states.add(state)
        self.__id = total

        self.__overview: str = ''
        # key: function(str)
        # value: {importance: int(0 means tested), widget_id: corresponding widget's id}
        # function 列表来自 LLM，importance 越高越优先；执行过对应动作后会降为 0。
        self.__functions: dict[str, FunctionDetail] = {}
        self.__analysed = False
        self.__lock = threading.Lock()
        self.__listener_lock = threading.Lock()
        self.__need_reanalysed: bool = False

    def get_root_state(self) -> 'DeviceState':
        return self.__root_state

    def to_json(self, reanalysis: bool = False):
        ret = {
            "Overview": self.__overview,
            "Function List": [func for func in self.__functions.keys()]
        }
        if not reanalysis:
            ret["id"] = self.__id
            ret["root"] = f"State{self.__root_state.get_id()}"
            ret["states"] = [state.get_id() for state in self.__states],
            functions = {}
            for func in self.__functions:
                functions[func] = self.__functions[func]['importance']
            ret["Function List"] = functions
        return ret

    def on_action_executed(self, event: 'UIEvent'):
        """
        call from main/child thread
        """
        # event->widget->function marked as done
        # 当某个 UIEvent 被执行，如果其 Widget 已绑定 function，就把该 function 标记为已测试。
        if event.get_visit_count() > 0:
            widget = event.get_target()
            if widget:
                function = widget.get_function()
                with self.__listener_lock:
                    if function:
                        if function in self.__functions:
                            self.__functions[function]['importance'] = 0
                            self.logger.info(f'Function:{function} is tested by performing {event.to_description()}')
                        else:
                            self.logger.warning(f'event({event.to_description()}) has no corresponding function')
            else:
                self.logger.warning(f'UI Event({event.to_description()}) has no target widget!')

    def update_tested_function(self, function: str):
        """
        call from main thread
        Update functions completed by llm testing (test function mode)
        """
        # LLM Guidance 结束后显式标记目标功能，避免后续反复选择同一个语义目标。
        with self.__lock:
            if function in self.__functions:
                self.__functions[function]['importance'] = 0
            else:
                self.__functions[function] = FunctionDetail(widget_id=-1, importance=0, state=self.__root_state)

    def update_from_overview(self, answer):
        """
        call from child thread
        """
        # OVERVIEW 响应写入 cluster：页面概览、功能列表、功能到 root widget 的绑定关系。
        with self.__lock:
            self.__overview = answer['Overview']
            # key:function, value: widget's id
            function_list: dict = answer['Function List']

            # Iterate through all keys of function list
            for i, key in enumerate(function_list.keys()):
                self.__functions[key] = FunctionDetail(widget_id=function_list[key], importance=len(function_list) - i,
                                                       state=self.__root_state)

            self.__set_function_to_widget(function_list)
            self.__update_completed_functions()
            self.__analysed = True

    def __set_function_to_widget(self, function_list):
        # 将 LLM 返回的 widget_id 映射到 Widget，并同步到同 cluster 的相似页面。
        for function in function_list.keys():
            widget_id = function_list[function]
            # Set function for all widgets in the root state
            widget = self.__root_state.find_widget_by_id(widget_id)
            if widget:
                widget.set_function(function)
                # find similar widget in other states and set function
                for state in self.__states:
                    if state == self.__root_state:
                        continue
                    other_widget = state.find_similar_widget(widget)
                    if other_widget:
                        other_widget.set_function(function)
                    else:
                        self.logger.info(f"({function}:{widget_id}) can't find widget in State{state.get_id()}")
            else:
                self.logger.warning(
                    f"({function}:{widget_id}) can't find widget in Root State{self.__root_state.get_id()}")

    def __update_completed_functions(self):
        """
        For all states currently included, set listeners for actions and update completed functions.
        At this time, we have just obtained the analysis results of llm on the cluster.
        """
        # 给当前 cluster 内所有事件设置 listener，后续事件执行即可自动更新功能完成状态。
        for state in self.__states:
            for event in state.get_possible_input():
                # first call on_action_executed
                # to prevent the situation that on_action_executed was called twice after set_listener
                self.on_action_executed(event)
                event.set_listener(self)

    def __update_later_joined_state(self, state: 'DeviceState'):
        """
        call from main thread
        Set the function of the widget in state
        """
        # 如果页面在 LLM 分析后才加入 cluster，尝试把 root state 的功能绑定迁移到新页面。
        self.logger.info(f"Update later joined State{state.get_id()}...")
        for widget in self.__root_state.get_all_widgets():
            function = widget.get_function()
            if not function:
                continue
            target = state.find_similar_widget(widget)
            if target:
                target.set_function(function)
                self.logger.info(
                    f"Successfully set function:{function} to widget({target.to_html()[:-1]}) in State{state.get_id()}")
            else:
                self.logger.info(f"widget({widget.to_html()[:-1]}) doesn't have similar one in State{state.get_id()}")

        # set listener to event
        for event in state.get_possible_input():
            event.set_listener(self)

    def update_from_reanalysis(self, json_resp, unique_widgets: dict[str, list[int]], widgets_dict):
        # REANALYSIS 响应只处理新增/差异控件，避免对整个 cluster 重新做昂贵分析。
        with self.__lock:
            try:
                for id_str in json_resp.keys():
                    id = int(id_str)
                    function = json_resp[id_str]
                    if function not in self.__functions:
                        # consider the importance as 1
                        self.__functions[function] = FunctionDetail(widget_id=-1, importance=1,
                                                                    state=widgets_dict[id]['state'])

                    widget_ids = unique_widgets[widgets_dict[id]['widget'].to_html(id=0)]
                    for widget_id in widget_ids:
                        # set function to widget
                        widget = widgets_dict[widget_id]['widget']
                        widget.set_function(function)
                        # mark this function as done, if the corresponding event has been executed
                        for event in widgets_dict[widget_id]['state'].find_events_by_widget(widget):
                            self.on_action_executed(event)
                        self.logger.info(f"[Reanalysis] Successfully set function({function}) to {widget.to_html()}")
            except Exception as e:
                self.logger.error(e)
            self.__need_reanalysed = False

    def add_state(self, state: 'DeviceState'):
        """
        call from main thread
        """
        # 相似页面加入 cluster 后，如果 cluster 已被 LLM 分析过，则标记需要后续重分析。
        with self.__lock:
            if state not in self.__states:
                self.__states.add(state)
                # For the state added later (after the current cluster has been analyzed by llm)
                if self.__analysed:
                    self.__need_reanalysed = True
                    self.__update_later_joined_state(state)

    def get_id(self) -> int:
        return self.__id

    def get_states(self) -> set['DeviceState']:
        return self.__states

    def need_reanalysed(self) -> bool:
        # add lock
        with self.__lock:
            return self.__need_reanalysed

    def to_description(self) -> str:
        """
        call from child thread
        Activity + HTML + \\n
        """
        # 提供给 LLM 的 cluster 描述：Activity 名 + root state 的 HTML 页面描述。
        desc = f"[Activity: {self.__root_state.foreground_activity}]\n"
        # Lock in to html to ensure thread safety
        desc += self.__root_state.to_html()
        return desc

    def has_untested_function(self) -> bool:
        """
        call from child thread
        """
        with self.__lock:
            for function in self.__functions.keys():
                if self.__functions[function]['importance'] > 0:
                    return True
            return False

    def write_overview_top5_tojson(self, top5, ignore_importance: bool = False):
        """
        call from child thread
        Write its own overview and top 5 important functions
        """
        # Guidance prompt 只带每个高价值 cluster 的少量重要功能，控制上下文长度。
        with self.__lock:
            key = f"State{self.__id}"
            # Sort and eliminate functions with importance 0 (already executed)
            sorted_functions = self.__sort_functions_by_value()
            final_functions = []
            for func in sorted_functions[:5]:
                if self.__functions[func]['importance'] > 0 or ignore_importance:
                    final_functions.append(func)

            top5[key] = TopCluster(Overview=self.__overview, FunctionList=final_functions)

    def __sort_functions_by_value(self) -> list[str]:
        """
        call from child thread
        """
        sorted_keys = [key for key, detail in sorted(self.__functions.items(),
                                                     key=lambda item: item[1]['importance'], reverse=True)]
        return sorted_keys

    def get_target_state(self, function: str) -> Optional['DeviceState']:
        # LLM 选择 function 后，通过这里找到最适合导航过去测试的具体 DeviceState。
        if function in self.__functions:
            state = self.__functions[function]['state']
            return state
        else:
            self.logger.warning(f"function{function} doesn't belong to any state in Cluster{self.__id}")
            return None

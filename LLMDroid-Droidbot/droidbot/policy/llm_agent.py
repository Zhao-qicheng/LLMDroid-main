# 文件作用：
# 1. 封装 LLMDroid 与大语言模型的交互，负责构造 prompt、调用模型并解析 JSON 响应。
# 2. 异步处理页面摘要、目标功能选择、目标页动作选择和页面簇重分析四类任务。
# 3. 将模型输出转成 StateCluster/UTG 可使用的结构化目标或 DroidBot 可执行的 InputEvent。
import os.path
from enum import Enum
import threading
import json
import re
from concurrent.futures import Future
import time
from queue import Queue, Empty
from typing import Any, Callable, Optional, TYPE_CHECKING, TypedDict
from openai import OpenAI

from ..desc.action_type import ActionType
from ..utils import save_content_to_file
from .prompt import *
from ..input_event import SetTextEvent

if TYPE_CHECKING:
    from ..desc.state_cluster import StateCluster
    from ..desc.device_state import DeviceState
    from ..app import App
    from ..desc.utg import UTG
    from ..desc.widget import Widget

from ..global_log import get_logger


class QuestionMode(Enum):
    # LLMAgent 支持的提问类型：页面摘要、目标选择、目标功能执行、补充重分析。
    OVERVIEW = 0
    GUIDE = 1
    TEST_FUNCTION = 2
    EXPLORE = 3
    REANALYSIS = 4


class QuestionPayload:
    # 主线程向 LLMAgent 子线程投递任务时使用的轻量载体。
    def __init__(self, mode, cluster: Optional['StateCluster'] = None,
                 state: Optional['DeviceState'] = None,
                 first_func_execution: bool = True):
        self.mode: QuestionMode = mode
        self.cluster: Optional['StateCluster'] = cluster
        self.state: Optional['DeviceState'] = state
        self.first_func_execution: bool = first_func_execution


class TopCluster(TypedDict):
    Overview: str
    FunctionList: list[str]


class WidgetInfo(TypedDict):
    function: str
    state: 'DeviceState'
    importance: int
    widget: 'Widget'


ValidationResult = tuple[bool, str]


def _config_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def extract_json_object(response: str) -> tuple[Optional[dict], str]:
    if not isinstance(response, str) or not response.strip():
        return None, "response is empty"

    response = response.strip()
    pos = response.find('{')
    if pos != -1:
        response = response[pos:]
    pos = response.rfind('}')
    if pos != -1:
        response = response[:pos + 1]
    try:
        parsed = json.loads(response)
    except Exception as e:
        return None, f"response is not valid JSON: {e}"
    if not isinstance(parsed, dict):
        return None, "top-level JSON value must be an object"
    return parsed, ""


def validate_overview_response(response: Any) -> ValidationResult:
    if not isinstance(response, dict):
        return False, "response must be a JSON object"
    overview = response.get("Overview")
    if not isinstance(overview, str):
        return False, '"Overview" must be a string'
    function_list = response.get("Function List")
    if not isinstance(function_list, dict):
        return False, '"Function List" must be an object'
    for function, element_id in function_list.items():
        if not isinstance(function, str):
            return False, '"Function List" keys must be strings'
        if type(element_id) is not int:
            return False, f'"Function List" value for {function!r} must be an integer element id'
    top5 = response.get("Top5", response.get("Top 5"))
    if top5 is not None:
        if not isinstance(top5, list):
            return False, '"Top5" must be an array when present'
        for elem in top5:
            if not isinstance(elem, (int, str)):
                return False, '"Top5" entries must be integers or State strings'
    return True, ""


def validate_guidance_response(response: Any, valid_targets: dict[str, set[str]]) -> ValidationResult:
    if not isinstance(response, dict):
        return False, "response must be a JSON object"
    target_state = response.get("Target State")
    target_function = response.get("Target Function")
    if not isinstance(target_state, str) or not re.fullmatch(r"State\d+", target_state):
        return False, '"Target State" must be a string like "State2"'
    if not isinstance(target_function, str):
        return False, '"Target Function" must be a string'
    if target_state not in valid_targets:
        return False, f'"Target State" {target_state!r} is not in the provided State Information'
    if target_function not in valid_targets[target_state]:
        return False, (
            f'"Target Function" {target_function!r} must be copied exactly from '
            f'{target_state}.FunctionList'
        )
    return True, ""


def validate_test_function_response(response: Any, valid_actions: set[tuple[int, int]]) -> ValidationResult:
    if not isinstance(response, dict):
        return False, "response must be a JSON object"
    element_id = response.get("Element Id")
    action_type = response.get("Action Type")
    if type(element_id) is not int:
        return False, '"Element Id" must be an integer'
    if type(action_type) is not int:
        return False, '"Action Type" must be an integer'
    if not 0 <= action_type <= 6:
        return False, '"Action Type" must be an integer from 0 to 6'
    if element_id == -1:
        if action_type != 0:
            return False, 'when "Element Id" is -1, "Action Type" must be 0'
        return True, ""
    if (element_id, action_type) not in valid_actions:
        return False, f"({element_id}, {action_type}) is not one of the provided candidate actions"
    if action_type == 6:
        input_text = response.get("Input")
        if not isinstance(input_text, str) or not input_text.strip():
            return False, '"Input" must be a non-empty string when "Action Type" is 6'
    return True, ""


def validate_reanalysis_response(response: Any, valid_ids: set[str]) -> ValidationResult:
    if not isinstance(response, dict):
        return False, "response must be a JSON object"
    for control_id, function in response.items():
        if not isinstance(control_id, str) or not re.fullmatch(r"\d+", control_id):
            return False, "all keys must be string representations of integer control ids"
        if control_id not in valid_ids:
            return False, f"control id {control_id!r} is not present in the provided controls"
        if not isinstance(function, str):
            return False, f"function for control id {control_id!r} must be a string"
    return True, ""


class LLMAgent:
    """
    中文说明：LLMAgent 是 LLMDroid 与大模型之间的桥。
    它负责把页面/cluster/历史动作组织成 prompt，并把模型 JSON 响应转成可执行目标或事件。
    为了不阻塞自主探索，耗时的 LLM 请求放在子线程中异步处理。
    """

    MODEL_STR = 'gpt-4o'
    BASE_URL = 'https://api.openai.com/v1'

    def __init__(self, app: 'App', utg: 'UTG'):
        self.logger = get_logger()
        self.__app: 'App' = app
        self.__utg: 'UTG' = utg
        self.__QA_file = os.path.join(self.__app.output_dir, 'LLM_QA.txt')
        # LLM_QA.txt 保存完整 prompt/response，是调试模型理解和格式错误的首要入口。
        with open(self.__QA_file, 'w', encoding='utf-8') as file:
            file.write(f"package: {self.__app.package_name}\n")
            file.write('=' * 20 + '\n')
        self.__start_prompt = ''
        # read from config file
        # config.json 同时提供 App 语义描述和 OpenAI-compatible 模型调用配置。
        with open('./config.json', mode='r', encoding='utf-8') as file:
            config = json.load(file)
            log_config = dict(config)
            if log_config.get('ApiKey'):
                log_config['ApiKey'] = '***'
            self.logger.info(f"config.json:\n{json.dumps(log_config, indent=4)}\n")
            self.__app_name = config['AppName']
            self.__app_desc = config['Description']
            self.__api_key = (
                config.get('ApiKey')
                or os.getenv('DASHSCOPE_API_KEY')
                or os.getenv('BAILIAN_API_KEY')
                or os.getenv('GLM_API_KEY')
                or os.getenv('ZHIPUAI_API_KEY')
            )
            if not self.__api_key:
                raise ValueError(
                    "ApiKey is empty. Set it in config.json or define "
                    "DASHSCOPE_API_KEY/BAILIAN_API_KEY/GLM_API_KEY/ZHIPUAI_API_KEY."
                )
            if 'Model' in config:
                LLMAgent.MODEL_STR = config['Model']
        if 'BaseUrl' in config:
            LLMAgent.BASE_URL = config['BaseUrl']
        self.__start_prompt = f"I'm now testing an app called {self.__app_name} on Android.\n{self.__app_desc}\n"
        llm_config = config.get('LLMAgent', {})
        self.__overview_workers = max(1, int(llm_config.get('OverviewWorkers', 2)))
        self.__reanalysis_workers = max(1, int(llm_config.get('ReanalysisWorkers', 1)))
        self.__guidance_wait_timeout = max(0, int(llm_config.get('GuidanceWaitTimeout', 45)))
        self.__request_timeout = max(1, int(llm_config.get('RequestTimeout', 120)))
        self.__max_repair_retries = max(0, int(llm_config.get('MaxRepairRetries', 2)))
        self.__use_response_format = _config_bool(llm_config.get('UseResponseFormat'), True)
        self.__response_format_supported = self.__use_response_format
        # init client
        # 使用 OpenAI SDK 的兼容接口，因此 BaseUrl 可以指向第三方 OpenAI-compatible 服务。
        self.__client = OpenAI(api_key=self.__api_key, base_url=LLMAgent.BASE_URL, timeout=self.__request_timeout)
        self.__file_lock = threading.Lock()

        # overview
        # top_valued_cluster 是 LLM 维护的高价值页面簇列表，Guidance 会优先从这里选目标。
        self.__top_valued_cluster: list['StateCluster'] = []
        self.__top_valued_cluster_lock = threading.Lock()
        self.__p2: int = 10

        self.__future: Future = None
        self.__future_lock = threading.Lock()

        self.__tested_functions: set[tuple[int, str]] = set()
        self.__tested_functions_lock = threading.Lock()
        self.__target_id: int = -1
        self.__target_func: str = ''
        self.__executed_events: list[str] = []
        self.__executed_events_lock = threading.Lock()

        #
        # Guidance/test function 会直接决定当前动作，保持单 worker 串行执行。
        # Overview/reanalysis 只写入页面簇语义，彼此独立，使用多个后台 worker 提高吞吐。
        self.__sync_queue = Queue()
        self.__overview_queue = Queue()
        self.__reanalysis_queue = Queue()
        self.__sync_question_remained: int = 0
        self.__overview_question_remained: int = 0
        self.__reanalysis_question_remained: int = 0
        self.__high_question_remained: int = 0
        self.__low_question_remained: int = 0
        self.__question_count_lock = threading.Lock()

        self.__work_thread = threading.Thread(
            target=self.__work_loop,
            args=(self.__sync_queue, "sync", {QuestionMode.GUIDE, QuestionMode.TEST_FUNCTION}),
        )
        self.__work_thread.setDaemon(True)
        self.__work_thread.start()
        self.__overview_threads = []
        for i in range(self.__overview_workers):
            thread = threading.Thread(
                target=self.__work_loop,
                args=(self.__overview_queue, f"overview-{i + 1}", {QuestionMode.OVERVIEW}),
            )
            thread.setDaemon(True)
            thread.start()
            self.__overview_threads.append(thread)

        self.__reanalysis_threads = []
        for i in range(self.__reanalysis_workers):
            thread = threading.Thread(
                target=self.__work_loop,
                args=(self.__reanalysis_queue, f"reanalysis-{i + 1}", {QuestionMode.REANALYSIS}),
            )
            thread.setDaemon(True)
            thread.start()
            self.__reanalysis_threads.append(thread)

        self.logger.info(
            "Start LLM worker threads: "
            f"sync=1, overview={self.__overview_workers}, reanalysis={self.__reanalysis_workers}, "
            f"guidance_wait_timeout={self.__guidance_wait_timeout}s"
        )

    def is_child_thread_alive(self) -> bool:
        return (
            self.__work_thread.is_alive()
            and any(thread.is_alive() for thread in self.__overview_threads)
            and any(thread.is_alive() for thread in self.__reanalysis_threads)
        )

    def push_to_queue(self, payload: QuestionPayload):
        """
        call from main thread
        """

        if payload.mode == QuestionMode.OVERVIEW:
            with self.__question_count_lock:
                self.__overview_question_remained += 1
                self.__high_question_remained += 1
            self.__overview_queue.put(payload)
            self.logger.info(
                f"Push overview question, queue: {self.__overview_queue.qsize()}, "
                f"overview_pending: {self.__overview_question_remained}, "
                f"high_pending: {self.__high_question_remained}"
            )
        elif payload.mode == QuestionMode.REANALYSIS:
            # reanalysis 只补充已有 cluster 的功能信息，且仅对高价值 cluster 做，降低 LLM 成本。
            self.__refresh_top_valued_clusters()
            with self.__top_valued_cluster_lock:
                should_reanalyse = payload.cluster in self.__top_valued_cluster[:self.__p2]
            if should_reanalyse:
                with self.__question_count_lock:
                    self.__reanalysis_question_remained += 1
                    self.__low_question_remained += 1
                self.__reanalysis_queue.put(payload)
                self.logger.info(
                    f"Push reanalysis question, queue: {self.__reanalysis_queue.qsize()}, "
                    f"reanalysis_pending: {self.__reanalysis_question_remained}, "
                    f"low_pending: {self.__low_question_remained}"
                )
        else:
            # GUIDE/TEST_FUNCTION 会影响当前阶段推进，进入同步队列并由主线程等待结果。
            with self.__question_count_lock:
                self.__sync_question_remained += 1
                self.__high_question_remained += 1
            self.__sync_queue.put(payload)
            self.logger.info(
                f"Push sync question, queue: {self.__sync_queue.qsize()}, "
                f"sync_pending: {self.__sync_question_remained}, "
                f"high_pending: {self.__high_question_remained}"
            )

    def __work_loop(self, queue: Queue, worker_name: str, allowed_modes: set[QuestionMode]):
        # 子线程循环消费 LLM 任务。不同队列的任务互不等待，避免 overview/reanalysis 阻塞 Guidance。
        while True:
            payload = None
            try:
                try:
                    payload = queue.get(timeout=1)
                    self.logger.info(f"Consumed from {worker_name} queue")
                except Empty:
                    continue

                try:
                    if payload.mode not in allowed_modes:
                        self.logger.warning(f"Skip unexpected {payload.mode} in {worker_name} queue")
                        continue
                    # 不同 mode 对应不同 prompt 模板和响应处理逻辑。
                    if payload.mode == QuestionMode.OVERVIEW:
                        self.__ask_for_overview(payload)
                    elif payload.mode == QuestionMode.GUIDE:
                        self.__ask_for_guidance(payload)
                    elif payload.mode == QuestionMode.TEST_FUNCTION:
                        self.__ask_for_test_function(payload)
                    elif payload.mode == QuestionMode.REANALYSIS:
                        self.__ask_for_reanalysis(payload)
                finally:
                    self.__mark_payload_done(payload)
            except Exception as e:
                self.logger.error(f"LLM worker({worker_name}) error: {e}")
                import traceback
                traceback.print_exc()
                if payload is not None:
                    if payload.mode == QuestionMode.GUIDE:
                        self.__set_future_result((-1, ""))
                    elif payload.mode == QuestionMode.TEST_FUNCTION:
                        self.__set_future_result(None)

    def __mark_payload_done(self, payload: QuestionPayload):
        with self.__question_count_lock:
            if payload.mode == QuestionMode.OVERVIEW:
                self.__overview_question_remained = max(0, self.__overview_question_remained - 1)
                self.__high_question_remained = max(0, self.__high_question_remained - 1)
            elif payload.mode == QuestionMode.REANALYSIS:
                self.__reanalysis_question_remained = max(0, self.__reanalysis_question_remained - 1)
                self.__low_question_remained = max(0, self.__low_question_remained - 1)
            else:
                self.__sync_question_remained = max(0, self.__sync_question_remained - 1)
                self.__high_question_remained = max(0, self.__high_question_remained - 1)

    def wait_until_queue_empty(self, timeout: Optional[int] = None) -> bool:
        # 进入 Guidance 前只等待 overview 完成；超时后用已完成摘要先推进，剩余任务继续后台处理。
        timeout = self.__guidance_wait_timeout if timeout is None else timeout
        begin_stamp = time.time()
        self.logger.info(f"Wait until overview queue is empty, timeout: {timeout}s...")
        while True:
            with self.__question_count_lock:
                overview_remained = self.__overview_question_remained
            if overview_remained == 0:
                self.logger.info(f"overview questions all done")
                return True
            if timeout > 0 and time.time() - begin_stamp >= timeout:
                self.logger.warning(
                    f"Wait overview timeout after {timeout}s, "
                    f"overview questions remain: {overview_remained}"
                )
                return False
            self.logger.info(f"Overview questions remain: {overview_remained}")
            time.sleep(3)

    def has_ready_overview(self) -> bool:
        with self.__top_valued_cluster_lock:
            return len(self.__top_valued_cluster) > 0

    def __refresh_top_valued_clusters(self):
        scored_clusters = [
            cluster for cluster in self.__utg.clusters
            if cluster and cluster.has_untested_function()
        ]
        if not scored_clusters:
            scored_clusters = [cluster for cluster in self.__utg.clusters if cluster]
        scored_clusters.sort(key=lambda cluster: cluster.get_guidance_score(), reverse=True)
        with self.__top_valued_cluster_lock:
            self.__top_valued_cluster = scored_clusters

    def __ask_for_overview(self, payload: QuestionPayload):
        # OVERVIEW：让 LLM 阅读一个新页面簇的 HTML 描述，产出页面概览和可测试功能列表。
        if payload.cluster is None:
            self.logger.warning("Payload's state is None, skip")
            return

        self.logger.info(f"Ask for StateCluster's overview")
        # time.sleep(3)
        # self.logger.debug("debug: Ask for StateCluster's overview, over")
        # return
        prompt = self.__start_prompt + function_explanation + input_explanation_overview
        prompt += "\n```HTML Description\n"
        prompt += payload.cluster.to_description()[:7000] + "\n"
        prompt += "```\n"

        prompt += required_output_overview2 + required_output_overview_summary2 + answer_format_overview2

        json_resp = self.__get_structured_response(
            prompt=prompt,
            validator=validate_overview_response,
            mode=QuestionMode.OVERVIEW,
        )
        if json_resp is None:
            self.logger.warning(f"Skip overview update for Cluster{payload.cluster.get_id()} because LLM failed")
            return

        # process response
        # 将模型返回的 overview/function list 写回 StateCluster，后续目标选择会读取这些结构化信息。
        payload.cluster.update_from_overview(json_resp)
        self.__refresh_top_valued_clusters()

    def __ask_for_guidance(self, payload: QuestionPayload):
        # GUIDE：当覆盖率/时间触发停滞时，让 LLM 在高价值 cluster 中选择下一轮目标功能。
        self.logger.info("Ask for guidance")
        prompt = self.__start_prompt + input_explanation_guidance

        cluster_info = {}
        self.__refresh_top_valued_clusters()
        with self.__top_valued_cluster_lock:
            top_snapshot = list(self.__top_valued_cluster[:self.__p2])
        for cluster in top_snapshot:
            if cluster.has_untested_function():
                cluster.write_overview_top5_tojson(cluster_info)
        # if all clusters' functions are tested, just write five functions for each cluster
        if len(cluster_info) == 0:
            self.logger.warning("[Ask for guidance] all clusters' functions are tested")
            for cluster in top_snapshot:
                cluster.write_overview_top5_tojson(cluster_info, ignore_importance=True)
        if len(cluster_info) == 0:
            self.logger.warning("[Ask for guidance] no available cluster information")
            self.__set_future_result((-1, ""))
            return
        prompt += f"\n```State Information\n{json.dumps(cluster_info, ensure_ascii=False, indent=4)}\n```\n"

        # tested functions
        tested_by_state: dict[str, list[str]] = {}
        with self.__tested_functions_lock:
            tested_functions = set(self.__tested_functions)
        for cluster_id, func in tested_functions:
            tested_by_state.setdefault(f"State{cluster_id}", []).append(func)
        prompt += required_output_guidance1
        prompt += json.dumps(tested_by_state, ensure_ascii=False, indent=4)
        prompt += required_output_guidance2
        prompt += answer_format_guidance

        valid_targets = {
            state_name: set(info.get("FunctionList", []))
            for state_name, info in cluster_info.items()
        }
        json_resp = self.__get_structured_response(
            prompt=prompt,
            validator=lambda response: validate_guidance_response(response, valid_targets),
            mode=QuestionMode.GUIDE,
            repair_context=f"Valid targets are: {json.dumps(cluster_info, ensure_ascii=False)}",
        )
        if json_resp is None:
            self.__set_future_result((-1, ""))
            return
        self.__target_id = int(json_resp['Target State'][5:])
        self.__target_func = json_resp['Target Function']

        # LLM 只选择语义目标；真正的路径规划仍在本地 UTG 中完成，避免逐步依赖模型。
        self.logger.info(f"Try to find path from Cluster{self.__utg.current_cluster.get_id()} to Cluster{self.__target_id}")
        # find cluster by id
        target_cluster: Optional['StateCluster'] = self.__utg.find_cluster_by_id(self.__target_id)
        if target_cluster is None:
            self.__set_future_result((-1, self.__target_func))
        else:
            # int, str
            target_state = target_cluster.get_target_state(self.__target_func)
            self.__set_future_result((target_state.get_id() if target_state else -1, self.__target_func))

    def __ask_for_test_function(self, payload: QuestionPayload):
        # TEST_FUNCTION：到达目标页后，让 LLM 基于当前页面 HTML 选择具体控件和动作类型。
        self.logger.info("Ask for testing function")

        prompt = self.__start_prompt + input_explanation_test
        html = payload.state.to_html()
        candidates = payload.state.to_llm_action_candidates()
        valid_actions = {
            (candidate["element_id"], candidate["action_type"])
            for candidate in candidates
        }
        candidate_html = {
            (candidate["element_id"], candidate["action_type"]): candidate["widget_html"]
            for candidate in candidates
        }
        if not candidates:
            self.logger.warning("Current page has no LLM action candidates")
            self.__set_future_result(None)
            return
        prompt += f"\n```Page Description\n{html}```\n"
        prompt += "\n```Candidate Actions\n"
        prompt += json.dumps(candidates, ensure_ascii=False, indent=4)
        prompt += "\n```\n"

        # function to test
        prompt += f"The target function I want to test is: {self.__target_func}\n"

        # provide executed events
        with self.__executed_events_lock:
            executed_events = list(self.__executed_events)
        if executed_events:
            joined = ',\n'.join(executed_events)
            prompt += f"\nI have already executed: [{joined}]\n"

        # Ask which widget to click
        prompt += f"{required_output_test}\n{answer_format_test}\n"
        if executed_events:
            prompt += answer_format_test_empty

        json_resp = self.__get_structured_response(
            prompt=prompt,
            validator=lambda response: validate_test_function_response(response, valid_actions),
            mode=QuestionMode.TEST_FUNCTION,
            repair_context=f"Valid candidate actions are: {json.dumps(candidates, ensure_ascii=False)}",
        )
        if json_resp is None:
            self.__set_future_result(None)
            return

        widget_id = self.__parse_int_field(json_resp, 'Element Id')
        action_offset = self.__parse_int_field(json_resp, 'Action Type')
        if widget_id is None or action_offset is None:
            self.__set_future_result(None)
            return

        try:
            act_type = ActionType.get_type_by_value(action_offset + ActionType.CLICK.value)
        except ValueError:
            self.logger.warning(f"Invalid LLM Action Type: {action_offset!r}. Full response: {json_resp}")
            self.__set_future_result(None)
            return

        if widget_id == -1:
            self.__set_future_result(None)
            return

        ret = payload.state.find_event_by_llm_action(widget_id, action_offset)
        if ret is None:
            ret = payload.state.find_event_by_id_and_type(widget_id, act_type)
        if ret:
            # set text to InputEvent
            # 如果模型返回 Input 字段，只在 SetTextEvent 上写入真实输入文本。
            if 'Input' in json_resp:
                input_text = json_resp['Input']
                if isinstance(ret, SetTextEvent):
                    ret.text = input_text
                else:
                    self.logger.warning(f"Can't set text to event:{ret.to_description()}")
            # extract corresponding line in html
            # 记录已执行动作的 HTML 行，下一轮 prompt 会告知模型避免重复操作。
            executed_html = candidate_html.get((widget_id, action_offset), "")
            s = ret.to_description(html=executed_html)
            self.logger.debug(s)
            with self.__executed_events_lock:
                self.__executed_events.append(s)
        # None type will be handled by utg_based_policy
        self.__set_future_result(ret)

    def __ask_for_reanalysis(self, payload: QuestionPayload):
        # REANALYSIS：当一个 cluster 后续加入了差异页面，重新让 LLM 识别新增控件对应的功能。
        self.logger.info(f"Ask for Reanalysis of Cluster{payload.cluster.get_id()}")

        prompt: str = self.__start_prompt + input_explanation_reanalysis1
        prompt += "```Overview and Function List\n"
        prompt += json.dumps(payload.cluster.to_json(reanalysis=True), ensure_ascii=False, indent=4)
        prompt += "\n```\n"

        prompt += input_explanation_reanalysis2
        prompt += "```Controls in HTML Description\n"

        # get different widgets
        # 只把与 root state 不同的控件提供给模型，控制 prompt 长度和调用成本。
        widgets_dict: dict[int, WidgetInfo] = {}
        id = 1
        root_state = payload.cluster.get_root_state()
        for state in payload.cluster.get_states():
            # allocate different id for every widget
            for widget in state.diff_widgets(root_state):
                widgets_dict[id] = WidgetInfo(function='', state=state, importance=-1, widget=widget)
                id += 1

        if len(widgets_dict) == 0:
            self.logger.warning(f"All states are exactly the same sa root state, no different widgets to analysis")
            return

        # remove duplicate ones
        unique_widgets: dict[str, list[int]] = {}
        for id in widgets_dict.keys():
            html = widgets_dict[id]['widget'].to_html(id=0)
            if html not in unique_widgets:
                unique_widgets[html] = [id]
            else:
                unique_widgets[html].append(id)

        # generate widget list in html
        for ws in unique_widgets.values():
            widget_id = ws[0]
            prompt += widgets_dict[widget_id]['widget'].to_html(id=widget_id)

        prompt += "```\n"
        # required output and answer format
        prompt += required_output_reanalysis + answer_format_reanalysis
        # rank clusters and functions

        valid_ids = {str(widget_ids[0]) for widget_ids in unique_widgets.values()}
        json_resp = self.__get_structured_response(
            prompt=prompt,
            validator=lambda response: validate_reanalysis_response(response, valid_ids),
            mode=QuestionMode.REANALYSIS,
            repair_context=f"Valid control ids are: {sorted(valid_ids)}",
        )
        if json_resp is None:
            self.logger.warning(f"Skip reanalysis update for Cluster{payload.cluster.get_id()} because LLM failed")
            return

        # process response
        # 根据模型结果更新功能列表，并把新功能绑定回对应 widget/action listener。
        # update function list, record corresponding state, set function to widget
        # no need to set listener to action,
        # because listener has already been set when other states joined to this cluster
        payload.cluster.update_from_reanalysis(json_resp, unique_widgets, widgets_dict)
        # TODO update top clusters

    def __create_chat_completion(self, messages: list[dict], use_response_format: bool):
        request_kwargs = {
            "temperature": 0,
            "messages": messages,
            "model": LLMAgent.MODEL_STR,
        }
        if use_response_format:
            request_kwargs["response_format"] = {"type": "json_object"}
        try:
            return self.__client.chat.completions.create(**request_kwargs)
        except Exception as e:
            if use_response_format:
                self.__response_format_supported = False
                self.logger.warning(
                    f"response_format is not supported or failed ({e}); fallback to plain chat completion"
                )
                return self.__client.chat.completions.create(
                    temperature=0,
                    messages=messages,
                    model=LLMAgent.MODEL_STR,
                )
            raise

    def __log_llm_validation_error(self, mode: QuestionMode, attempt: int, validation_error: str,
                                   raw_response_length: int):
        content = json.dumps({
            "mode": mode.name,
            "attempt": attempt,
            "validation_error": validation_error,
            "raw_response_length": raw_response_length,
        }, ensure_ascii=False, indent=4)
        with self.__file_lock:
            save_content_to_file(self.__QA_file, title='Validation Error', content=content)

    def __get_structured_response(self, prompt: str, validator: Callable[[dict], ValidationResult],
                                  mode: QuestionMode, repair_context: Optional[str] = None) -> Optional[dict]:
        # 统一的大模型调用入口：保存 prompt、重试请求、记录耗时/响应长度、解析和校验 JSON。
        with self.__file_lock:
            save_content_to_file(self.__QA_file, title='Prompt', content=prompt)
        messages = [{"role": "user", "content": prompt}]
        request_attempt = 0
        validation_error = ""
        max_total_attempts = max(1, 1 + self.__max_repair_retries)

        while request_attempt < max_total_attempts:
            request_attempt += 1
            begin_stamp = time.time()
            chat_completion = None
            try_times = 0
            while try_times < 5:
                try:
                    chat_completion = self.__create_chat_completion(
                        messages=messages,
                        use_response_format=self.__response_format_supported,
                    )
                    if chat_completion:
                        break
                except Exception as e:
                    self.logger.warning(f"Exception:{e}, try to ask again in 3 seconds")
                    time.sleep(3)
                    try_times += 1

            if chat_completion is None:
                validation_error = "LLM request failed after 5 retries"
                self.logger.error(validation_error)
                self.__log_llm_validation_error(mode, request_attempt, validation_error, 0)
                return None

            response = chat_completion.choices[0].message.content or ""
            end_stamp = time.time()
            with self.__file_lock:
                with open(os.path.join(self.__app.output_dir, 'LLM-Interaction.txt'), 'a') as file:
                    time_difference = round(end_stamp - begin_stamp, 5)
                    file.write(f"{time_difference}, {len(response)}\n")
            self.logger.info(f"Get response:\n{response}")
            with self.__file_lock:
                save_content_to_file(self.__QA_file, title='Response', content=response)

            json_resp, parse_error = extract_json_object(response)
            if json_resp is None:
                validation_error = parse_error
            else:
                valid, validation_error = validator(json_resp)
                if valid:
                    return json_resp

            self.logger.warning(
                f"Invalid LLM response for {mode.name}, attempt {request_attempt}/{max_total_attempts}: "
                f"{validation_error}"
            )
            self.__log_llm_validation_error(mode, request_attempt, validation_error, len(response))
            if request_attempt >= max_total_attempts:
                break

            repair_prompt = (
                "Your previous response was invalid.\n"
                f"Validation error: {validation_error}\n"
                "Return only a corrected JSON object that satisfies the original task and schema."
            )
            if repair_context:
                repair_prompt += f"\n{repair_context}"
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
                {"role": "user", "content": repair_prompt},
            ]

        self.logger.error(f"LLM failed to produce valid {mode.name} response: {validation_error}")
        return None

    def set_future(self, future):
        # UtgBasedInputPolicy 每次同步等待 LLM 结果前都会重置 Future。
        with self.__future_lock:
            self.__future = future

    def __set_future_result(self, result):
        with self.__future_lock:
            future = self.__future
        if future and not future.done():
            future.set_result(result)
        else:
            self.logger.warning("Future is missing or already done, skip setting LLM result")

    def __parse_int_field(self, json_resp: dict, key: str) -> Optional[int]:
        value = json_resp.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            value = value.strip()
            if re.fullmatch(r'-?\d+', value):
                return int(value)
        self.logger.warning(f"Invalid LLM response field {key}: {value!r}. Full response: {json_resp}")
        return None

    def add_tested_function(self):
        """
        Add target function to tested functions in agent,
        also mark the function in the corresponding cluster as tested
        """
        # 不论目标是否完全成功，结束一轮 Guidance 后都标记为已尝试，避免反复卡在同一功能。
        if self.__target_id < 0 or not self.__target_func:
            self.logger.warning("Skip marking tested function because target is empty")
            return
        with self.__tested_functions_lock:
            self.__tested_functions.add((self.__target_id, self.__target_func))
        cluster = self.__utg.find_cluster_by_id(self.__target_id)
        if cluster:
            cluster.update_tested_function(self.__target_func)
        else:
            self.logger.warning(f"Can't find Cluster{self.__target_id} when marking function({self.__target_func}) as tested")

    def record_target_navigation_failure(self):
        cluster = self.__utg.find_cluster_by_id(self.__target_id)
        if cluster:
            cluster.record_navigation_failure()

    def clear_executed_events(self):
        # 一轮目标功能测试结束后清空动作历史，避免影响下一轮目标的 prompt。
        with self.__executed_events_lock:
            self.__executed_events.clear()

# 文件作用：
# 1. 作为 DroidBot/LLMDroid 的事件调度器，根据 policy_name 创建具体输入策略。
# 2. 统一管理事件发送、事件间隔、事件日志、method profiling 和 Monkey/manual/replay 分支。
# 3. 在 LLMDroid-Droidbot 中，它负责把策略层生成的 InputEvent 包装为 EventLog 并下发到设备。
import subprocess
import time
from typing import Literal

from .input_event import EventLog
from .policy.input_policy import *
from .policy.manual_policy import ManualPolicy
from .policy.utg_based_policy import UtgBasedInputPolicy
from .policy.utg_greedy_search_policy import UtgGreedySearchPolicy
from .policy.utg_naive_search_policy import UtgNaiveSearchPolicy
from .policy.utg_replay_policy import UtgReplayPolicy

# UtgGreedySearchPolicy, \
#                          UtgReplayPolicy, \
#                          ManualPolicy

DEFAULT_POLICY = POLICY_GREEDY_DFS
DEFAULT_EVENT_INTERVAL = 1
DEFAULT_EVENT_COUNT = 100000000
DEFAULT_TIMEOUT = -1


class UnknownInputException(Exception):
    pass


class InputManager(object):
    """
    This class manages all events to send during app running

    中文说明：InputManager 是“事件调度层”。它不直接决定点哪个控件，
    而是根据 policy_name 创建具体策略，再把策略生成的事件包装成 EventLog 后发送到设备。
    """

    def __init__(self, device, app, policy_name, random_input,
                 event_count, event_interval,
                 code_coverage: Literal['time', 'androlog', 'jacoco'],
                 script_path=None, profiling_method=None, master=None,
                 replay_output=None,
                 external_driver=False
                 ):
        """
        manage input event sent to the target device
        :param device: instance of Device
        :param app: instance of App
        :param policy_name: policy of generating events, string
        :return:
        """
        self.logger = logging.getLogger('InputEventManager')
        self.enabled = True

        self.device = device
        self.app = app
        self.policy_name = policy_name
        self.random_input = random_input
        self.events = []
        self.policy = None
        self.script = None
        self.event_count = event_count
        self.event_interval = event_interval
        self.replay_output = replay_output
        self.external_driver = external_driver

        self.monkey = None

        if script_path is not None:
            # script 用于在特定页面强制执行预定义动作，优先级高于普通探索策略。
            f = open(script_path, 'r')
            script_dict = json.load(f)
            from .input_script import DroidBotScript
            self.script = DroidBotScript(script_dict)

        self.policy = self.get_input_policy(device, app, master, code_coverage)
        self.profiling_method = profiling_method

    def get_input_policy(self, device, app, master, code_coverage):
        # policy_name 决定真正的事件生成器。LLMDroid 的核心逻辑挂在 UTG-based 策略上，
        # 即 naive/greedy/manual 等继承或复用 UtgBasedInputPolicy 的策略。
        if self.policy_name == POLICY_NONE:
            input_policy = None
        elif self.policy_name == POLICY_MONKEY:
            input_policy = None
        elif self.policy_name in [POLICY_NAIVE_DFS, POLICY_NAIVE_BFS]:
            input_policy = UtgNaiveSearchPolicy(device, app, self.random_input, self.policy_name, code_coverage,
                                                external_driver=self.external_driver)
        elif self.policy_name in [POLICY_GREEDY_DFS, POLICY_GREEDY_BFS]:
            input_policy = UtgGreedySearchPolicy(device, app, self.random_input, self.policy_name, code_coverage,
                                                 external_driver=self.external_driver)
        elif self.policy_name == POLICY_MEMORY_GUIDED:
            from .input_policy2 import MemoryGuidedPolicy
            input_policy = MemoryGuidedPolicy(device, app, self.random_input, code_coverage,
                                              external_driver=self.external_driver)
        elif self.policy_name == POLICY_LLM_GUIDED:
            from .input_policy3 import LLM_Guided_Policy
            input_policy = LLM_Guided_Policy(device, app, self.random_input)
        elif self.policy_name == POLICY_REPLAY:
            input_policy = UtgReplayPolicy(device, app, self.replay_output)
        elif self.policy_name == POLICY_MANUAL:
            input_policy = ManualPolicy(device, app, code_coverage, external_driver=self.external_driver)
        else:
            self.logger.warning("No valid input policy specified. Using policy \"none\".")
            input_policy = None
        if isinstance(input_policy, UtgBasedInputPolicy):
            # UTG-based 策略需要知道脚本和分布式 master，后续生成事件时会读取这些上下文。
            input_policy.script = self.script
            input_policy.master = master
        return input_policy

    def add_event(self, event):
        """
        add one event to the event list
        :param event: the event to be added, should be subclass of AppEvent
        :return:
        """
        if event is None:
            return
        self.events.append(event)

        # EventLog 负责发送事件前后的状态保存、日志记录和可选 method profiling。
        # 因此这里不是直接 event.send(device)，而是交给 EventLog.start()/stop() 包装执行。
        event_log = EventLog(self.device, self.app, event, self.profiling_method)
        event_log.start()
        while True:
            time.sleep(self.event_interval)
            if not self.device.pause_sending_event:
                break
        event_log.stop()

    def start(self):
        """
        start sending event
        """
        self.logger.info("start sending events, policy is %s" % self.policy_name)

        try:
            if self.policy is not None:
                # 大多数 LLMDroid/DroidBot 策略会进入这里，由 policy.start() 循环生成事件。
                self.policy.start(self)
            elif self.policy_name == POLICY_NONE:
                # none 模式只启动 App，不自动发送事件，适合人工调试当前页面状态。
                self.device.start_app(self.app)
                if self.event_count == 0:
                    return
                while self.enabled:
                    time.sleep(1)
            elif self.policy_name == POLICY_MONKEY:
                # monkey 模式绕过 DroidBot 的 UTG/LLM 逻辑，直接调用 Android 系统 monkey。
                throttle = self.event_interval * 1000
                monkey_cmd = "adb -s %s shell monkey %s --ignore-crashes --ignore-security-exceptions" \
                             " --throttle %d -v %d" % \
                             (self.device.serial,
                              "" if self.app.get_package_name() is None else "-p " + self.app.get_package_name(),
                              throttle,
                              self.event_count)
                self.monkey = subprocess.Popen(monkey_cmd.split(),
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE)
                for monkey_out_line in iter(self.monkey.stdout.readline, ''):
                    if not isinstance(monkey_out_line, str):
                        monkey_out_line = monkey_out_line.decode()
                    self.logger.info(monkey_out_line)
                # may be disturbed from outside
                if self.monkey is not None:
                    self.monkey.wait()
            elif self.policy_name == POLICY_MANUAL:
                # manual 模式由用户手动操作设备，每次回车保存当前页面状态，便于构造样本。
                self.device.start_app(self.app)
                while self.enabled:
                    keyboard_input = input("press ENTER to save current state, type q to exit...")
                    if keyboard_input.startswith('q'):
                        break
                    state = self.device.get_current_state()
                    if state is not None:
                        state.save2dir()
        except KeyboardInterrupt:
            pass

        self.stop()
        self.logger.info("Finish sending events")

    def stop(self):
        """
        stop sending event
        """
        if self.policy and isinstance(self.policy, UtgBasedInputPolicy):
            # 退出前输出 StateCluster/函数分析结果，便于复盘 LLM 对页面的理解。
            self.policy.debug_states()

        if self.monkey:
            if self.monkey.returncode is None:
                self.monkey.terminate()
            self.monkey = None
            pid = self.device.get_app_pid("com.android.commands.monkey")
            if pid is not None:
                self.device.adb.shell("kill -9 %d" % pid)
        self.enabled = False

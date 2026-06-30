# 鏂囦欢浣滅敤锛?# 1. 浣滀负 DroidBot/LLMDroid 鐨勪簨浠惰皟搴﹀櫒锛屾牴鎹?policy_name 鍒涘缓鍏蜂綋杈撳叆绛栫暐銆?# 2. 缁熶竴绠＄悊浜嬩欢鍙戦€併€佷簨浠堕棿闅斻€佷簨浠舵棩蹇椼€乵ethod profiling 鍜?Monkey/manual/replay 鍒嗘敮銆?# 3. 鍦?LLMDroid-Droidbot 涓紝瀹冭礋璐ｆ妸绛栫暐灞傜敓鎴愮殑 InputEvent 鍖呰涓?EventLog 骞朵笅鍙戝埌璁惧銆?import subprocess
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

    涓枃璇存槑锛欼nputManager 鏄€滀簨浠惰皟搴﹀眰鈥濄€傚畠涓嶇洿鎺ュ喅瀹氱偣鍝釜鎺т欢锛?    鑰屾槸鏍规嵁 policy_name 鍒涘缓鍏蜂綋绛栫暐锛屽啀鎶婄瓥鐣ョ敓鎴愮殑浜嬩欢鍖呰鎴?EventLog 鍚庡彂閫佸埌璁惧銆?    """

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
            # script 鐢ㄤ簬鍦ㄧ壒瀹氶〉闈㈠己鍒舵墽琛岄瀹氫箟鍔ㄤ綔锛屼紭鍏堢骇楂樹簬鏅€氭帰绱㈢瓥鐣ャ€?            f = open(script_path, 'r')
            script_dict = json.load(f)
            from .input_script import DroidBotScript
            self.script = DroidBotScript(script_dict)

        self.policy = self.get_input_policy(device, app, master, code_coverage)
        self.profiling_method = profiling_method

    def get_input_policy(self, device, app, master, code_coverage):
        # policy_name 鍐冲畾鐪熸鐨勪簨浠剁敓鎴愬櫒銆侺LMDroid 鐨勬牳蹇冮€昏緫鎸傚湪 UTG-based 绛栫暐涓婏紝
        # 鍗?naive/greedy/manual 绛夌户鎵挎垨澶嶇敤 UtgBasedInputPolicy 鐨勭瓥鐣ャ€?        if self.policy_name == POLICY_NONE:
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
            # UTG-based 绛栫暐闇€瑕佺煡閬撹剼鏈拰鍒嗗竷寮?master锛屽悗缁敓鎴愪簨浠舵椂浼氳鍙栬繖浜涗笂涓嬫枃銆?            input_policy.script = self.script
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

        # EventLog 璐熻矗鍙戦€佷簨浠跺墠鍚庣殑鐘舵€佷繚瀛樸€佹棩蹇楄褰曞拰鍙€?method profiling銆?        # 鍥犳杩欓噷涓嶆槸鐩存帴 event.send(device)锛岃€屾槸浜ょ粰 EventLog.start()/stop() 鍖呰鎵ц銆?        event_log = EventLog(self.device, self.app, event, self.profiling_method)
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
                # 澶у鏁?LLMDroid/DroidBot 绛栫暐浼氳繘鍏ヨ繖閲岋紝鐢?policy.start() 寰幆鐢熸垚浜嬩欢銆?                self.policy.start(self)
            elif self.policy_name == POLICY_NONE:
                # none 妯″紡鍙惎鍔?App锛屼笉鑷姩鍙戦€佷簨浠讹紝閫傚悎浜哄伐璋冭瘯褰撳墠椤甸潰鐘舵€併€?                self.device.start_app(self.app)
                if self.event_count == 0:
                    return
                while self.enabled:
                    time.sleep(1)
            elif self.policy_name == POLICY_MONKEY:
                # monkey 妯″紡缁曡繃 DroidBot 鐨?UTG/LLM 閫昏緫锛岀洿鎺ヨ皟鐢?Android 绯荤粺 monkey銆?                throttle = self.event_interval * 1000
                monkey_cmd = "adb -s %s shell monkey %s --ignore-crashes --ignore-security-exceptions" \
                             " --throttle %d -v %d" % \
                             (self.device.serial,
                              "" if self.app.get_package_name() is None else "-p " + self.app.get_package_name(),
                              throttle,
                              self.event_count)
                self.monkey = subprocess.Popen(monkey_cmd.split(),
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE,
                                               text=True)
                stdout, stderr = self.monkey.communicate()
                for monkey_out_line in stdout.splitlines():
                    if monkey_out_line.strip():
                        self.logger.info(monkey_out_line)
                for monkey_err_line in stderr.splitlines():
                    if monkey_err_line.strip():
                        self.logger.warning(monkey_err_line)
                # may be disturbed from outside
                if self.monkey is not None:
                    self.monkey.wait()
            elif self.policy_name == POLICY_MANUAL:
                # manual 妯″紡鐢辩敤鎴锋墜鍔ㄦ搷浣滆澶囷紝姣忔鍥炶溅淇濆瓨褰撳墠椤甸潰鐘舵€侊紝渚夸簬鏋勯€犳牱鏈€?                self.device.start_app(self.app)
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
            # 閫€鍑哄墠杈撳嚭 StateCluster/鍑芥暟鍒嗘瀽缁撴灉锛屼究浜庡鐩?LLM 瀵归〉闈㈢殑鐞嗚В銆?            self.policy.debug_states()

        if self.monkey:
            if self.monkey.returncode is None:
                self.monkey.terminate()
            self.monkey = None
            pid = self.device.get_app_pid("com.android.commands.monkey")
            if pid is not None:
                self.device.adb.shell("kill -9 %d" % pid)
        self.enabled = False


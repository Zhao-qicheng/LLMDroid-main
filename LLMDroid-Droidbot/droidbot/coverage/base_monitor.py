# 文件作用：
# 1. 定义覆盖率监控基类，提供覆盖率历史记录、增长率计算和低增长检测。
# 2. 为 AndroLog/Jacoco 覆盖率实现提供统一接口 _get_code_coverage()。
# 3. 是 LLMDroid 从自主探索切换到 LLM Guidance 的触发判断基础。
from ..global_log import get_logger
from abc import ABCMeta, abstractmethod
import math
import os
import time


class CodeCoverageMonitor(metaclass=ABCMeta):
    """
    中文说明：覆盖率监控基类只负责“增长率是否变低”的通用判断。
    具体覆盖率来源由 AndroLog/Jacoco 子类实现 _get_code_coverage()。
    """

    def __init__(self, save_dir: str, wsize=10, min_growth_rate=0.05, factor=0.5):
        self.logger = get_logger()
        self.__file_path = os.path.join(save_dir, 'codecoverage.txt')

        try:
            with open(self.__file_path, 'w') as file:
                file.write("code coverage\n")
                local_time = time.localtime(time.time())
                formatted_local_time = time.strftime('%Y-%m-%d %H:%M:%S', local_time)
                file.write(f"start time: {formatted_local_time}\n")
        except IOError as e:
            self.logger.error(e)

        # monitor
        # 滑动窗口保存最近若干次覆盖率增长率，用于判断自主探索是否进入瓶颈。
        self.__WINDOW_SIZE: int = wsize
        self.__MIN_GROWTH_RATE: float = min_growth_rate
        self.__FACTOR: float = factor
        self.__MIN_THRESHOLD = 0.01
        self.__window = (0, self.__WINDOW_SIZE)
        self.__current_coverage: float = 0.00001
        self.__cv_history: list[float] = []
        self.__adjusted_threshold = self.__MIN_GROWTH_RATE
        self.__growth_rate_sum = 0.0
        self.__gr_to_check: list[float] = []

    @abstractmethod
    def _get_code_coverage(self) -> float:
        pass

    def __update(self, current_cv: float):
        # 每次检查前把当前覆盖率加入历史，并根据历史增长情况动态调整阈值。
        self.__cv_history.append(current_cv)
        n = len(self.__cv_history)
        current_growth_rate = 0.0
        if n >= 2:
            # gn = (xn - xn-1) / xn-1
            current_growth_rate = (current_cv - self.__cv_history[-2]) / self.__cv_history[-2]
            self.__growth_rate_sum += min(10.0, current_growth_rate)
            # update growth rate list to check
            self.__gr_to_check.append(current_growth_rate)
            if len(self.__gr_to_check) > self.__WINDOW_SIZE:
                self.__gr_to_check.pop(0)
            self.logger.info(f"[CV_Monitor]({len(self.__gr_to_check)}) growth rate: {current_growth_rate}, sum:{self.__growth_rate_sum}")
        # Adjust the threshold when the number of collected growth rates is greater than the window value
        if n >= self.__WINDOW_SIZE:
            # G
            baseline = self.__growth_rate_sum / (n - 1)
            # delta_g = gn - G
            delta_g = current_growth_rate - baseline

            # Tn = T0 * exp(k * delta_g)
            adjusted = self.__adjusted_threshold * math.exp(self.__FACTOR * delta_g)
            self.__adjusted_threshold = max(adjusted, self.__MIN_THRESHOLD)
            self.logger.info(f"[CV_Monitor] G:{baseline:8.5f}, delta_g:{delta_g:8.5f}, adjusted_threshold:{self.__adjusted_threshold:8.5f}")

    def update_code_coverage(self):
        # 子类负责获取当前覆盖率，本基类只缓存结果。
        self.__current_coverage = self._get_code_coverage()

    def check_low_growth_rate(self) -> bool:
        # update current code coverage and adjust threshold
        # 返回 True 表示窗口内增长都低于阈值，父策略会据此切换到 LLM Guidance。
        self.__update(self.__current_coverage)

        if len(self.__gr_to_check) == self.__WINDOW_SIZE:
            reverse = self.__gr_to_check[::-1]
            for i, gr in enumerate(reverse):
                if gr > self.__adjusted_threshold:
                    self.logger.info(f"[CV_Monitor Check] {i} to the end")
                    return False
            return True
        else:
            return False

    def _save_to_file(self, content: str):
        try:
            with open(self.__file_path, 'a') as file:
                file.write(content + "\n")
        except IOError as e:
            print(e)

    def clear(self):
        # 一轮 Guidance 结束后清空窗口，避免旧的低增长记录立刻再次触发 LLM。
        self.__gr_to_check.clear()

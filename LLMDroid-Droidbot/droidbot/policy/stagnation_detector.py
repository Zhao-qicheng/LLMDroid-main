# 文件作用：
# 1. 实现 Code-State-Widget 三维联合停滞检测（CSW-SD）。
# 2. 只读取覆盖率 monitor 与 UTG 已有信息，不改变 DroidBot 探索核心。
# 3. 为 UtgBasedInputPolicy 判断何时从 EXPLORE 切换到 LLM Guidance。
from typing import Optional, Sequence

from ..coverage.base_monitor import CodeCoverageMonitor
from ..desc.device_state import DeviceState
from ..desc.utg import UTG
from ..global_log import get_logger


Transition = tuple[DeviceState, object, DeviceState]
logger = get_logger()


def window_ready(transitions: Sequence[Transition], window: int) -> bool:
    return window > 0 and len(transitions) >= window


def count_effective_in_window(
    transitions: Sequence[Transition], window: int
) -> int:
    if window <= 0 or not transitions:
        return 0
    recent = transitions[-window:]
    return sum(
        1
        for old_state, _event, new_state in recent
        if old_state is not None
        and new_state is not None
        and old_state.state_str != new_state.state_str
    )


def local_unexplored_ratio(utg: UTG, state: DeviceState) -> float:
    if state is None:
        return 0.0
    possible = state.get_possible_input()
    if not possible:
        return 0.0
    explored = sum(
        1 for event in possible if utg.is_event_explored(event, state)
    )
    return 1.0 - explored / len(possible)


def invalid_ratio_in_window(
    transitions: Sequence[Transition], window: int
) -> float:
    if window <= 0 or not transitions:
        return 0.0
    recent = transitions[-window:]
    invalid = sum(
        1
        for old_state, _event, new_state in recent
        if old_state is not None
        and new_state is not None
        and old_state.state_str == new_state.state_str
    )
    return invalid / len(recent)


def log_stagnation_stats(
    code_ready: bool,
    code_stalled: bool,
    code_active: bool,
    recent_gr: float,
    state_ready: bool,
    state_stalled: bool,
    delta_e_eff: int,
    u_local: float,
    r_invalid: float,
    widget_stalled: bool,
) -> None:
    logger.info(
        "[CSW-SD] ready=%s code_ready=%s code_stalled=%s "
        "code_active=%s recent_gr=%.6f state_stalled=%s "
        "delta_e_eff=%d u_local=%.3f r_invalid=%.3f widget_stalled=%s",
        state_ready,
        code_ready,
        code_stalled,
        code_active,
        recent_gr,
        state_stalled,
        delta_e_eff,
        u_local,
        r_invalid,
        widget_stalled,
    )


def should_trigger_guide(
    utg: UTG,
    cv_monitor: CodeCoverageMonitor,
    current_state: DeviceState,
    window: Optional[int] = None,
    eps_state: int = 0,
    eps_widget: float = 0.05,
    r_thresh: float = 0.7,
) -> bool:
    # Code 维：check_low_growth_rate() 会推进覆盖率增长窗口。
    code_stalled = cv_monitor.check_low_growth_rate()
    code_ready = cv_monitor.growth_window_ready()
    recent_gr = cv_monitor.recent_gr()
    code_active = code_ready and (not code_stalled)

    # State / Widget 维：默认与 Code monitor 窗口保持同一契约。
    actual_window = window if window is not None else cv_monitor.window_size
    state_ready = window_ready(utg.transitions, actual_window)

    delta_e_eff = count_effective_in_window(utg.transitions, actual_window)
    state_stalled = state_ready and (delta_e_eff <= eps_state)

    u_local = local_unexplored_ratio(utg, current_state)
    widget_stalled = state_ready and (u_local < eps_widget)
    r_invalid = (
        invalid_ratio_in_window(utg.transitions, actual_window)
        if state_ready
        else 0.0
    )

    log_stagnation_stats(
        code_ready=code_ready,
        code_stalled=code_stalled,
        code_active=code_active,
        recent_gr=recent_gr,
        state_ready=state_ready,
        state_stalled=state_stalled,
        delta_e_eff=delta_e_eff,
        u_local=u_local,
        r_invalid=r_invalid,
        widget_stalled=widget_stalled,
    )

    # R1: Code 与 State 双停，说明全局探索收益不足。
    if code_ready and code_stalled and state_stalled:
        return True
    # R2: Code 仍活跃但 UI 无新有效转移，处理 UI-Code 分歧。
    if code_ready and code_active and state_stalled:
        return True
    # R3: 当前页控件基本耗尽，且最近窗口同页空转比例过高。
    if state_ready and widget_stalled and r_invalid > r_thresh:
        return True
    # R4: Code 低增长但 UI 仍有有效转移，继续交给 greedy 探索。
    if code_ready and code_stalled and not state_stalled:
        return False
    return False

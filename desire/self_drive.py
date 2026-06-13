from __future__ import annotations

"""self_drive.py — 自驱模块

好奇心自增长地板、自体验脉冲等。
让系统在无外部刺激时也能缓慢"醒来"。
"""

from .config import (
    SELF_DRIVE_PULSE_DELTA, CURIOSITY_SELF_GROW_RATE,
    CURIOSITY_SELF_GROW_CAP, DRIVE_TO_ACTION,
)
from .state import DesireState, clamp_drives
from .desire import pulse_drive, source_drive_for


def self_experience_pulse(
    state: DesireState,
    action: str,
    material: str,
) -> None:
    """自体验脉冲：因自己执行的动作而产生的驱力脉冲

    与外部脉冲不同，使用较小的 SELF_DRIVE_PULSE_DELTA。

    Args:
        state: 当前状态
        action: 执行的动作类型
        material: 动作产生的素材文本（目前未使用，留给未来扩展）
    """
    drive_key = source_drive_for(action)
    if drive_key:
        pulse_drive(state, drive_key, SELF_DRIVE_PULSE_DELTA, source='self')
        state.self_drive_stats['today_self_actions'] = (
            state.self_drive_stats.get('today_self_actions', 0) + 1
        )


def curiosity_self_grow(state: DesireState) -> None:
    """好奇心自增长：每 tick 缓慢提高好奇心地板

    地板值以 CURIOSITY_SELF_GROW_RATE 增长，上限为 CURIOSITY_SELF_GROW_CAP。
    """
    state.curiosity_self_floor = min(
        CURIOSITY_SELF_GROW_CAP,
        state.curiosity_self_floor + CURIOSITY_SELF_GROW_RATE,
    )


def apply_self_drive(state: DesireState) -> None:
    """每 tick 调用的自驱逻辑

    1. 增长好奇心地板
    2. 确保好奇心不低于地板值
    """
    curiosity_self_grow(state)

    # 确保好奇心不低于自驱地板
    if state.drive['curiosity'] < state.curiosity_self_floor:
        state.drive['curiosity'] = state.curiosity_self_floor

    clamp_drives(state)

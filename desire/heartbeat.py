from __future__ import annotations

"""heartbeat.py — 自主心跳节奏

根据内在张力、疲劳等动态调整心跳间隔。
full_tick 编排一次完整的心跳周期：念头 tick → 耦合 → 意图拣选 → 执行 → 满足 → 保存。
"""

import logging
from typing import Any

from config import (
    DRIVE_KEYS, HEARTBEAT_BASE, HEARTBEAT_LOW_TENSION_GAIN,
    HEARTBEAT_TENSION_GAIN, HEARTBEAT_FATIGUE_GAIN,
    HEARTBEAT_MIN, HEARTBEAT_MAX,
    GATE_COUPLING, GATE_DESIRE_DRIVEN, GATE_SELF_DRIVE,
    gate,
)
from state import DesireState, save_state
from desire import (
    tick_thoughts, pick_intent, satisfy, tick_refractory,
    do_action, autofeed_action_thought,
)
from coupling import apply_coupling
from self_drive import apply_self_drive

logger = logging.getLogger(__name__)


def compute_tension(state: DesireState) -> float:
    """计算内在张力：非疲劳维度的驱力均值"""
    non_fatigue = [v for k, v in state.drive.items() if k != 'fatigue']
    if not non_fatigue:
        return 0.0
    return sum(non_fatigue) / len(non_fatigue)


def compute_heartbeat_interval(state: DesireState) -> float:
    """根据张力和疲劳计算心跳间隔（秒）

    公式:
        interval = BASE * (1 - tension * TENSION_GAIN
                             + (1 - tension) * LOW_TENSION_GAIN
                             + fatigue * FATIGUE_GAIN)

    张力高 → 间隔短（更活跃）
    疲劳高 → 间隔长（更慵懒）
    结果夹在 [MIN, MAX] 内。
    """
    tension = compute_tension(state)
    fatigue = state.drive.get('fatigue', 0.0)

    factor = (
        1.0
        - tension * HEARTBEAT_TENSION_GAIN
        + (1.0 - tension) * HEARTBEAT_LOW_TENSION_GAIN
        + fatigue * HEARTBEAT_FATIGUE_GAIN
    )

    interval = HEARTBEAT_BASE * factor
    return max(HEARTBEAT_MIN, min(HEARTBEAT_MAX, interval))


def full_tick(state: DesireState, state_path: str | None = None) -> dict[str, Any]:
    """编排一次完整的心跳 tick

    流程:
        1. tick_thoughts — 念头池衰减/增长/反哺/消解
        2. 如果耦合开关开启：apply_coupling + tick_refractory
        3. 如果自驱开关开启：apply_self_drive
        4. pick_intent — 拣选意图
        5. 如果驱动开关开启：do_action 执行意图
        6. 如果执行了动作：satisfy 回滚 + autofeed 生成念头
        7. 递增 tick 计数
        8. save_state 持久化

    Returns:
        {
            'tick': int,
            'tension': float,
            'intent': dict,
            'action_result': str | None,
            'heartbeat_interval': float,
        }
    """
    # 1. 念头池 tick
    tick_thoughts(state)

    # 2. 耦合
    if gate(GATE_COUPLING):
        apply_coupling(state)
        tick_refractory(state)

    # 3. 自驱
    if gate(GATE_SELF_DRIVE):
        apply_self_drive(state)

    # 4. 拣选意图
    intent = pick_intent(state)

    # 5. 执行动作
    action_result: str | None = None
    if gate(GATE_DESIRE_DRIVEN) and intent['want_action'] != 'rest':
        action_result = do_action(state, intent)

        # 6. 满足回滚 + 自动生成念头
        satisfy(state, intent['want_action'])
        if action_result:
            autofeed_action_thought(
                state,
                intent['want_action'],
                action_result,
            )

    # 7. 递增 tick
    state.tick_count += 1

    # 8. 保存
    save_state(state, state_path)

    tension = compute_tension(state)
    interval = compute_heartbeat_interval(state)

    summary = {
        'tick': state.tick_count,
        'tension': round(tension, 4),
        'intent': intent,
        'action_result': action_result,
        'heartbeat_interval': round(interval, 1),
    }

    logger.info('Tick %d 完成 | 张力=%.3f | 意图=%s', state.tick_count, tension, intent.get('want_action'))
    return summary

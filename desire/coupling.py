from __future__ import annotations

"""coupling.py — 驱力耦合网络

维度之间的相互影响：
- level 模式：持续施压（基于当前值）
- delta 模式：仅在上升时（基于与上一 tick 的差值）
- 全局阻尼：每 tick 向基线回归
"""

from config import (
    COUPLING_EDGES, COUPLING_DAMPING, DRIVE_BASELINE, DRIVE_KEYS,
)
from state import DesireState, clamp_drives


def apply_coupling(state: DesireState) -> None:
    """执行一个 tick 的耦合计算

    遍历所有耦合边，根据模式计算影响量并施加到目标维度。
    最后进行全局阻尼（向基线缓慢回归）。
    所有结果夹在 [0, 1] 内。
    """
    # 累积增量（避免顺序依赖）
    deltas: dict[str, float] = {k: 0.0 for k in DRIVE_KEYS}

    for source, target, coeff, mode in COUPLING_EDGES:
        source_val = state.drive.get(source, 0.0)

        if mode == 'level':
            # 持续施压：effect = source_value * coefficient
            effect = source_val * coeff
        elif mode == 'delta':
            # 仅上升时：effect = max(0, current - prev) * coefficient
            prev_val = state.prev_drive.get(source, 0.0)
            rise = max(0.0, source_val - prev_val)
            effect = rise * coeff
        else:
            effect = 0.0

        deltas[target] += effect

    # 全局阻尼：向基线回归
    for k in DRIVE_KEYS:
        baseline = DRIVE_BASELINE.get(k, 0.3)
        diff = baseline - state.drive[k]
        deltas[k] += diff * COUPLING_DAMPING

    # 保存当前驱力作为下一 tick 的 prev_drive
    state.prev_drive = dict(state.drive)

    # 施加增量
    for k in DRIVE_KEYS:
        state.drive[k] += deltas[k]

    # 夹值
    clamp_drives(state)

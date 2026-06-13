from __future__ import annotations

"""state.py — 欲望系统状态定义与持久化

DesireState 是运行时状态容器，包括 8 维驱力、念头池、不应期计时器等。
Thought 是念头数据类，分 flit（闪念）和 fixation（执念）两种。
load_state / save_state 负责 JSON 序列化。
"""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .config import DRIVE_KEYS, DRIVE_DEFAULTS


# ──────────────────────────────────────────
# 念头 (Thought) 数据类
# ──────────────────────────────────────────
@dataclass
class Thought:
    """一条念头：可能是闪念 (flit) 或执念 (fixation)"""
    text: str                          # 念头内容
    drive: str                         # 关联驱力维度
    kind: str = 'flit'                 # 'flit' | 'fixation'
    strength: float = 0.6              # 当前强度 [0, 1]
    fed_count: int = 0                 # 反哺驱力的次数（仅 fixation 使用）

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Thought:
        """从字典反序列化"""
        return cls(
            text=d['text'],
            drive=d['drive'],
            kind=d.get('kind', 'flit'),
            strength=d.get('strength', 0.6),
            fed_count=d.get('fed_count', 0),
        )


# ──────────────────────────────────────────
# 欲望系统运行时状态
# ──────────────────────────────────────────
@dataclass
class DesireState:
    """欲望系统的完整运行时状态"""

    # 8 维驱力值，全部 clamp 到 [0, 1]
    drive: dict[str, float] = field(default_factory=lambda: dict(DRIVE_DEFAULTS))

    # 念头池
    thoughts: list[Thought] = field(default_factory=list)

    # 不应期倒计时（drive_key -> 剩余 ticks）
    refractory: dict[str, int] = field(default_factory=dict)

    # 上一 tick 的驱力快照（用于 delta 耦合）
    prev_drive: dict[str, float] = field(default_factory=lambda: dict(DRIVE_DEFAULTS))

    # 全局 tick 计数
    tick_count: int = 0

    # 最近动作记录 [(action, tick)]（用于频率折扣）
    last_actions: list[tuple[str, int]] = field(default_factory=list)

    # 好奇心自驱地板
    curiosity_self_floor: float = 0.0

    # 自驱统计
    self_drive_stats: dict[str, Any] = field(default_factory=lambda: {
        'today_self_actions': 0,
        'last_self_pulse': None,
    })


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """将值夹在 [lo, hi] 区间"""
    return max(lo, min(hi, v))


def clamp_drives(state: DesireState) -> None:
    """确保所有驱力值都在 [0, 1] 范围内"""
    for k in DRIVE_KEYS:
        state.drive[k] = _clamp(state.drive[k])


# ──────────────────────────────────────────
# 序列化 / 反序列化
# ──────────────────────────────────────────

def _state_to_dict(state: DesireState) -> dict[str, Any]:
    """将 DesireState 序列化为可 JSON 化的字典"""
    return {
        'drive': dict(state.drive),
        'thoughts': [t.to_dict() for t in state.thoughts],
        'refractory': dict(state.refractory),
        'prev_drive': dict(state.prev_drive),
        'tick_count': state.tick_count,
        'last_actions': list(state.last_actions),
        'curiosity_self_floor': state.curiosity_self_floor,
        'self_drive_stats': dict(state.self_drive_stats),
    }


def _dict_to_state(d: dict[str, Any]) -> DesireState:
    """从字典反序列化为 DesireState"""
    state = DesireState()

    # 驱力
    if 'drive' in d:
        for k in DRIVE_KEYS:
            state.drive[k] = float(d['drive'].get(k, DRIVE_DEFAULTS[k]))

    # 念头
    if 'thoughts' in d:
        state.thoughts = [Thought.from_dict(t) for t in d['thoughts']]

    # 不应期
    if 'refractory' in d:
        state.refractory = {k: int(v) for k, v in d['refractory'].items()}

    # 上一 tick 驱力
    if 'prev_drive' in d:
        for k in DRIVE_KEYS:
            state.prev_drive[k] = float(d['prev_drive'].get(k, DRIVE_DEFAULTS[k]))

    # tick 计数
    state.tick_count = int(d.get('tick_count', 0))

    # 最近动作
    if 'last_actions' in d:
        state.last_actions = [(str(a), int(t)) for a, t in d['last_actions']]

    # 好奇心自驱地板
    state.curiosity_self_floor = float(d.get('curiosity_self_floor', 0.0))

    # 自驱统计
    if 'self_drive_stats' in d:
        state.self_drive_stats = dict(d['self_drive_stats'])

    clamp_drives(state)
    return state


# ──────────────────────────────────────────
# 文件读写
# ──────────────────────────────────────────

DEFAULT_STATE_PATH: str = os.path.join(os.path.dirname(__file__), 'data', 'desire_thoughts.json')


def load_state(path: str | None = None) -> DesireState:
    """从 JSON 文件加载状态，文件不存在或格式异常则返回默认状态"""
    path = path or DEFAULT_STATE_PATH
    p = Path(path)
    if not p.exists():
        return DesireState()
    try:
        with open(p, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        # 兼容只含 thoughts 数组的旧格式
        if isinstance(raw, dict) and 'drive' not in raw and 'thoughts' in raw:
            return DesireState()
        return _dict_to_state(raw)
    except (json.JSONDecodeError, KeyError, TypeError):
        return DesireState()


def save_state(state: DesireState, path: str | None = None) -> None:
    """将状态序列化写入 JSON 文件"""
    path = path or DEFAULT_STATE_PATH
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    clamp_drives(state)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(_state_to_dict(state), f, ensure_ascii=False, indent=2)

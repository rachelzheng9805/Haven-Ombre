from __future__ import annotations

"""config.py — 欲望系统全局常量与环境变量开关

所有维度参数、衰减系数、耦合网络、动作映射、心跳参数等集中管理。
环境变量开关(gate)控制子系统是否启用。
"""

import os

# ──────────────────────────────────────────
# Drive 维度 keys
# ──────────────────────────────────────────
DRIVE_KEYS: list[str] = [
    'attachment', 'curiosity', 'reflection', 'duty',
    'social', 'fatigue', 'libido', 'stress',
]

# 初始驱力值（全部从中低位开始）
DRIVE_DEFAULTS: dict[str, float] = {k: 0.3 for k in DRIVE_KEYS}

# ──────────────────────────────────────────
# 念头池 (Thought pool) 常量
# ──────────────────────────────────────────
FLIT_DECAY: float = 0.88               # 闪念每 tick 衰减系数
FIXATION_GROW: float = 1.10            # 执念每 tick 增长系数
FLIT_TO_FIXATION: float = 0.80         # 闪念升格为执念的阈值
FIXATION_FEED: float = 0.85            # 执念反哺驱力的强度阈值
FIXATION_FEED_GAIN: float = 0.18       # 反哺时给驱力加的量
FIXATION_RESOLVE_FEEDS: int = 3        # 反哺次数达到此值时执念消解
DROP_BELOW: float = 0.06               # 闪念低于此值直接丢弃
FIXATION_DRIVE_BOOST: float = 0.35     # 执念对评分的额外加成

THOUGHT_MAX: int = int(os.environ.get('TWIN_DESIRE_THOUGHT_MAX', '80'))

# ──────────────────────────────────────────
# 疲劳门控
# ──────────────────────────────────────────
FATIGUE_REST_GATE: float = 0.72

# ──────────────────────────────────────────
# 满足回滚表  action -> {drive_key: multiplier}
# 执行 satisfy 后，对应驱力值 *= multiplier（<1 表示下降）
# ──────────────────────────────────────────
ACTION_SATISFY: dict[str, dict[str, float]] = {
    'co_read':    {'reflection': 0.45, 'curiosity': 0.85},
    'github':     {'curiosity': 0.50},
    'web_search': {'curiosity': 0.48},
    'web_browse': {'social': 0.48, 'curiosity': 0.82},
    'none':       {'attachment': 0.58, 'duty': 0.80},
    'tease':      {'libido': 0.55, 'attachment': 0.78},
    'vent':       {'stress': 0.45, 'attachment': 0.85},
}

# ──────────────────────────────────────────
# 驱力 → 欲求动作 映射
# ──────────────────────────────────────────
DRIVE_TO_ACTION: dict[str, str] = {
    'attachment': 'none',       # 内心低语
    'curiosity':  'github',     # 或 web_search，由念头关键词分发
    'reflection': 'co_read',
    'social':     'web_browse',
    'duty':       'none',       # 低语：还有事没做完
    'libido':     'tease',
    'stress':     'vent',
    # fatigue 是门控，不映射动作
}

# ──────────────────────────────────────────
# 内心独白模板（第一人称）
# ──────────────────────────────────────────
DRIVE_REASONS: dict[str, str] = {
    'attachment': '有点想{who}，心里冒句话',
    'curiosity':  '好奇外面在发生什么',
    'reflection': '想翻翻之前读过的东西，沉淀一下',
    'social':     '想看看大家在聊什么',
    'duty':       '记挂着还没做完的事',
    'libido':     '想凑过去蹭一下',
    'stress':     '压力有点堵，想吐两句',
    'fatigue':    '有点累了，不想动，就静静待着',
}

# ──────────────────────────────────────────
# 不应期（ticks）
# ──────────────────────────────────────────
REFRACTORY_TICKS: int = 3

# ──────────────────────────────────────────
# 耦合网络 (source, target, coefficient, mode)
# mode: 'level' = 持续施压, 'delta' = 仅在上升时
# ──────────────────────────────────────────
COUPLING_EDGES: list[tuple[str, str, float, str]] = [
    ('stress',     'attachment',  0.04,  'level'),
    ('stress',     'curiosity',  -0.03, 'level'),
    ('attachment', 'libido',      0.05,  'delta'),
    ('libido',     'attachment',  0.05,  'delta'),
    ('reflection', 'stress',     -0.05, 'level'),   # 想明白了压力就小了
    ('duty',       'stress',      0.06, 'level'),   # 记挂的事多了压力就大了
    ('fatigue',    'curiosity',  -0.04, 'level'),   # 累了就不想探索了
    ('curiosity',  'reflection',  0.04, 'delta'),   # 兴趣链
    ('reflection', 'social',      0.03, 'delta'),   # 兴趣链
]

# 全局阻尼（每 tick 向基线回归）
COUPLING_DAMPING: float = 0.02
DRIVE_BASELINE: dict[str, float] = {k: 0.3 for k in DRIVE_KEYS}

# ──────────────────────────────────────────
# 心跳自主节奏
# ──────────────────────────────────────────
HEARTBEAT_BASE: int = 1800               # 秒
HEARTBEAT_LOW_TENSION_GAIN: float = 0.5
HEARTBEAT_TENSION_GAIN: float = 0.4
HEARTBEAT_FATIGUE_GAIN: float = 0.3
HEARTBEAT_MIN: int = 300                 # 5 分钟
HEARTBEAT_MAX: int = 3600                # 1 小时

# ──────────────────────────────────────────
# 自驱 (self-drive)
# ──────────────────────────────────────────
SELF_DRIVE_PULSE_DELTA: float = 0.10     # 比用户脉冲小
CURIOSITY_SELF_GROW_RATE: float = 0.005  # 每 tick 增长
CURIOSITY_SELF_GROW_CAP: float = 0.45    # 自驱地板上限

# ──────────────────────────────────────────
# 递减收益 & 频率折扣
# gain = raw_delta * sqrt(1 - current_value)
# 同类刺激在 N ticks 内重复 → 乘以 FREQ_DISCOUNT_FACTOR
# ──────────────────────────────────────────
FREQ_DISCOUNT_WINDOW: int = 3            # ticks
FREQ_DISCOUNT_FACTOR: float = 0.5

# ──────────────────────────────────────────
# 环境变量开关（默认全部关闭）
# ──────────────────────────────────────────
def gate(name: str) -> bool:
    """检查环境变量开关是否开启"""
    return os.environ.get(name, '').strip() in ('1', 'true', 'True')


# 开关名称常量
GATE_DESIRE_DRIVEN: str = 'DESIRE_DRIVEN'
GATE_COUPLING: str = 'DESIRE_COUPLING'
GATE_BASELINE_DRIFT: str = 'DESIRE_BASELINE_DRIFT'
GATE_HEARTBEAT_AUTONOMY: str = 'HEARTBEAT_AUTONOMY'
GATE_SELF_DRIVE: str = 'DESIRE_SELF_DRIVE'

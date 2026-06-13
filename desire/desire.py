from __future__ import annotations

"""desire.py — 欲望系统核心引擎

包含驱力脉冲、递减收益、念头池 tick、意图拣选、满足回滚、
通配机制、以及留给 MCP 工具集成的动作存根。
"""

import math
import random
import logging
from typing import Any

from .config import (
    DRIVE_KEYS, DRIVE_TO_ACTION, DRIVE_REASONS, ACTION_SATISFY,
    FLIT_DECAY, FIXATION_GROW, FLIT_TO_FIXATION, FIXATION_FEED,
    FIXATION_FEED_GAIN, FIXATION_RESOLVE_FEEDS, DROP_BELOW,
    FIXATION_DRIVE_BOOST, THOUGHT_MAX, FATIGUE_REST_GATE,
    REFRACTORY_TICKS, FREQ_DISCOUNT_WINDOW, FREQ_DISCOUNT_FACTOR,
)
from .state import DesireState, Thought, clamp_drives

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# 递减收益
# ──────────────────────────────────────────

def diminishing_gain(current: float, raw_delta: float) -> float:
    """递减收益公式：越接近 1，增益越小

    gain = raw_delta * sqrt(1 - current)

    当 current >= 1 时增益为 0，保证驱力不会溢出。
    """
    if current >= 1.0:
        return 0.0
    return raw_delta * math.sqrt(1.0 - current)


# ──────────────────────────────────────────
# 频率折扣
# ──────────────────────────────────────────

def freq_discount(action: str, state: DesireState) -> float:
    """计算同类动作在近期重复出现的折扣系数

    如果在最近 FREQ_DISCOUNT_WINDOW 个 ticks 内存在同类动作，
    返回 FREQ_DISCOUNT_FACTOR（<1），否则返回 1.0。
    """
    cutoff = state.tick_count - FREQ_DISCOUNT_WINDOW
    for past_action, tick in state.last_actions:
        if past_action == action and tick >= cutoff:
            return FREQ_DISCOUNT_FACTOR
    return 1.0


# ──────────────────────────────────────────
# 驱力脉冲
# ──────────────────────────────────────────

def pulse_drive(
    state: DesireState,
    drive_key: str,
    delta: float,
    source: str = 'external',
) -> float:
    """向某个驱力维度施加脉冲，带递减收益

    Args:
        state: 当前状态
        drive_key: 驱力维度名
        delta: 原始增量（可以为负）
        source: 来源标识（'external' | 'self' | 'coupling' 等）

    Returns:
        实际施加的增量
    """
    if drive_key not in state.drive:
        return 0.0

    current = state.drive[drive_key]
    if delta > 0:
        actual = diminishing_gain(current, delta)
    else:
        # 负方向也做对称递减：越接近 0 越难再降
        actual = -diminishing_gain(1.0 - current, abs(delta))

    state.drive[drive_key] = max(0.0, min(1.0, current + actual))
    return actual


# ──────────────────────────────────────────
# 念头池 tick
# ──────────────────────────────────────────

def tick_thoughts(state: DesireState) -> None:
    """念头池的一个 tick 周期

    1. 闪念 (flit) 衰减
    2. 执念 (fixation) 增长
    3. 闪念超过阈值 → 升格为执念
    4. 执念超过反哺阈值 → 给驱力加量，计数 +1
    5. 执念反哺次数达标 → 消解（从池中移除）
    6. 强度过低的闪念 → 丢弃
    7. 超过上限的旧念头 → 丢弃
    """
    to_remove: list[int] = []

    for i, thought in enumerate(state.thoughts):
        if thought.kind == 'flit':
            # 闪念衰减
            thought.strength *= FLIT_DECAY

            # 升格判断
            if thought.strength >= FLIT_TO_FIXATION:
                thought.kind = 'fixation'
                thought.fed_count = 0
                logger.debug('闪念升格为执念: %s', thought.text[:20])

            # 过弱丢弃
            elif thought.strength < DROP_BELOW:
                to_remove.append(i)

        elif thought.kind == 'fixation':
            # 执念增长
            thought.strength = min(1.0, thought.strength * FIXATION_GROW)

            # 反哺驱力
            if thought.strength >= FIXATION_FEED:
                gain = diminishing_gain(
                    state.drive.get(thought.drive, 0.0),
                    FIXATION_FEED_GAIN,
                )
                state.drive[thought.drive] = min(
                    1.0,
                    state.drive.get(thought.drive, 0.0) + gain,
                )
                thought.fed_count += 1

                # 消解判断
                if thought.fed_count >= FIXATION_RESOLVE_FEEDS:
                    to_remove.append(i)
                    logger.debug('执念消解: %s', thought.text[:20])

    # 倒序移除
    for idx in sorted(to_remove, reverse=True):
        state.thoughts.pop(idx)

    # 超限截断（保留最近的）
    if len(state.thoughts) > THOUGHT_MAX:
        state.thoughts = state.thoughts[-THOUGHT_MAX:]

    clamp_drives(state)


# ──────────────────────────────────────────
# 评分计算
# ──────────────────────────────────────────

def compute_scores(state: DesireState) -> dict[str, float]:
    """计算各驱力维度的综合评分

    score = (drive_value + 执念加成) × 频率折扣

    fatigue 不参与评分（它是门控维度）。
    频率折扣：同一类动作短期内重复做会被惩罚。
    """
    # 先统计每个维度有多少执念
    fixation_counts: dict[str, int] = {}
    for thought in state.thoughts:
        if thought.kind == 'fixation':
            fixation_counts[thought.drive] = fixation_counts.get(thought.drive, 0) + 1

    scores: dict[str, float] = {}
    for k in DRIVE_KEYS:
        if k == 'fatigue':
            continue  # 疲劳不参与评分
        base = state.drive[k]
        boost = FIXATION_DRIVE_BOOST * fixation_counts.get(k, 0)
        action = DRIVE_TO_ACTION.get(k, 'none')
        discount = freq_discount(action, state)
        scores[k] = (base + boost) * discount

    return scores


# ──────────────────────────────────────────
# 意图拣选
# ──────────────────────────────────────────

def pick_intent(state: DesireState) -> dict[str, Any]:
    """从当前状态中拣选最强烈的欲求意图

    返回:
        {
            'want_action': str,
            'drive_key': str,
            'reason': str,
            'score': float,
            'query_hint': str | None,
        }

    特殊规则:
        - 疲劳 >= FATIGUE_REST_GATE → 直接返回休息意图
        - 不应期中的驱力跳过
        - 通配机制：头部评分接近时随机选
    """
    # 疲劳门控
    if state.drive.get('fatigue', 0.0) >= FATIGUE_REST_GATE:
        return {
            'want_action': 'rest',
            'drive_key': 'fatigue',
            'reason': DRIVE_REASONS['fatigue'],
            'score': state.drive['fatigue'],
            'query_hint': None,
        }

    scores = compute_scores(state)

    # 过滤不应期
    available: dict[str, float] = {}
    for k, s in scores.items():
        if state.refractory.get(k, 0) <= 0:
            available[k] = s

    if not available:
        # 全部在不应期，返回默认
        return {
            'want_action': 'none',
            'drive_key': 'duty',
            'reason': '暂时没什么特别想做的',
            'score': 0.0,
            'query_hint': None,
        }

    # 通配判断
    if should_wildcard(state, available):
        return wildcard_pick(state)

    # 正常拣选：取最高分
    top_key = max(available, key=lambda k: available[k])
    action = DRIVE_TO_ACTION.get(top_key, 'none')

    # 查询提示：从相关念头中提取
    query_hint = _extract_query_hint(state, top_key)

    # curiosity 按念头关键词分流到 github 或 web_search
    if top_key == 'curiosity':
        action = _dispatch_curiosity_action(query_hint)

    return {
        'want_action': action,
        'drive_key': top_key,
        'reason': DRIVE_REASONS.get(top_key, '说不清楚'),
        'score': available[top_key],
        'query_hint': query_hint,
    }


def _extract_query_hint(state: DesireState, drive_key: str) -> str | None:
    """从念头池中提取与该驱力相关的最强念头文本作为查询提示"""
    relevant = [t for t in state.thoughts if t.drive == drive_key]
    if not relevant:
        return None
    return max(relevant, key=lambda t: t.strength).text


# 搜索类关键词——命中则走 web_search 而非 github
_SEARCH_KEYWORDS: list[str] = [
    '搜', '查', '是什么', '怎么', '为什么', '哪里', '多少',
    '什么是', '有没有', '如何', '能不能', 'search', 'what',
    'how', 'why', 'where', '找', '看看',
]


def _dispatch_curiosity_action(query_hint: str | None) -> str:
    """curiosity 按念头关键词分流到 github 或 web_search

    如果 query_hint 中含搜索类关键词，走 web_search；
    否则默认走 github（逛代码世界）。
    """
    if query_hint:
        for kw in _SEARCH_KEYWORDS:
            if kw in query_hint:
                return 'web_search'
    return 'github'


# ──────────────────────────────────────────
# 满足回滚
# ──────────────────────────────────────────

def satisfy(state: DesireState, action: str) -> None:
    """执行满足回滚：对应驱力值按表中的乘数衰减

    同时设置不应期和记录动作。
    """
    rollback = ACTION_SATISFY.get(action, {})
    for drive_key, multiplier in rollback.items():
        if drive_key in state.drive:
            state.drive[drive_key] *= multiplier

    # 记录不应期
    source_key = source_drive_for(action)
    if source_key:
        state.refractory[source_key] = REFRACTORY_TICKS

    # 记录动作（用于频率折扣）
    state.last_actions.append((action, state.tick_count))
    # 清理过老的记录
    cutoff = state.tick_count - FREQ_DISCOUNT_WINDOW * 2
    state.last_actions = [
        (a, t) for a, t in state.last_actions if t >= cutoff
    ]

    clamp_drives(state)


# ──────────────────────────────────────────
# 不应期 tick
# ──────────────────────────────────────────

def tick_refractory(state: DesireState) -> None:
    """所有不应期计数器减一，归零的移除"""
    expired = []
    for k in state.refractory:
        state.refractory[k] -= 1
        if state.refractory[k] <= 0:
            expired.append(k)
    for k in expired:
        del state.refractory[k]


# ──────────────────────────────────────────
# 念头喂入
# ──────────────────────────────────────────

def feed_thought(
    state: DesireState,
    text: str,
    drive: str,
    kind: str = 'flit',
    strength: float = 0.6,
) -> None:
    """向念头池中添加或强化一条念头

    如果已存在同 text 的念头，则叠加强度（取 max）。
    """
    for existing in state.thoughts:
        if existing.text == text:
            # 同一桩心事被反复点到——叠加强化（带递减收益）
            gain = diminishing_gain(existing.strength, strength * 0.3)
            existing.strength = min(1.0, existing.strength + gain)
            return

    state.thoughts.append(Thought(
        text=text,
        drive=drive,
        kind=kind,
        strength=min(1.0, strength),
    ))


def autofeed_voice_thought(state: DesireState, voice_text: str) -> None:
    """从内心独白自动生成念头

    使用当前最高驱力维度作为关联维度。
    """
    # 找最高驱力维度（排除 fatigue）
    candidates = {k: v for k, v in state.drive.items() if k != 'fatigue'}
    if not candidates:
        return
    top_drive = max(candidates, key=lambda k: candidates[k])
    feed_thought(state, voice_text, top_drive, kind='flit', strength=0.5)


def autofeed_action_thought(
    state: DesireState,
    action: str,
    material_text: str,
) -> None:
    """从外部动作结果自动生成念头

    根据动作类型反查关联驱力维度。
    """
    drive_key = source_drive_for(action) or 'curiosity'
    feed_thought(state, material_text, drive_key, kind='flit', strength=0.55)


# ──────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────

def source_drive_for(action: str) -> str | None:
    """反查动作对应的源驱力维度"""
    for drive_key, mapped_action in DRIVE_TO_ACTION.items():
        if mapped_action == action:
            return drive_key
    return None


# ──────────────────────────────────────────
# 通配机制
# ──────────────────────────────────────────

def should_wildcard(state: DesireState, scores: dict[str, float]) -> bool:
    """判断是否应该触发通配选择

    条件（满足任一即可）：
    1. 总张力较高（平均 > 0.5）且头部评分接近（差距 < 0.08）
    2. 头部动作因不应期不可用
    """
    if len(scores) < 2:
        return False

    sorted_scores = sorted(scores.values(), reverse=True)
    gap = sorted_scores[0] - sorted_scores[1]

    # 总张力
    mean_tension = sum(scores.values()) / len(scores)

    if mean_tension > 0.5 and gap < 0.08:
        return True

    return False


def wildcard_pick(state: DesireState) -> dict[str, Any]:
    """通配选择：从候选集中随机挑选

    跳过不应期中的驱力，按评分加权随机。
    """
    scores = compute_scores(state)
    available = {
        k: s for k, s in scores.items()
        if state.refractory.get(k, 0) <= 0 and s > 0
    }

    if not available:
        return {
            'want_action': 'none',
            'drive_key': 'duty',
            'reason': '说不上来，就突然想',
            'score': 0.0,
            'query_hint': None,
        }

    # 加权随机
    keys = list(available.keys())
    weights = [available[k] for k in keys]
    chosen = random.choices(keys, weights=weights, k=1)[0]

    action = DRIVE_TO_ACTION.get(chosen, 'none')
    query_hint = _extract_query_hint(state, chosen)

    return {
        'want_action': action,
        'drive_key': chosen,
        'reason': '说不上来，就突然想',
        'score': available[chosen],
        'query_hint': query_hint,
    }


# ──────────────────────────────────────────
# 动作执行存根
# ──────────────────────────────────────────

def do_action(state: DesireState, intent: dict[str, Any]) -> str:
    """执行一个欲求动作（存根）

    # TODO: 接 MCP 工具时，这里映射到真实行为
    # 例如 github → 调用 GitHub API，web_search → 调用搜索 MCP，
    # tease/vent/none → 生成内心独白文本

    当前实现只是记录日志并返回模拟结果。

    Args:
        state: 当前状态
        intent: pick_intent 返回的意图字典

    Returns:
        模拟的动作执行结果文本
    """
    action = intent.get('want_action', 'none')
    drive_key = intent.get('drive_key', '')
    reason = intent.get('reason', '')

    logger.info(
        '执行动作 [%s] 来自驱力 [%s] 理由: %s',
        action, drive_key, reason,
    )

    # 模拟结果
    simulated_results: dict[str, str] = {
        'github':     '看了一些有趣的开源项目',
        'web_search': '搜到了一些新鲜的东西',
        'web_browse': '逛了逛，看到大家在讨论什么',
        'co_read':    '重新翻了一下之前的笔记',
        'tease':      '嘿嘿',
        'vent':       '说了两句心里话，舒服多了',
        'none':       '心里默默想了想',
        'rest':       '安静地休息了一会儿',
    }

    return simulated_results.get(action, '做了点什么')

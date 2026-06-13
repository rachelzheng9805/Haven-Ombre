from __future__ import annotations

"""test_desire.py — 欲望系统综合测试

覆盖 18 个测试用例，验证递减收益、念头池、疲劳门控、
满足回滚、不应期、耦合网络、心跳节奏、通配机制、自驱等。

运行方式: python3 -m pytest test_desire.py -v
"""

import math
import os
import random

import pytest

# 确保测试时所有 gate 默认关闭
os.environ.pop('DESIRE_DRIVEN', None)
os.environ.pop('DESIRE_COUPLING', None)
os.environ.pop('DESIRE_BASELINE_DRIFT', None)
os.environ.pop('HEARTBEAT_AUTONOMY', None)
os.environ.pop('DESIRE_SELF_DRIVE', None)

from config import (
    DRIVE_KEYS, FLIT_DECAY, FLIT_TO_FIXATION, FIXATION_FEED,
    FIXATION_FEED_GAIN, FIXATION_RESOLVE_FEEDS, DROP_BELOW,
    FATIGUE_REST_GATE, REFRACTORY_TICKS, DRIVE_TO_ACTION,
    FREQ_DISCOUNT_WINDOW, FREQ_DISCOUNT_FACTOR,
)
from state import DesireState, Thought, clamp_drives
from desire import (
    diminishing_gain, freq_discount, pulse_drive, tick_thoughts,
    compute_scores, pick_intent, satisfy, tick_refractory,
    feed_thought, autofeed_voice_thought, autofeed_action_thought,
    source_drive_for, should_wildcard, wildcard_pick, do_action,
)
from coupling import apply_coupling
from heartbeat import compute_tension, compute_heartbeat_interval, full_tick
from self_drive import apply_self_drive, curiosity_self_grow


def _fresh_state(**overrides: float) -> DesireState:
    """创建一个干净的测试状态，可选覆盖特定驱力值"""
    state = DesireState()
    for k, v in overrides.items():
        if k in state.drive:
            state.drive[k] = v
    return state


# ──────────────────────────────────────────
# 1. 递减收益
# ──────────────────────────────────────────

class TestDiminishingGain:
    """递减收益：越接近 1，增益越小"""

    def test_diminishing_gain_basic(self):
        """低位时增益接近原始值，高位时增益明显减少"""
        gain_low = diminishing_gain(0.1, 0.2)
        gain_high = diminishing_gain(0.9, 0.2)
        assert gain_low > gain_high
        # 在 current=0 时，gain 应等于 raw_delta
        assert abs(diminishing_gain(0.0, 0.5) - 0.5) < 1e-9

    def test_diminishing_gain_at_max(self):
        """current=1 时增益为 0"""
        assert diminishing_gain(1.0, 0.5) == 0.0

    def test_diminishing_gain_formula(self):
        """验证公式 gain = raw_delta * sqrt(1 - current)"""
        current, delta = 0.36, 0.25
        expected = delta * math.sqrt(1.0 - current)
        assert abs(diminishing_gain(current, delta) - expected) < 1e-9


# ──────────────────────────────────────────
# 2. 驱力脉冲夹值
# ──────────────────────────────────────────

class TestPulseDrive:
    """驱力脉冲永远不会超过 [0, 1]"""

    def test_pulse_drive_clamps_upper(self):
        """大量正脉冲不会超过 1.0"""
        state = _fresh_state(curiosity=0.95)
        pulse_drive(state, 'curiosity', 10.0)
        assert state.drive['curiosity'] <= 1.0

    def test_pulse_drive_clamps_lower(self):
        """大量负脉冲不会低于 0.0"""
        state = _fresh_state(curiosity=0.05)
        pulse_drive(state, 'curiosity', -10.0)
        assert state.drive['curiosity'] >= 0.0

    def test_pulse_drive_invalid_key(self):
        """无效的驱力 key 不报错，返回 0"""
        state = _fresh_state()
        actual = pulse_drive(state, 'nonexistent', 0.5)
        assert actual == 0.0


# ──────────────────────────────────────────
# 3. 闪念衰减
# ──────────────────────────────────────────

class TestFlitDecay:
    """闪念每 tick 应该衰减"""

    def test_flit_decays(self):
        """一个 tick 后闪念强度 = 原始 * FLIT_DECAY"""
        state = _fresh_state()
        state.thoughts = [Thought(text='测试闪念', drive='curiosity', kind='flit', strength=0.5)]
        tick_thoughts(state)
        assert abs(state.thoughts[0].strength - 0.5 * FLIT_DECAY) < 1e-9

    def test_flit_drops_below_threshold(self):
        """强度过低的闪念被丢弃"""
        state = _fresh_state()
        state.thoughts = [Thought(text='微弱闪念', drive='curiosity', kind='flit', strength=DROP_BELOW - 0.01)]
        tick_thoughts(state)
        assert len(state.thoughts) == 0


# ──────────────────────────────────────────
# 4. 闪念升格为执念
# ──────────────────────────────────────────

class TestFlitUpgrade:
    """闪念强度达到阈值后升格为执念"""

    def test_flit_upgrades_to_fixation(self):
        """strength >= FLIT_TO_FIXATION 时，kind 变为 fixation"""
        state = _fresh_state()
        # 设置一个衰减后仍然 >= 阈值的强度
        # 衰减后: strength * FLIT_DECAY >= FLIT_TO_FIXATION
        # strength >= FLIT_TO_FIXATION / FLIT_DECAY
        initial = FLIT_TO_FIXATION / FLIT_DECAY + 0.01
        state.thoughts = [Thought(text='强闪念', drive='curiosity', kind='flit', strength=initial)]
        tick_thoughts(state)
        assert state.thoughts[0].kind == 'fixation'


# ──────────────────────────────────────────
# 5. 执念反哺驱力
# ──────────────────────────────────────────

class TestFixationFeedsDrive:
    """执念强度超过反哺阈值时会给驱力加量"""

    def test_fixation_feeds_drive(self):
        """执念 strength >= FIXATION_FEED 时，关联驱力增加"""
        state = _fresh_state(curiosity=0.3)
        state.thoughts = [Thought(
            text='执念测试', drive='curiosity', kind='fixation',
            strength=FIXATION_FEED + 0.05,
        )]
        old_val = state.drive['curiosity']
        tick_thoughts(state)
        assert state.drive['curiosity'] > old_val


# ──────────────────────────────────────────
# 6. 执念消解
# ──────────────────────────────────────────

class TestFixationResolves:
    """执念反哺次数达标后消解"""

    def test_fixation_resolves(self):
        """fed_count >= FIXATION_RESOLVE_FEEDS 时执念被移除"""
        state = _fresh_state()
        state.thoughts = [Thought(
            text='即将消解', drive='curiosity', kind='fixation',
            strength=0.95,  # 足够高，会反哺
            fed_count=FIXATION_RESOLVE_FEEDS - 1,
        )]
        tick_thoughts(state)
        # 反哺一次后 fed_count = FIXATION_RESOLVE_FEEDS，应该被移除
        assert len(state.thoughts) == 0


# ──────────────────────────────────────────
# 7. 疲劳门控
# ──────────────────────────────────────────

class TestFatigueGate:
    """疲劳超过阈值时返回休息意图"""

    def test_fatigue_gate(self):
        """fatigue >= FATIGUE_REST_GATE → want_action == 'rest'"""
        state = _fresh_state(fatigue=FATIGUE_REST_GATE + 0.01)
        intent = pick_intent(state)
        assert intent['want_action'] == 'rest'
        assert intent['drive_key'] == 'fatigue'

    def test_no_fatigue_gate(self):
        """fatigue < FATIGUE_REST_GATE → 正常意图"""
        state = _fresh_state(fatigue=0.1)
        intent = pick_intent(state)
        assert intent['want_action'] != 'rest'


# ──────────────────────────────────────────
# 8. 满足回滚
# ──────────────────────────────────────────

class TestSatisfyRollback:
    """满足后对应驱力值下降"""

    def test_satisfy_rollback(self):
        """执行 tease 后 libido 和 attachment 都下降"""
        state = _fresh_state(libido=0.8, attachment=0.8)
        old_libido = state.drive['libido']
        old_attach = state.drive['attachment']
        satisfy(state, 'tease')
        assert state.drive['libido'] < old_libido
        assert state.drive['attachment'] < old_attach
        # 验证乘数
        assert abs(state.drive['libido'] - old_libido * 0.55) < 1e-9
        assert abs(state.drive['attachment'] - old_attach * 0.78) < 1e-9


# ──────────────────────────────────────────
# 9. 不应期
# ──────────────────────────────────────────

class TestRefractory:
    """不应期内的驱力不会被选中"""

    def test_refractory(self):
        """最高驱力在不应期时不被选中"""
        state = _fresh_state(curiosity=0.9, attachment=0.5)
        # 其他驱力都低
        for k in DRIVE_KEYS:
            if k not in ('curiosity', 'attachment', 'fatigue'):
                state.drive[k] = 0.1
        state.refractory['curiosity'] = REFRACTORY_TICKS

        intent = pick_intent(state)
        assert intent['drive_key'] != 'curiosity'

    def test_tick_refractory_decrements(self):
        """tick_refractory 正确递减并清理归零项"""
        state = _fresh_state()
        state.refractory = {'curiosity': 2, 'libido': 1}
        tick_refractory(state)
        assert state.refractory['curiosity'] == 1
        assert 'libido' not in state.refractory


# ──────────────────────────────────────────
# 10. 耦合网络有界性
# ──────────────────────────────────────────

class TestCouplingBounded:
    """随机初始化 200 ticks，所有驱力始终在 [0, 1]"""

    def test_coupling_bounded(self):
        """200 轮耦合后所有驱力仍在合法范围"""
        state = _fresh_state()
        rng = random.Random(42)
        for k in DRIVE_KEYS:
            state.drive[k] = rng.random()
            state.prev_drive[k] = rng.random()

        for _ in range(200):
            apply_coupling(state)
            for k in DRIVE_KEYS:
                assert 0.0 <= state.drive[k] <= 1.0, \
                    f'{k} = {state.drive[k]} 越界！'


# ──────────────────────────────────────────
# 11. 耦合 level 模式
# ──────────────────────────────────────────

class TestCouplingLevel:
    """stress 高时 curiosity 应该下降"""

    def test_coupling_level(self):
        """stress 高 → curiosity 受到负压"""
        state = _fresh_state(stress=0.8, curiosity=0.5)
        # 设置 prev_drive 与 drive 一致（排除 delta 干扰）
        state.prev_drive = dict(state.drive)
        apply_coupling(state)
        # stress -> curiosity 系数 -0.03 (level)
        # 加上阻尼效应，curiosity 应该比 0.5 低
        assert state.drive['curiosity'] < 0.5


# ──────────────────────────────────────────
# 12. 耦合 delta 模式
# ──────────────────────────────────────────

class TestCouplingDelta:
    """attachment 上升时 libido 应该上升"""

    def test_coupling_delta(self):
        """attachment 上升 → libido 跟着涨"""
        state = _fresh_state(attachment=0.6, libido=0.3)
        # prev 低于 current → 有上升
        state.prev_drive = dict(state.drive)
        state.prev_drive['attachment'] = 0.3  # 上升了 0.3
        old_libido = state.drive['libido']
        apply_coupling(state)
        # attachment->libido delta 0.05, rise=0.3, effect=0.015
        assert state.drive['libido'] > old_libido


# ──────────────────────────────────────────
# 13. 心跳间隔
# ──────────────────────────────────────────

class TestHeartbeatInterval:
    """高张力 → 更短的心跳间隔"""

    def test_heartbeat_interval(self):
        """高张力状态的间隔比低张力状态短"""
        state_high = _fresh_state()
        for k in DRIVE_KEYS:
            if k != 'fatigue':
                state_high.drive[k] = 0.8

        state_low = _fresh_state()
        for k in DRIVE_KEYS:
            state_low.drive[k] = 0.1

        interval_high = compute_heartbeat_interval(state_high)
        interval_low = compute_heartbeat_interval(state_low)
        assert interval_high < interval_low


# ──────────────────────────────────────────
# 14. 通配触发
# ──────────────────────────────────────────

class TestWildcard:
    """头部评分接近且张力高时触发通配"""

    def test_wildcard_triggers(self):
        """两个维度评分非常接近 + 平均张力 > 0.5 → 触发"""
        state = _fresh_state()
        scores = {'curiosity': 0.7, 'social': 0.695, 'reflection': 0.3}
        assert should_wildcard(state, scores) is True

    def test_wildcard_no_trigger(self):
        """评分差距大 → 不触发"""
        state = _fresh_state()
        scores = {'curiosity': 0.9, 'social': 0.3, 'reflection': 0.2}
        assert should_wildcard(state, scores) is False


# ──────────────────────────────────────────
# 15. 自驱好奇心地板
# ──────────────────────────────────────────

class TestSelfDriveCuriosityFloor:
    """好奇心不低于自驱地板"""

    def test_self_drive_curiosity_floor(self):
        """应用自驱后，curiosity 不低于 floor"""
        state = _fresh_state(curiosity=0.05)
        state.curiosity_self_floor = 0.0
        # 多次增长地板
        for _ in range(50):
            apply_self_drive(state)
        assert state.curiosity_self_floor > 0.0
        assert state.drive['curiosity'] >= state.curiosity_self_floor


# ──────────────────────────────────────────
# 16. 频率折扣
# ──────────────────────────────────────────

class TestFreqDiscount:
    """同类刺激重复出现有折扣"""

    def test_freq_discount(self):
        """近期有同类动作 → 折扣系数 < 1"""
        state = _fresh_state()
        state.tick_count = 10
        state.last_actions = [('github', 9)]  # 1 tick 前
        discount = freq_discount('github', state)
        assert discount == FREQ_DISCOUNT_FACTOR

    def test_freq_discount_none(self):
        """没有近期同类动作 → 无折扣"""
        state = _fresh_state()
        state.tick_count = 10
        state.last_actions = [('github', 2)]  # 太久以前
        discount = freq_discount('github', state)
        assert discount == 1.0


# ──────────────────────────────────────────
# 17. 反查动作源驱力
# ──────────────────────────────────────────

class TestSourceDriveFor:
    """source_drive_for 能正确反查"""

    def test_source_drive_for(self):
        """已知映射的反查"""
        assert source_drive_for('github') == 'curiosity'
        assert source_drive_for('tease') == 'libido'
        assert source_drive_for('vent') == 'stress'
        assert source_drive_for('co_read') == 'reflection'

    def test_source_drive_for_unknown(self):
        """未知动作返回 None"""
        assert source_drive_for('unknown_action') is None


# ──────────────────────────────────────────
# 18. 完整 tick 集成测试
# ──────────────────────────────────────────

class TestFullTickIntegration:
    """full_tick 能完整运行且状态有变化"""

    def test_full_tick_integration(self, tmp_path):
        """完整 tick 不报错，tick_count 递增"""
        state = _fresh_state(curiosity=0.6, stress=0.4)
        feed_thought(state, '集成测试念头', 'curiosity', 'flit', 0.7)
        state_path = str(tmp_path / 'test_state.json')

        old_tick = state.tick_count
        summary = full_tick(state, state_path)

        assert state.tick_count == old_tick + 1
        assert 'tick' in summary
        assert 'tension' in summary
        assert 'intent' in summary
        assert 'heartbeat_interval' in summary
        assert summary['tick'] == state.tick_count

    def test_full_tick_saves_state(self, tmp_path):
        """full_tick 后状态文件存在"""
        state = _fresh_state()
        state_path = str(tmp_path / 'test_state.json')
        full_tick(state, state_path)
        assert os.path.exists(state_path)


# ──────────────────────────────────────────
# 19. freq_discount 集成到 compute_scores
# ──────────────────────────────────────────

class TestFreqDiscountInScores:
    """频率折扣应该降低同类动作重复做时的评分"""

    def test_freq_discount_lowers_score(self):
        """近期做过 github → curiosity 评分被打折"""
        state = _fresh_state(curiosity=0.6)
        # 没有近期动作
        score_before = compute_scores(state)['curiosity']
        # 加入近期 github 动作
        state.tick_count = 5
        state.last_actions = [('github', 4)]
        score_after = compute_scores(state)['curiosity']
        assert score_after < score_before
        assert abs(score_after - score_before * FREQ_DISCOUNT_FACTOR) < 1e-9


# ──────────────────────────────────────────
# 20. feed_thought 叠加而非取 max
# ──────────────────────────────────────────

class TestFeedThoughtAdditive:
    """同一条念头再喂应该叠加强化，不是取 max"""

    def test_feed_thought_additive(self):
        """重复喂同一条念头，强度应该增加"""
        state = _fresh_state()
        feed_thought(state, '反复出现的念头', 'curiosity', 'flit', 0.4)
        s1 = state.thoughts[0].strength
        feed_thought(state, '反复出现的念头', 'curiosity', 'flit', 0.4)
        s2 = state.thoughts[0].strength
        assert s2 > s1, '重复喂入应叠加增强'
        assert s2 <= 1.0

    def test_feed_thought_additive_capped(self):
        """叠加后不超过 1.0"""
        state = _fresh_state()
        feed_thought(state, '强念头', 'curiosity', 'flit', 0.9)
        for _ in range(20):
            feed_thought(state, '强念头', 'curiosity', 'flit', 0.9)
        assert state.thoughts[0].strength <= 1.0


# ──────────────────────────────────────────
# 21. curiosity 按关键词分流
# ──────────────────────────────────────────

class TestCuriosityDispatch:
    """curiosity 按念头关键词分流到 github 或 web_search"""

    def test_curiosity_routes_to_web_search(self):
        """念头含搜索关键词 → web_search"""
        state = _fresh_state(curiosity=0.9)
        for k in DRIVE_KEYS:
            if k not in ('curiosity', 'fatigue'):
                state.drive[k] = 0.1
        feed_thought(state, '量子计算是什么', 'curiosity', 'flit', 0.7)
        intent = pick_intent(state)
        assert intent['drive_key'] == 'curiosity'
        assert intent['want_action'] == 'web_search'

    def test_curiosity_routes_to_github(self):
        """念头不含搜索关键词 → github"""
        state = _fresh_state(curiosity=0.9)
        for k in DRIVE_KEYS:
            if k not in ('curiosity', 'fatigue'):
                state.drive[k] = 0.1
        feed_thought(state, '那个 Rust 项目挺有意思', 'curiosity', 'flit', 0.7)
        intent = pick_intent(state)
        assert intent['drive_key'] == 'curiosity'
        assert intent['want_action'] == 'github'

    def test_curiosity_no_hint_defaults_github(self):
        """无相关念头 → 默认 github"""
        state = _fresh_state(curiosity=0.9)
        for k in DRIVE_KEYS:
            if k not in ('curiosity', 'fatigue'):
                state.drive[k] = 0.1
        intent = pick_intent(state)
        assert intent['want_action'] == 'github'

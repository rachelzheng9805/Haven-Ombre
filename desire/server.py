from __future__ import annotations

"""server.py — FastAPI 服务器

提供 REST API 和静态文件服务。
端口 8765，支持 CORS。
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from config import gate, GATE_HEARTBEAT_AUTONOMY
from state import DesireState, load_state, save_state
from desire import (
    feed_thought, satisfy as desire_satisfy, pulse_drive,
    compute_scores, pick_intent,
)
from heartbeat import full_tick, compute_heartbeat_interval
from config import (
    GATE_DESIRE_DRIVEN, GATE_COUPLING, GATE_BASELINE_DRIFT,
    GATE_SELF_DRIVE,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# 全局状态（进程内单例）
# ──────────────────────────────────────────
_state: DesireState | None = None
_heartbeat_task: asyncio.Task[None] | None = None

STATIC_DIR = os.path.dirname(__file__)
DATA_PATH = os.path.join(STATIC_DIR, 'data', 'desire_thoughts.json')


def _get_state() -> DesireState:
    """获取全局状态，惰性初始化"""
    global _state
    if _state is None:
        _state = load_state(DATA_PATH)
    return _state


# ──────────────────────────────────────────
# 心跳后台任务
# ──────────────────────────────────────────

async def _heartbeat_loop() -> None:
    """心跳循环：按动态间隔反复执行 full_tick"""
    while True:
        try:
            state = _get_state()
            interval = compute_heartbeat_interval(state)
            await asyncio.sleep(interval)
            if gate(GATE_HEARTBEAT_AUTONOMY):
                full_tick(state, DATA_PATH)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception('心跳循环异常')
            await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时加载状态，启动心跳循环"""
    global _state, _heartbeat_task
    _state = load_state(DATA_PATH)
    logger.info('状态已加载，tick=%d', _state.tick_count)

    # 启动心跳后台任务
    _heartbeat_task = asyncio.create_task(_heartbeat_loop())

    yield

    # 关闭心跳
    if _heartbeat_task:
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass

    # 保存状态
    if _state:
        save_state(_state, DATA_PATH)
        logger.info('状态已保存')


# ──────────────────────────────────────────
# FastAPI 应用
# ──────────────────────────────────────────

app = FastAPI(
    title='Desire System',
    description='AI 欲望/驱力系统 API',
    version='0.1.0',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


# ──────────────────────────────────────────
# 静态文件
# ──────────────────────────────────────────

@app.get('/')
async def serve_index():
    """返回 index.html"""
    path = os.path.join(STATIC_DIR, 'index.html')
    if os.path.exists(path):
        return FileResponse(path, media_type='text/html')
    return JSONResponse({'error': 'index.html not found'}, status_code=404)


@app.get('/index.css')
async def serve_css():
    """返回 index.css"""
    path = os.path.join(STATIC_DIR, 'index.css')
    if os.path.exists(path):
        return FileResponse(path, media_type='text/css')
    return JSONResponse({'error': 'index.css not found'}, status_code=404)


@app.get('/index.js')
async def serve_js():
    """返回 index.js"""
    path = os.path.join(STATIC_DIR, 'index.js')
    if os.path.exists(path):
        return FileResponse(path, media_type='application/javascript')
    return JSONResponse({'error': 'index.js not found'}, status_code=404)


# ──────────────────────────────────────────
# API 路由
# ──────────────────────────────────────────

@app.get('/api/desire/state')
async def get_state():
    """获取完整状态"""
    state = _get_state()
    scores = compute_scores(state)
    intent = pick_intent(state)
    interval = compute_heartbeat_interval(state)
    return {
        'drive': state.drive,
        'scores': scores,
        'intent': intent,
        'thoughts': [t.to_dict() for t in state.thoughts],
        'thought_count': len(state.thoughts),
        'refractory': state.refractory,
        'tick_count': state.tick_count,
        'heartbeat_interval': round(interval, 1),
        'self_drive': {
            'enabled': gate(GATE_SELF_DRIVE),
            'curiosity_self_floor': round(state.curiosity_self_floor, 4),
            'today_self_actions': state.self_drive_stats.get('today_self_actions', 0),
            'last_self_pulse': state.self_drive_stats.get('last_self_pulse'),
        },
        'gates': {
            GATE_DESIRE_DRIVEN: gate(GATE_DESIRE_DRIVEN),
            GATE_COUPLING: gate(GATE_COUPLING),
            GATE_BASELINE_DRIFT: gate(GATE_BASELINE_DRIFT),
            GATE_HEARTBEAT_AUTONOMY: gate(GATE_HEARTBEAT_AUTONOMY),
            GATE_SELF_DRIVE: gate(GATE_SELF_DRIVE),
        },
    }


class FeedRequest(BaseModel):
    text: str
    drive: str
    kind: str = 'flit'
    strength: float = 0.6


@app.post('/api/desire/feed')
async def api_feed(req: FeedRequest):
    """喂入一条念头"""
    state = _get_state()
    feed_thought(state, req.text, req.drive, req.kind, req.strength)
    save_state(state, DATA_PATH)
    return {'ok': True, 'thought_count': len(state.thoughts)}


@app.post('/api/desire/tick')
async def api_tick():
    """手动执行一个 tick"""
    state = _get_state()
    summary = full_tick(state, DATA_PATH)
    return summary


class SatisfyRequest(BaseModel):
    action: str


@app.post('/api/desire/satisfy')
async def api_satisfy(req: SatisfyRequest):
    """手动执行满足回滚"""
    state = _get_state()
    desire_satisfy(state, req.action)
    save_state(state, DATA_PATH)
    return {'ok': True, 'drive': state.drive}


class PulseRequest(BaseModel):
    drive: str
    delta: float


@app.post('/api/desire/pulse')
async def api_pulse(req: PulseRequest):
    """手动脉冲某个驱力"""
    state = _get_state()
    actual = pulse_drive(state, req.drive, req.delta)
    save_state(state, DATA_PATH)
    return {'ok': True, 'drive': req.drive, 'actual_delta': round(actual, 4), 'new_value': round(state.drive.get(req.drive, 0.0), 4)}


class GateRequest(BaseModel):
    gate_name: str
    enabled: bool


@app.post('/api/desire/gate')
async def api_gate(req: GateRequest):
    """切换环境变量开关"""
    value = '1' if req.enabled else ''
    os.environ[req.gate_name] = value
    return {'ok': True, 'gate': req.gate_name, 'enabled': req.enabled}


# ──────────────────────────────────────────
# 入口
# ──────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(
        'server:app',
        host='0.0.0.0',
        port=8765,
        reload=True,
        log_level='info',
    )

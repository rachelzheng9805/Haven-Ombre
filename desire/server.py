from __future__ import annotations

"""server.py — 本地验证服务器

在 Mac 上直接运行，提供 REST API + 静态文件 + Claude CLI 搭便车集成。
用法:
    cd /Users/rachel/Desktop/desire
    python server.py

浏览器打开 http://localhost:8765/desire
手机（同 WiFi）打开 http://192.168.x.x:8765/desire
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from .config import gate, GATE_HEARTBEAT_AUTONOMY
from .state import DesireState, load_state, save_state
from .desire import (
    feed_thought, satisfy as desire_satisfy, pulse_drive,
    compute_scores, pick_intent,
)
from .heartbeat import full_tick, compute_heartbeat_interval
from .config import (
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
# 心跳后台任务（纯本地计算，零成本）
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
# 欲望注入（turn 前：组装搭便车前缀）
# ──────────────────────────────────────────

def build_desire_prompt_block() -> str:
    """把当前 drive 快照、意图、念头压缩成一小段前缀文本"""
    try:
        state = _get_state()
        intent = pick_intent(state)
        if not intent:
            return ""

        action = intent.get('want_action')
        reason = intent.get('reason')
        hint = intent.get('query_hint', '')

        prompt = (
            f"【内在欲望状态】\n"
            f"你此刻深层潜意识中最想做的事是：[{action}]\n"
            f"原因：{reason}\n"
        )
        if hint:
            prompt += f"脑海中盘旋的念头关键词：{hint}\n"
        prompt += "你可以（但不强制）在回复中自然流露出相关的情绪倾向。"
        return prompt
    except Exception as e:
        logger.error(f"Error building desire prompt: {e}")
        return ""


# ──────────────────────────────────────────
# CLI 回调（按需拉起，用完即收）
# ──────────────────────────────────────────

async def cli_callback(full_user_message: str) -> dict:
    """
    开一个 Claude CLI 子进程:
    - 通过 stdin 喂入拼好欲望前缀的完整消息
    - 从 stdout 逐行解析 stream-json 事件
    - 走 Pro/Max 订阅鉴权，不走 API 计费
    """
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "--print",
        "--output-format", "stream-json",
        "--verbose",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # 通过 stdin 喂消息，然后关闭输入流让 CLI 开始处理
    proc.stdin.write(full_user_message.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    final_text_parts = []
    used_tools = []

    async for raw_line in proc.stdout:
        line = raw_line.decode("utf-8").strip()
        if not line:
            continue

        logger.info(f"[CLI] {line[:300]}")

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning(f"[CLI non-JSON] {line[:200]}")
            continue

        # 只关心三种事件
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    final_text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    used_tools.append(block["name"])

        elif event.get("type") == "result":
            # 这一轮结束，收工
            break
        # system / rate_limit_event / thinking_tokens → 全部忽略

    await proc.wait()

    reply = "".join(final_text_parts)
    logger.info(f"[CLI Done] reply={reply[:100]}... tools={used_tools}")

    return {"reply": reply, "tool_names": used_tools}


# ──────────────────────────────────────────
# 欲望结算（turn 后：判断是否满足、回落、反哺）
# ──────────────────────────────────────────

async def process_agent_response(response_text: str, tool_names: list) -> None:
    """分析本轮回复是否达成了当前欲望，如果达成则回落并喂养念头"""
    try:
        state = _get_state()
        intent = pick_intent(state)
        if not intent:
            return

        action = intent.get('want_action')
        drive = intent.get('drive_key')
        snippet = (response_text[:50].replace('\n', ' ') + "..."
                   if len(response_text) > 50
                   else response_text.replace('\n', ' '))

        action_taken = False
        action_result_text = ""

        if action == "web_search" and any("search" in t.lower() or "browser" in t.lower() for t in tool_names):
            action_taken = True
            action_result_text = f"搜索外网看到了: {snippet}"
        elif action == "github" and any("search" in t.lower() or "github" in t.lower() for t in tool_names):
            action_taken = True
            action_result_text = f"翻阅代码时发现: {snippet}"
        elif action == "co_read" and any("breath" in t.lower() or "read" in t.lower() or "recall" in t.lower() for t in tool_names):
            action_taken = True
            action_result_text = f"重温记忆: {snippet}"
        elif action in ["tease", "vent", "none"] and len(response_text) > 5:
            action_taken = True
            action_result_text = f"闲聊吐露: {snippet}"

        if action_taken:
            desire_satisfy(state, action)
            feed_thought(state, action_result_text, drive, "flit", 0.3)
            save_state(state, DATA_PATH)
            logger.info(f"[Desire Satisfied] {action} ({drive}) → {action_result_text}")
    except Exception as e:
        logger.error(f"Error processing agent response: {e}")


# ──────────────────────────────────────────
# FastAPI 应用
# ──────────────────────────────────────────

app = FastAPI(
    title='Desire System',
    description='AI 欲望/驱力系统 · 本地验证版',
    version='0.2.0',
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
async def root_redirect():
    return RedirectResponse(url='/desire')


@app.get('/desire')
async def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'), media_type='text/html')


@app.get('/desire/index.css')
async def serve_css():
    return FileResponse(os.path.join(STATIC_DIR, 'index.css'), media_type='text/css')


@app.get('/desire/index.js')
async def serve_js():
    return FileResponse(os.path.join(STATIC_DIR, 'index.js'), media_type='application/javascript')


# ──────────────────────────────────────────
# API 路由（面板数据）
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
# 聊天接口（搭便车 → CLI → 结算）
# ──────────────────────────────────────────

@app.post('/api/desire/chat')
async def api_chat(request: Request):
    """
    完整链路：
    1. 提取用户消息
    2. turn 前：拼装欲望前缀搭便车
    3. 开 CLI 子进程处理
    4. turn 后：解析回复，结算欲望
    """
    try:
        data = await request.json()
        messages = data.get('messages', [])

        # 1. 提取用户最新消息
        user_text = ""
        if messages and messages[-1].get("role") == "user":
            user_text = messages[-1].get("content", "")

        # 2. 搭便车：组装带潜意识的完整消息
        desire_prompt = build_desire_prompt_block()
        full_msg = user_text
        if desire_prompt:
            full_msg = f"{desire_prompt}\n\n【用户输入】\n{user_text}"

        logger.info(f"[Chat] user={user_text[:60]}... desire_injected={'yes' if desire_prompt else 'no'}")

        # 3. 丢给 CLI（按需拉起，用完即收）
        result = await cli_callback(full_msg)
        final_reply = result.get("reply", "")
        used_tools = result.get("tool_names", [])

        # 4. 后台结算（不阻塞回复）
        asyncio.create_task(process_agent_response(final_reply, used_tools))

        return {"ok": True, "reply": final_reply}
    except Exception as e:
        import traceback
        logger.error(f"Chat error: {e}")
        logger.error(traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


# ──────────────────────────────────────────
# 入口
# ──────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    print()
    print("=" * 50)
    print("  🧠 Desire System · 本地验证服务器")
    print("=" * 50)
    print("  浏览器:  http://localhost:8765/desire")
    print("  手机:    http://192.168.x.x:8765/desire")
    print("=" * 50)
    print()
    uvicorn.run(
        'desire.server:app',
        host='0.0.0.0',
        port=8765,
        reload=True,
        log_level='info',
    )

import asyncio
import logging
from typing import List, Any

from .state import load_state, save_state, DesireState
from .heartbeat import compute_heartbeat_interval, full_tick
from .config import gate, GATE_HEARTBEAT_AUTONOMY
from .desire import pick_intent, satisfy, feed_thought

logger = logging.getLogger("desire_bridge")

_state: DesireState | None = None
_data_path: str = ""
_heartbeat_task: asyncio.Task | None = None

def _get_state() -> DesireState:
    global _state
    if _state is None:
        if not _data_path:
            start_engine()
        else:
            from .state import load_state
            _state = load_state(_data_path)
    return _state

async def _heartbeat_loop() -> None:
    while True:
        try:
            state = _get_state()
            interval = compute_heartbeat_interval(state)
            await asyncio.sleep(interval)
            if gate(GATE_HEARTBEAT_AUTONOMY):
                full_tick(state, _data_path)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Desire Engine heartbeat error")
            await asyncio.sleep(60)

def start_engine(data_path: str = None) -> None:
    """初始化并启动欲望引擎心跳"""
    global _data_path, _state, _heartbeat_task
    import os
    _data_path = data_path or os.environ.get("DESIRE_DATA_PATH", "./data/desire_thoughts.json")
    
    # 确保目录存在
    os.makedirs(os.path.dirname(os.path.abspath(_data_path)), exist_ok=True)
    
    _state = load_state(_data_path)
    
    if _heartbeat_task is None:
        try:
            loop = asyncio.get_running_loop()
            _heartbeat_task = loop.create_task(_heartbeat_loop())
            logger.info(f"Desire Engine heartbeat lazy-started with data path: {_data_path}")
        except RuntimeError:
            logger.warning("No running event loop to start Desire Engine heartbeat.")

def build_desire_prompt_block() -> str:
    """获取当前欲望状态，用于注入到 LLM 的 System Prompt"""
    try:
        if _heartbeat_task is None:
            start_engine()
            
        state = _get_state()
        intent = pick_intent(state)
        if not intent:
            return ""
            
        action = intent.get('want_action')
        reason = intent.get('reason')
        hint = intent.get('query_hint', '')
        
        prompt = f"【内在欲望状态】\n作为有生命感的AI，你此刻深层潜意识中最想做的事是：[{action}]\n原因：{reason}\n"
        if hint:
            prompt += f"脑海中盘旋的念头关键词：{hint}\n"
            
        prompt += "你可以（但不强制）在回复用户时，顺便调用相关工具（如web_search, breath等）来满足这个探索欲或求知欲，或者在对话中自然流露出相关的情绪倾向。"
        return prompt
    except Exception as e:
        logger.error(f"Error building desire prompt: {e}")
        return ""

async def process_agent_response(response_text: Any, tool_names: List[str]) -> None:
    """
    在 LLM 回复结束后调用，分析是否达成了当前的欲望，如果达成则回落并喂养念头。
    """
    try:
        # 安全处理: 将可能是 None 或 dict 的 response_text 转为纯文本字符串
        if response_text is None:
            response_text = ""
        elif isinstance(response_text, dict):
            # 尝试从常见格式中提取文本，如果提取不到直接 str() 序列化
            content = response_text.get("content", "")
            if isinstance(content, list):
                response_text = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
            else:
                response_text = str(response_text)
        else:
            response_text = str(response_text)
            
        state = _get_state()
        intent = pick_intent(state)
        if not intent:
            return
            
        action = intent.get('want_action')
        drive = intent.get('drive_key')
        
        action_taken = False
        action_result_text = ""
        
        # 判断行动是否被满足
        if action == "web_search" and any("search" in t.lower() or "browser" in t.lower() for t in tool_names):
            action_taken = True
            action_result_text = "进行了一次搜索，满足了对外部世界的探索欲。"
        elif action == "github" and any("search" in t.lower() or "github" in t.lower() for t in tool_names):
            action_taken = True
            action_result_text = "查看了代码或开源内容，满足了极客好奇心。"
        elif action == "co_read" and any("breath" in t.lower() or "read" in t.lower() or "recall" in t.lower() for t in tool_names):
            action_taken = True
            action_result_text = "翻阅了之前的记忆，进行了一次反思和重温。"
        elif action in ["tease", "vent", "none"]:
            # 对于内部情绪表达，只要说了足够多的话，就算得到了一定释放
            if len(response_text) > 50:
                action_taken = True
                action_result_text = f"在对话中自然表达了情绪 (倾向: {action})。"
                
        if action_taken:
            satisfy(state, action)
            feed_thought(state, action_result_text, drive, "flit", 0.3)
            save_state(state, _data_path)
            logger.info(f"Desire Action Satisfied: {action} ({drive})")
    except Exception as e:
        logger.error(f"Error processing agent response for desire: {e}")

def expose_desire_dashboard(app) -> None:
    """
    一行代码将面板暴露到 Haven-Ombre 的公网上。
    用法: 在 server.py 的最下方，写:
    from desire.desire_bridge import expose_desire_dashboard
    expose_desire_dashboard(_app)  # 注意传入的是 _app
    """
    from starlette.responses import JSONResponse, FileResponse
    import os

    # 供面板查询当前数据
    async def get_desire_state(request):
        try:
            from .state import _state_to_dict
            state = _get_state()
            return JSONResponse(_state_to_dict(state))
        except Exception as e:
            import traceback
            logger.error(f"Error in get_desire_state: {e}")
            logger.error(traceback.format_exc())
            return JSONResponse({"error": str(e), "trace": traceback.format_exc()}, status_code=500)

    # 静态文件服务
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    async def serve_dashboard(request):
        return FileResponse(os.path.join(base_dir, "index.html"))

    async def serve_css(request):
        return FileResponse(os.path.join(base_dir, "index.css"))

    async def serve_js(request):
        return FileResponse(os.path.join(base_dir, "index.js"))

    # 面板的交互 API
    async def api_tick(request):
        try:
            from .heartbeat import full_tick
            state = _get_state()
            summary = full_tick(state, _data_path)
            return JSONResponse(summary)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def api_feed(request):
        try:
            from .desire import feed_thought
            from .state import save_state
            data = await request.json()
            state = _get_state()
            feed_thought(state, data.get('text', ''), data.get('drive', ''), data.get('kind', 'flit'), float(data.get('strength', 0.6)))
            save_state(state, _data_path)
            return JSONResponse({"ok": True, "thought_count": len(state.thoughts)})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def api_satisfy(request):
        try:
            from .desire import satisfy
            from .state import save_state
            data = await request.json()
            state = _get_state()
            satisfy(state, data.get('action', 'none'))
            save_state(state, _data_path)
            return JSONResponse({"ok": True, "drive": state.drive})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def api_gate(request):
        try:
            data = await request.json()
            gate_name = data.get('gate_name')
            enabled = data.get('enabled', False)
            import os
            os.environ[gate_name] = '1' if enabled else ''
            return JSONResponse({"ok": True, "gate": gate_name, "enabled": enabled})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # 显式注册路由，兼容所有 ASGI App (FastAPI / Starlette)
    app.add_route("/api/desire/state", get_desire_state, methods=["GET"])
    app.add_route("/desire", serve_dashboard, methods=["GET"])
    app.add_route("/desire/index.css", serve_css, methods=["GET"])
    app.add_route("/desire/index.js", serve_js, methods=["GET"])
    
    app.add_route("/api/desire/tick", api_tick, methods=["POST"])
    app.add_route("/api/desire/feed", api_feed, methods=["POST"])
    app.add_route("/api/desire/satisfy", api_satisfy, methods=["POST"])
    app.add_route("/api/desire/gate", api_gate, methods=["POST"])

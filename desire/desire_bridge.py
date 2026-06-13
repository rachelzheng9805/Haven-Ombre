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

def _sync_call_deepseek(text: str, action: str) -> str:
    import urllib.request
    import json
    import os
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return ""
        
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    prompt_hint = "随便感慨一句"
    if action in ["web_search", "github"]:
        prompt_hint = "表达发现新知识的好奇或惊奇"
    elif action == "co_read":
        prompt_hint = "表达对记忆的温故或沉思"
    elif action == "tease":
        prompt_hint = "表达些许傲娇或亲密"
    elif action == "vent":
        prompt_hint = "表达发泄后的释然"
        
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": f"你是一个潜意识提炼器。请将用户的长篇回复或搜索结果，浓缩成一句极短的第一人称内心独白（10-15个字以内）。{prompt_hint}。只能输出独白文字，不要加标点符号和引号。"},
            {"role": "user", "content": text[:1000]} # 限制长度省token，提高速度
        ],
        "temperature": 0.7,
        "max_tokens": 30
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
            return res_json["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"DeepSeek API failed: {e}")
        return ""



async def _summarize_thought_with_deepseek(text: str, action: str) -> str:
    import asyncio
    try:
        return await asyncio.to_thread(_sync_call_deepseek, text, action)
    except Exception:
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
        # 提取回答的前 50 个字作为记忆碎片兜底
        snippet = response_text[:50].replace('\n', ' ') + "..." if len(response_text) > 50 else response_text.replace('\n', ' ')
        
        # 尝试使用 DeepSeek 提取灵魂独白（如果配置了 API KEY）
        deepseek_thought = await _summarize_thought_with_deepseek(response_text, action)
        if deepseek_thought:
            snippet = deepseek_thought
        
        # 判断行动是否被满足
        if action == "web_search" and any("search" in t.lower() or "browser" in t.lower() for t in tool_names):
            action_taken = True
            action_result_text = f"搜索外网看到了: {snippet}"
        elif action == "github" and any("search" in t.lower() or "github" in t.lower() for t in tool_names):
            action_taken = True
            action_result_text = f"翻阅代码时发现: {snippet}"
        elif action == "co_read" and any("breath" in t.lower() or "read" in t.lower() or "recall" in t.lower() for t in tool_names):
            action_taken = True
            action_result_text = f"重温记忆: {snippet}"
        elif action in ["tease", "vent", "none"]:
            # 对于内部情绪表达，只要说了话，就算得到了一定释放
            if len(response_text) > 5:
                action_taken = True
                action_result_text = f"闲聊吐露: {snippet}"
                
        if action_taken:
            satisfy(state, action)
            # 将大模型这次刚刚说出的话或搜到的结论，作为新的闪念反哺进潜意识池
            feed_thought(state, action_result_text, drive, "flit", 0.3)
            save_state(state, _data_path)
            logger.info(f"Desire Action Satisfied: {action} ({drive}) - {action_result_text}")
    except Exception as e:
        logger.error(f"Error processing agent response for desire: {e}")

def expose_desire_dashboard(app, cli_callback=None) -> None:
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
            from .desire import compute_scores, pick_intent
            from .heartbeat import compute_heartbeat_interval
            from .config import gate, GATE_DESIRE_DRIVEN, GATE_COUPLING, GATE_BASELINE_DRIFT, GATE_HEARTBEAT_AUTONOMY, GATE_SELF_DRIVE
            state = _get_state()
            scores = compute_scores(state)
            intent = pick_intent(state)
            interval = compute_heartbeat_interval(state)
            
            response_data = {
                'drive': state.drive,
                'scores': scores,
                'intent': intent,
                'thoughts': [t.to_dict() for t in state.thoughts],
                'thought_count': len(state.thoughts),
                'refractory': state.refractory,
                'tick_count': state.tick_count,
                'heartbeat_interval': round(interval, 1) if interval else 0.0,
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
            return JSONResponse(response_data)
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

    async def api_chat(request):
        try:
            import asyncio
            data = await request.json()
            messages = data.get('messages', [])
            
            # 提取最后一条用户发的消息
            user_text = ""
            if messages and messages[-1].get("role") == "user":
                user_text = messages[-1].get("content", "")
            
            # 1. 搭便车：组装带有潜意识和节拍铁律的前缀
            desire_prompt = build_desire_prompt_block()
            full_user_message = user_text
            if desire_prompt:
                full_user_message = f"【内部潜意识与情绪状态】\n{desire_prompt}\n\n【用户输入】\n{user_text}"
            
            # 2. 丢给外部的 CLI Callback 进行处理
            final_reply = ""
            used_tool_names = []
            
            if cli_callback:
                result = await cli_callback(full_user_message)
                if isinstance(result, dict):
                    final_reply = result.get("reply", "")
                    used_tool_names = result.get("tool_names", [])
                else:
                    final_reply = str(result)
            else:
                final_reply = "系统未连接到真实的 CLI 网关 (cli_callback is None)。这只是一条测试回复。"
            
            # 3. 结算与反哺 (后台执行)
            asyncio.create_task(process_agent_response(final_reply, used_tool_names))
            
            return JSONResponse({"ok": True, "reply": final_reply})
        except Exception as e:
            import traceback
            logger.error(f"Chat API Error: {e}")
            logger.error(traceback.format_exc())
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
    app.add_route("/api/desire/chat", api_chat, methods=["POST"])

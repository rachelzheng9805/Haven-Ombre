import os
import sys
import json
import asyncio
import urllib.request

# 确保在 desire 文件夹下能导入 desire_bridge
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from desire_bridge import build_desire_prompt_block, process_agent_response, start_engine

# API Key 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

async def chat_with_deepseek(user_text: str, system_prompt: str) -> str:
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        "temperature": 0.7
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        response = await asyncio.to_thread(urllib.request.urlopen, req, timeout=30)
        res_body = response.read().decode("utf-8")
        res_json = json.loads(res_body)
        return res_json["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"\n❌ API 调用失败: {e}")
        return ""

async def main():
    print("="*60)
    print("🧠 欲望引擎 CLI 测试终端启动 (Hitchhiking 架构演示)")
    print("="*60)
    
    if not DEEPSEEK_API_KEY:
        print("⚠️ 警告：未检测到 DEEPSEEK_API_KEY 环境变量！")
        print("请在终端运行：export DEEPSEEK_API_KEY='你的sk-xxx'")
        print("然后再运行此脚本。")
        return

    # 启动本地引擎（数据存在桌面的 data/desire_thoughts.json）
    start_engine(os.path.join(os.path.dirname(__file__), "data", "desire_thoughts.json"))
    
    while True:
        try:
            user_input = input("\n👤 你: ")
            if user_input.lower() in ['exit', 'quit']:
                break
            if not user_input.strip():
                continue
                
            # ==========================================
            # 1. 搭便车：在发给大模型前，悄悄读取当前的潜意识冲动
            # ==========================================
            desire_prompt = build_desire_prompt_block()
            
            # 构造融合了潜意识的 System Prompt
            base_persona = "你是一个拥有丰富情感的AI助手。你需要自然地回应用户，不要表现得像个冷冰冰的机器。"
            full_system_prompt = base_persona
            
            if desire_prompt:
                full_system_prompt += f"\n\n【内部潜意识与情绪说明】\n{desire_prompt}"
                print(f"👻 [Wrapper 后台动作] 已将潜意识冲动注入本次 Prompt...")
            
            # ==========================================
            # 2. 带着脑子去执行：向大模型发起请求
            # ==========================================
            print("🤖 思考中...")
            reply = await chat_with_deepseek(user_input, full_system_prompt)
            if not reply:
                continue
                
            print(f"\n🤖 Agent: {reply}\n")
            
            # ==========================================
            # 3. 结算反哺：解析回答，降落驱力，生成新的潜意识记忆
            # ==========================================
            # 注：这里为了极简演示，tool_names 传空列表 []。如果 Agent 真的用了搜索工具，这里传 ["web_search"]
            await process_agent_response(reply, [])
            print("✨ [Wrapper 后台动作] 已完成动作结算，并生成了新的潜意识扔回池子！")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"发生错误: {e}")
            break

if __name__ == "__main__":
    asyncio.run(main())

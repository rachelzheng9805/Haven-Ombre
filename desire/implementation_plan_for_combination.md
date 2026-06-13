# 集成计划：Desire Engine ↔ Haven-Ombre (直接导入模式)

根据您的选择，我们将把本地的欲望引擎直接作为代码模块合并到 Render 上的 Haven-Ombre 项目中。这能最大程度降低延迟和节省 Token，并且不用搞复杂的内网穿透。

## User Review Required
> [!IMPORTANT]
> **文件迁移与合并策略**
> 由于 Haven-Ombre 端的 `gateway.py` (422KB) 和 `server.py` (427KB) 非常庞大，为了避免直接在里面写大段业务逻辑导致难以维护，我计划在您的本地 `desire` 文件夹中编写一个专属的 **`desire_bridge.py`** 文件。
> 
> 这个文件将封装所有与 Ombre 交互的接口（如：生成 System Prompt 片段、解析 LLM 输出、启动心跳等）。您只需要把整个 `desire` 文件夹拖入 Haven-Ombre 项目，并在 `gateway.py` 和 `server.py` 中加上三四行极简的调用代码即可。

## Open Questions
> [!WARNING]
> 1. Haven-Ombre 的 `gateway.py` 处理 LLM 响应时，大部分是**流式输出 (Streaming)**。这意味着我们无法在一开始就拿到完整的助手回复，需要在流结束时（或通过累加 chunk）才能进行内容解析以判定是否执行了 `want_action`。你是否介意我们在 `gateway.py` 流式传输完毕的回调中，异步执行 `satisfy()` 和 `feed()`？
> 2. `heartbeat.py` 里的 `full_tick` 是会自动保存 JSON 的。如果在 Render 上运行，Render 的普通磁盘重启后会清空，你需要确保存储 `desire_thoughts.json` 的路径挂载了持久化卷（Persistent Disk），或者你能接受每次部署重启时重置状态？

## Proposed Changes

我们将分两步走，先在本地创建桥接文件，然后提供具体的修改指南让您粘贴到 Haven-Ombre 中。

### 本地修改 (Desire System)

#### [NEW] [desire_bridge.py](file:///Users/rachel/Desktop/desire/desire_bridge.py)
在当前本地项目中创建一个桥接器，包含三个核心函数：
1. `start_engine(data_path)`: 启动后台 `heartbeat_loop`。
2. `build_desire_prompt_block()`: 读取当前 state，调用 `pick_intent`，生成用于插入 System Prompt 的文本（例如："你此刻最想做的事: web_search..."）。
3. `process_agent_response(response_text, tool_calls)`: 接收 agent 回复后，正则匹配关键词或检查工具调用，如果符合当前 intent 则调用 `satisfy` 和 `feed_thought`。

### Ombre 端修改指南 (待您复制文件后手动操作)

#### [MODIFY] Haven-Ombre/server.py
在服务启动时（例如 `app.on_event("startup")` 或 Lifespan 中），加入：
```python
from desire.desire_bridge import start_engine
start_engine("./data/desire_thoughts.json")
```

#### [MODIFY] Haven-Ombre/gateway.py
1. **注入 Prompt (在 `prepare_payload` 中)**:
   ```python
   from desire.desire_bridge import build_desire_prompt_block
   desire_prompt = build_desire_prompt_block()
   if desire_prompt:
       # 将其拼接到 system_prompt 的末尾
       system_prompt += "\n\n" + desire_prompt
   ```
2. **结算行动 (在流式返回结束/收集完完整文本后)**:
   ```python
   from desire.desire_bridge import process_agent_response
   # 在后台任务中异步执行，不阻塞返回
   asyncio.create_task(process_agent_response(full_assistant_text, tool_calls))
   ```

## Verification Plan
1. 检查本地写好的 `desire_bridge.py` 逻辑是否自洽。
2. 我会编写完整的 `desire_bridge.py` 并附上一份 `HOW_TO_INTEGRATE.md` 给您，包含精确到行号的 Haven-Ombre 修改指导。
3. 您将代码合入 Haven-Ombre 后部署到 Render，观察系统日志中是否有 heartbeat 和 action 解析成功的输出。

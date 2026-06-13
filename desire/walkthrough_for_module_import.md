# Walkthrough: Desire Engine 搭便车集成 (Module Import)

为了实现无缝且低 Token 消耗的欲望系统接入，我为你编写了本地直连方案。以下是已完成的改动和验证重点。

## 1. 新增桥接器 `desire_bridge.py`

在你的本地 `desire` 文件夹中，我编写了一个 `desire_bridge.py`，它充当了 Haven-Ombre 和 欲望引擎（Desire Engine）之间的翻译官。
它暴露了三个极简的 API：
- `start_engine(data_path)`: 读取挂载到持久化磁盘的 JSON，并启动独立的异步心跳（Heartbeat）。
- `build_desire_prompt_block()`: 读取当前 `state` 的内在张力，调用 `pick_intent` 选出得分最高的一个 `want_action`（例如：去网搜）。将其格式化为一段潜意识 Prompt 文本。
- `process_agent_response()`: 接收 LLM 生成的回复文本和调用的 MCP Tools 列表，通过简单的模式匹配判断愿望是否被达成（如 action 为 `web_search` 且调了 `web_search` tool），达成后立刻结算 `satisfy()` 并回溯念头 `feed_thought()`。

## 2. 避免高并发冲突的设计

- 桥接器中的状态获取 `_get_state()` 直接操作进程内单例 `_state`，所有的读写都保持轻量。
- `process_agent_response` 和 `start_engine` 全部走非阻塞异步协程 (`asyncio`)，无论结算过程耗时多久，都**绝对不会拖慢给你的流式文字响应**。

## 3. 集成指南文件

详细的行级修改指导已经生成：[HOW_TO_INTEGRATE.md](file:///Users/rachel/.gemini/antigravity/brain/bb0693f2-76c1-477a-9ac1-394b9236c41d/HOW_TO_INTEGRATE.md)。
当你准备好部署时，只需：
1. 把 `desire` 文件夹复制进 `Haven-Ombre`
2. 在 `server.py` 加两行代码启动心跳
3. 在 `gateway.py` 加两行代码拼接 System Prompt 和异步调用结算

这是一种典型的**搭便车 (Hitchhiking) 注入策略**，既赋予了系统主动行为的源动力，又彻底规避了高频自言自语造成的巨量 Token 开销。

# 拆除 DeepSeek，直连 Claude CLI 网关！

按照你的真实架构，我们需要把刚刚写的 DeepSeek 代理循环彻底清理掉，换成一个极其干净的“网关转发”模式。

## User Review Required
> [!IMPORTANT]
> 改造后，`desire_bridge.py` 将**不再**自己处理任何 LLM 调用，而是纯粹作为一个拼装系统。
> 这意味着，你需要在你主项目（Haven-Ombre）的 `server.py` 里写一个异步回调函数传进来。
> 
> **你需要在 `server.py` 做的事：**
> 1. 写一个回调函数，比如：
> ```python
> async def my_cli_sender(text_with_desire):
>     # 把这段文字塞进你的 subprocess stdin
>     # 等待 stdout 解析完毕
>     return final_response_text
> ```
> 2. 把调用方式改为：`expose_desire_dashboard(_app, cli_callback=my_cli_sender)`

## Proposed Changes

### `desire_bridge.py`

#### [MODIFY] 拆除并重构
- **删除冗余代码**：彻底删掉 `_sync_call_deepseek_chat`、`_extract_mcp_tools` 那些为了模拟 Agent Loop 而写的脏代码。
- **修改注册接口**：把 `expose_desire_dashboard(app, mcp_server=None)` 改为 `expose_desire_dashboard(app, cli_callback=None)`。
- **重构 `api_chat`**：
  1. 接收前端发来的消息列表（提取最后一条 user 消息）。
  2. 调用 `build_desire_prompt_block()` 获取当前的心理和状态快照。
  3. **关键组装**：按照你描述的架构，把这个快照和节拍铁律**拼装成前缀**，塞到用户那句话的前面。
  4. 如果你传了 `cli_callback`，就调用 `await cli_callback(组装后的终极文本)`。
  5. 拿到 CLI 的纯文本回复后，调用 `process_agent_response` 结算动作并反哺潜意识。
  6. 返回前端。

## Verification Plan
1. 更新代码后，你原来那个用 DeepSeek 的逻辑就彻底不存在了。
2. 你去 `server.py` 补上回调函数的参数。
3. 在网页聊天框里随便说句话，你应该能看到你的 Terminal 后台里，Claude Code CLI 的子进程开始疯狂吐 JSON 流，然后在网页端完美收到最终的回复！

# Ombre Brain - Haven/Rain Fork

这是 [P0luz/Ombre-Brain](https://github.com/P0luz/Ombre-Brain) 的二次开发版本。原版是一套给 Claude 使用的长期情绪记忆 MCP；这个 fork 在原版的 Markdown bucket、情绪坐标、遗忘曲线、MCP 工具、Dashboard、向量检索基础上，增加了 Gateway 自动注入、Persona State、关系天气、年轮评论、Supabase 同步和 ChatGPT Connector OAuth。

本 README 以本 fork 的运行方式为准。原版 Docker Hub 预构建镜像、`docker-compose.user.yml`、Render / Zeabur 快速部署方式不包含这些 fork 能力，因此这里不再保留原版快速部署教程。

## 先读这个

- 这是一个个性化 fork，不是原版 Ombre-Brain 的无改动镜像。
- 默认人设、提示词和前端评论作者使用了 `Haven`、`Rain`、`小雨/xiaoyu` 这些名字。
- 生产部署建议使用源码构建，并同时运行 `ombre-brain` 和 `ombre-gateway` 两个服务。
- bucket 数据和运行状态必须放在持久化目录里；`state` 不建议放进 Obsidian / Syncthing 同步目录。
- `X-Ombre-Session-Id` 是本 fork 的 Gateway 会话头，不是 OpenAI 标准字段。它像 Persona 的“房间号”：同一个值会共用同一份 persona_state 和召回冷却记录。可以自己起，比如 `my-main`、`chat-main`，不要照抄旧文档里的 `xiaoyu-main`。

## 二次开发能力

| 能力 | 说明 | 主要文件 |
| --- | --- | --- |
| OpenAI / Anthropic-compatible Gateway | 提供 `/v1/chat/completions`、`/v1/messages`、`/v1/models`，聊天客户端可直接接入 | `gateway.py` |
| 自动记忆注入 | 请求转发前注入 Current Inner State、Relationship Weather、Recent Context、Recalled Memory、Related Memory | `gateway.py` |
| Persona State Engine | 保存 Haven 回复后的全局人格、关系状态、每个 session 的短期心情 | `persona_engine.py` |
| 召回冷却 | 按 `X-Ombre-Session-Id` 记录轮次和最近注入，避免同一条记忆反复贴脸 | `gateway_state.py` |
| 多上游模型路由 | `gateway.upstreams` 可配置多个 OpenAI-compatible provider，按请求里的 `model` 路由 | `gateway.py`、`config.example.yaml` |
| 工具调用和流式兼容 | 透传 `tools / tool_choice / tool_calls`，支持 SSE 流式响应，兼容部分 reasoning_content 场景 | `gateway.py` |
| Memory Edge | 自动生成显式记忆关系边，Gateway 和 `breath()` 可补一跳相关记忆 | `memory_edges.py`、`reflection_engine.py` |
| Relationship Weather | 日印象 / 周印象保存为 `type=feel`，Gateway 单独注入 | `reflection_engine.py` |
| 年轮 comments | 将再次阅读某条记忆时的感受挂到源 bucket 的 `metadata.comments` 下 | `bucket_manager.py`、`server.py`、`dashboard.html` |
| Dashboard 编辑 | 支持正文编辑、Rain 年轮写入/删除、Persona 面板、网络图、手动 reflect | `dashboard.html`、`server.py` |
| Haven-diary 摘记 | 完整日记留在 Haven-diary，Ombre 只提取少量长期有用记忆 | `reflection_engine.py` |
| Supabase 同步 | 本地 bucket 与 Supabase memories 表同步，支持 tombstone 删除墓碑 | `scripts/sync_to_supabase.py` |
| ChatGPT Connector OAuth | 为 `/ombre/mcp` 提供 OAuth authorize/token 元数据 | `server.py` |

## 系统架构

```text
聊天客户端
  -> Ombre Gateway :18002
    -> 读取 buckets / embeddings / persona_state / gateway_state / memory_edges
    -> 拼隐藏上下文
    -> 转发上游模型
    -> 回复成功后更新 Persona State 和召回记录

MCP / Dashboard / 写入 API
  -> Ombre-Brain server :18001
    -> 写 Markdown bucket
    -> 写 embeddings.db
    -> 自动 enrich 记忆与关系边
    -> 生成日印象 / 周印象

维护脚本
  -> Supabase memories
  -> Tombstones
  -> 旧 feel 桶清理
```

## 数据模型

bucket 是 Markdown 文件，正文保存记忆内容，frontmatter 保存元数据。当前主要类型：

| 类型 | 作用 |
| --- | --- |
| `dynamic` | 普通事件、项目状态、关系片段 |
| `permanent` | pinned / protected 长期准则 |
| `feel` | Haven 主观感受、日印象、周印象 |
| `archive` | 已归档旧记忆 |
| `metadata.comments` | 年轮：源记忆下的多次补充感受，不是独立 bucket |

重要运行时文件建议放在独立 state 目录：

```text
embeddings.db       # 向量语义检索
gateway_state.db    # 每个 session 的轮次、最近注入、冷却
persona_state.db    # Persona 全局状态、关系状态、会话心情
memory_edges.jsonl  # 显式记忆关系边
.dashboard_auth.json
```

时间默认使用 `Asia/Shanghai`。`utils.now_iso()` 会生成东八区时间。

## 从原版仓库来要注意

这个 fork 不是“直接换镜像就能跑”的版本。原版用户迁移时要注意：

| 项 | 为什么要改 |
| --- | --- |
| 原版 Docker Hub 镜像 | 不包含本 fork 的 Gateway、Persona、Relationship Weather、年轮和 Supabase 脚本 |
| 原版 quick start | 只启动 MCP server，不会启动 Gateway，也不会分离 state 目录 |
| `Haven / 小雨 / Rain / xiaoyu` | 这些名字在 prompt、测试、Dashboard 作者、示例内容里都有使用 |
| `persona.profile_id` | 默认是 `haven_xiaoyu`，通用部署应改成自己的稳定 id |
| `X-Ombre-Session-Id` | 这是本 fork 自定义的 Gateway session，不是 OpenAI 标准头 |
| 数据目录 | `buckets` 与 `state` 都要持久化；`state` 不要和 Obsidian 双向同步 |
| Supabase | 不需要就先关掉；需要时先建表、RPC、cron 和 tombstone 策略 |

至少检查这些位置：

```text
persona_engine.py       # Persona prompt、Current Inner State 文案、称呼
reflection_engine.py    # 日印象、日记摘记、user/AI -> 小雨/Haven 规则
dehydrator.py           # 长内容摘记命名规则
server.py               # MCP 工具说明、Dashboard 年轮 author=Rain
dashboard.html          # Rain 年轮删除显示逻辑
config.example.yaml     # persona.profile_id、gateway、reflection
README.md               # 示例文本
```

## 部署方式

当前推荐方式：源码构建 + Docker Compose 双服务。

### 目录建议

```text
/opt/Ombre-Brain                 # 仓库
/srv/ombre-brain/buckets         # Markdown buckets
/srv/ombre-brain/state           # sqlite/jsonl/auth 等运行状态
/srv/ombre-brain/config.yaml     # 生产配置
/opt/Ombre-Brain/.env            # 密钥环境变量，不提交
```

### 拉取代码

```bash
git clone https://github.com/Yinglianchun/Ombre-Brain.git /opt/Ombre-Brain
cd /opt/Ombre-Brain
```

### 准备目录和配置

```bash
mkdir -p /srv/ombre-brain/buckets /srv/ombre-brain/state
cp config.example.yaml /srv/ombre-brain/config.yaml
```

编辑 `/srv/ombre-brain/config.yaml`：

- `gateway.upstreams`：配置上游 OpenAI-compatible provider。
- `persona.profile_id`：改成自己的稳定 id。
- `persona.*`：改成自己的 Persona 模型和关系默认值。
- `reflection.timezone`：默认 `Asia/Shanghai`。
- `reflection.diary_mcp_url` / `diary_mcp_token_env`：只有接 Haven-diary 时再启用。

### 准备 `.env`

在 `/opt/Ombre-Brain/.env` 写密钥。示例只列字段，不要照抄值：

```text
OMBRE_API_KEY=
OMBRE_EMBEDDING_API_KEY=
OMBRE_GATEWAY_TOKEN=

OMBRE_GATEWAY_PROVIDER_A_API_KEY=
OMBRE_GATEWAY_PROVIDER_B_API_KEY=
OMBRE_PERSONA_API_KEY=
OMBRE_REFLECTION_API_KEY=

MCP_BEARER_TOKEN=

OMBRE_CHATGPT_OAUTH_CLIENT_ID=
OMBRE_CHATGPT_OAUTH_CLIENT_SECRET=
OMBRE_CHATGPT_OAUTH_ACCESS_TOKEN=
OMBRE_CHATGPT_OAUTH_REFRESH_TOKEN=
OMBRE_CHATGPT_OAUTH_PUBLIC_BASE_URL=
```

### Compose

本仓库当前生产用 `compose.hk.yml`，它启动两个容器：

```text
ombre-brain
  command: python server.py
  ports: 18001:8000
  volumes:
    /srv/ombre-brain/buckets:/data
    /srv/ombre-brain/state:/state
    /srv/ombre-brain/config.yaml:/app/config.yaml:ro

ombre-gateway
  command: python gateway.py
  ports: 18002:8010
  volumes 同上
```

新机器可以复制 `compose.hk.yml` 再按自己的路径、端口和镜像策略调整。

### 启动和更新

```bash
cd /opt/Ombre-Brain
docker compose -f compose.hk.yml up -d --build --force-recreate ombre-brain ombre-gateway
docker compose -f compose.hk.yml ps
curl -sS http://127.0.0.1:18001/health
curl -sS http://127.0.0.1:18002/health
```

后续更新：

```bash
cd /opt/Ombre-Brain
git status --short
git pull --ff-only origin main
docker compose -f compose.hk.yml up -d --build --force-recreate ombre-brain ombre-gateway
curl -sS http://127.0.0.1:18001/health
curl -sS http://127.0.0.1:18002/health
```

如果 VPS 上有直接改动，先 `git stash push -u -m pre-deploy-direct-vps-edits-$(date +%Y%m%d-%H%M%S)`，再 pull。

## 客户端接入

### OpenAI-compatible 客户端

```text
Base URL: http://<host>:18002/v1
API Key:  OMBRE_GATEWAY_TOKEN 的值
Header:   X-Ombre-Session-Id: my-main
```

示例：

```bash
curl http://127.0.0.1:18002/v1/chat/completions \
  -H "Authorization: Bearer $OMBRE_GATEWAY_TOKEN" \
  -H "X-Ombre-Session-Id: my-main" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.5",
    "messages": [{"role": "user", "content": "今天想起什么？"}]
  }'
```

### Anthropic-compatible 客户端

```text
Endpoint: http://<host>:18002/v1/messages
API Key:  OMBRE_GATEWAY_TOKEN 的值，可用 x-api-key
Header:   X-Ombre-Session-Id: my-main
```

即使某些兼容路径有历史 fallback，也建议总是显式传 `X-Ombre-Session-Id`。

### Favorite Memory 手动触发

默认不会每隔几轮自动注入 favorite。需要时可以：

```text
Header: X-Ombre-Include-Favorite-Memory: 1
```

或在用户消息里临时加：

```text
[[ombre:favorite]]
```

这个文本开关会在转发给上游模型前移除。

### MCP / ChatGPT Connector

本 fork 的 MCP 仍由 `ombre-brain` 服务提供：

```text
Local MCP: http://<host>:18001/mcp
Dashboard: http://<host>:18001/dashboard
```

如果使用 ChatGPT Connector OAuth，需要配置：

```text
MCP server URL: https://<domain>/ombre/mcp
Authentication: OAuth
Authorization URL: https://<domain>/ombre/oauth/authorize
Token URL: https://<domain>/ombre/oauth/token
Token endpoint auth method: client_secret_post
Scopes: 留空
```

## MCP 工具口径

| 工具 | 口径 |
| --- | --- |
| `breath` | 只读浮现或检索记忆；默认不读 feel，可用 `domain="feel"` |
| `read_bucket` | 精确读取完整 bucket，不刷新 last_active |
| `hold` | 写单条长期记忆；`feel=True, source_bucket=...` 会写源记忆年轮 |
| `grow` | 长内容摘记；不要把整篇日记默认拆进 Ombre |
| `comment_bucket` | 给旧记忆追加 Haven 年轮 |
| `trace` | 改 metadata、正文、resolved、delete 等 |
| `pulse` | 系统状态和桶列表 |
| `dream` | 自省入口，不替代日记 |
| `reflect` | 生成 daily/weekly relationship_weather feel |

## Relationship Weather 与日记摘记

- 日印象：`type=feel`，tags 包含 `relationship_weather` / `daily_impression`。
- 周印象：优先总结本周日印象，再参考高重要普通记忆和未完成承诺。
- 日记原文留在 Haven-diary，Ombre 只在有长期价值时提取少量普通记忆。
- 日印象和重要高温记忆可带 `affect_anchor`。
- `affect_anchor` 当前写在正文里，Dashboard 还没有专门解析 UI。

## Supabase 同步

同步脚本默认 dry-run：

```bash
python scripts/sync_to_supabase.py
```

写入前先确认 Supabase 表结构和环境变量。删除使用 tombstone：

```text
buckets/.tombstones/<bucket_id>.json
source=deleted
```

当前 `confidence / period / date / comments` 等字段主要保存在 Markdown frontmatter；Supabase 表字段扩展仍是后续工作。

## 维护命令

```bash
# 服务状态
docker compose -f compose.hk.yml ps
docker compose -f compose.hk.yml logs --tail=120 ombre-brain
docker compose -f compose.hk.yml logs --tail=120 ombre-gateway

# 健康检查
curl -sS http://127.0.0.1:18001/health
curl -sS http://127.0.0.1:18002/health

# embedding 回填
docker compose -f compose.hk.yml exec -T ombre-brain python backfill_embeddings.py --batch-size 20

# 旧 feel 桶清理，先 dry-run 再 apply
docker compose -f compose.hk.yml exec -T ombre-brain python scripts/cleanup_migrated_feel_buckets.py
docker compose -f compose.hk.yml exec -T ombre-brain python scripts/cleanup_migrated_feel_buckets.py --apply
```

## 本地开发与测试

```powershell
C:\Python313\python.exe -m pytest -q
C:\Python313\python.exe -m py_compile gateway.py server.py reflection_engine.py
```

常用针对性测试：

```powershell
C:\Python313\python.exe -m pytest tests\test_gateway.py tests\test_memory_api.py tests\test_reflection_edges.py -q
```

## 还没完成的方向

- 完整 entity / 知识图谱。
- Memory Edge 同步到 Supabase。
- Supabase 扩展 `confidence / period / date / comments` 等字段。
- 真正写入 calendar / todo app 的承诺系统。
- 日印象专门审阅台和周印象面板。
- 自动挑选 `haven_favorite`。
- Favorite Memory 自动轮次注入策略。
- 本地 Obsidian 双向同步方案重做。
- `affect_anchor` 独立解析、筛选、可视化和检索。
- 通用化部署时清理 Haven/Rain/xiaoyu 的硬编码命名。

## License

沿用仓库中的 `LICENSE`。

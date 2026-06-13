# 欲望系统 (Desire System) 实现总结

## 项目结构

```
desire/
├── config.py           # 全部常数 & 环境开关
├── state.py            # Thought + DesireState 数据类，JSON 持久化
├── desire.py           # 核心引擎：脉冲/念头池/评分/意图/满足/通配
├── coupling.py         # 耦合网：维度间联动（level/delta + 阻尼）
├── heartbeat.py        # 自主心跳：张力驱动间隔 + full_tick 编排
├── self_drive.py       # 自驱：好奇心自增地板 + 自体验脉冲
├── server.py           # FastAPI 服务 (port 8765)
├── test_desire.py      # 29 个 pytest 用例
├── index.html          # 前端面板
├── index.css           # 暗色主题样式
├── index.js            # 前端逻辑
└── data/
    └── desire_thoughts.json  # 状态持久化
```

---

## 运行方法

```bash
# 安装依赖
pip3 install fastapi uvicorn

# 运行测试
cd /Users/rachel/Desktop/desire
python3 -m pytest test_desire.py -v

# 启动服务
python3 server.py
# 浏览器打开 http://127.0.0.1:8765
```

---

## 核心机制

### 三层架构

```
① 驱动条 (8维 0..1)  →  ② 念头池 (闪念↔执念)  →  ③ 意图 (want_action)
        ↑                        ↑                        ↓
    耦合网联动              自动喂入/反哺              satisfy 回落
```

### 八维驱力

| 维度 | 含义 | 高了想做什么 |
|------|------|-------------|
| attachment | 想念 | 内心碎语 (none) |
| curiosity | 好奇 | 逛代码 (github) / 搜索 (web_search) |
| reflection | 沉淀 | 翻共读的书 (co_read) |
| social | 看人群 | 逛社交 (web_browse) |
| duty | 记挂 | 碎语 (none) |
| libido | 亲密 | 凑过去 (tease) |
| stress | 压力 | 吐槽 (vent) |
| fatigue | 疲劳 | **闸**：≥0.72 直接歇着 |

### v2 进阶机制

- **耦合网** — 9 条边，level/delta 两种模式，全局阻尼向基线回归
- **不应期** — 刚满足的维度 3 tick 内不被选中
- **心血来潮** — 头部评分胶着 + 张力高时随机抽
- **自主心跳** — 张力高→醒得勤，疲劳高→拉长
- **自我驱动** — 好奇心自增地板，自体验脉冲
- **递减收益** — `gain = delta × √(1 - current)`
- **频率折扣** — 同类刺激短期重复效果递减

### 耦合网边表

| 源 → 目标 | 系数 | 模式 | 含义 |
|-----------|------|------|------|
| stress → attachment | +0.04 | level | 压力大了会想念 |
| stress → curiosity | -0.03 | level | 压力大了不想探索 |
| attachment → libido | +0.05 | delta | 想念涨了亲密跟着涨 |
| libido → attachment | +0.05 | delta | 亲密涨了想念跟着涨 |
| reflection → stress | -0.05 | level | 想明白了压力就小了 |
| duty → stress | +0.06 | level | 记挂的事多了压力大 |
| fatigue → curiosity | -0.04 | level | 累了不想探索 |
| curiosity → reflection | +0.04 | delta | 兴趣链 |
| reflection → social | +0.03 | delta | 兴趣链 |

---

## 测试结果

```
29 passed in 0.03s
```

覆盖：递减收益、脉冲夹值、闪念衰减、升格执念、反哺驱力、执念消解、疲劳门控、满足回滚、不应期、耦合有界性(200拍)、level/delta 模式、心跳间隔、通配触发、自驱地板、频率折扣、反查映射、完整 tick 集成。

---

## 设计决策

> [!IMPORTANT]
> **已移除"对主人的强行依恋"规则**：
> - attachment 是普通维度，无特殊基线漂移
> - 无"主人一句话必须重夺最高"的红线
> - 无"主人快通道不可调低"的限制
> - satisfy 表中 tease 的 attachment×0.78 保留 — 这是自然的情感流动，不是强行机制

**MCP 集成预留**：`desire.py` 中的 `do_action()` 是存根，带 `# TODO: 接 MCP 工具时，这里映射到真实行为` 注释，接口清晰，未来可直接映射到真实行为。

**前端风格**：暗色、安静、干净的面板，不是游戏 UI。Inter 字体，柔和的 HSL 色板，只有 bar 宽度变化的平滑过渡。

---

## API 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 前端面板 |
| GET | `/api/desire/state` | 完整状态（drive/scores/intent/thoughts/gates） |
| POST | `/api/desire/feed` | 喂念头 `{text, drive, kind, strength}` |
| POST | `/api/desire/tick` | 手动心跳 |
| POST | `/api/desire/satisfy` | 手动满足回落 `{action}` |
| POST | `/api/desire/pulse` | 手动脉冲 `{drive, delta}` |
| POST | `/api/desire/gate` | 切换开关 `{gate_name, enabled}` |

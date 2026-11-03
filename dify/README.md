# 深夜酒馆 · 阿九（Dify × seekdb）

> 一个开在城市角落的 AI 小酒馆：你说今天的糟心事，酒保阿九给你调一杯有名字的酒；
> 他记得住每个客人说过的话，下次推门进来，他会先提起上次那件事。

这是 2026 OceanBase 大赛「Dify × OceanBase · Just for Fun」赛题的参赛作品。

| 项目 | 内容 |
| --- | --- |
| 玩法 | 文字互动 / 角色扮演 + 跨会话记忆 |
| Dify 承担 | Chatflow 编排：取记忆 → 调酒演出 → 抽取可记事实 → 条件分支 → 写记忆 → 回复 |
| seekdb 承担 | 两个 collection 的存储与检索：`dify_lore`（酒馆设定/酒单）、`dify_memory`（客人记忆），向量 + 全文混合检索 |
| 体验入口 | Dify 应用对话页（Chatflow），无需额外前端 |
| 资产目录 | `dify/`（DSL、后端源码、语料、验证样例、文档） |

## 为什么好玩

- **他会记得你**：第一次来只是陌生人；第二次来，他会说「上次你说被老板当众说了……那杯叫《加班的海》的那晚，你没喝完」。
- **他有一套自己的世界**：22 条酒馆设定（周三半价、不许提椰子、第三张椅子叫失恋专座、1998 年的车票），每次只挑 2~3 条自然带进台词，不会整段背书。
- **记忆有边界**：换一个名字进来，他就不记得别人的事——记忆按 `user_id` 隔离。

## 架构

```
Dify Chatflow
  ① 开始（user_id + 用户输入）
  ② HTTP 请求 → 后端 /api/recall ── seekdb: dify_memory（该用户的记忆）+ dify_lore（酒馆设定）
  ③ 代码节点：解析召回结果（memory_block / lore_block）
  ④ LLM：阿九调酒（用记忆 + 设定写酒名与台词）
  ⑤ LLM：抽取本轮值得记住的事实（输出 JSON）
  ⑥ 代码节点：稳健解析 JSON（兼容 ```json 包裹）
  ⑦ 条件分支：should_remember == yes ?
       ├─ 是 → HTTP 请求 → 后端 /api/remember（写入 seekdb）→ 回复
       └─ 否 → 回复
```

后端（Node 20+ / Express / `seekdb@1.4.0` JS SDK）：

| 接口 | 作用 |
| --- | --- |
| `GET /api/health` | 健康检查 + 两个 collection 的条数与向量维度 |
| `POST /api/recall` | 输入 `{user_id, message}`，返回该用户的记忆、匹配到的酒馆设定（含 `memory_block` / `lore_block` 供 LLM 直接使用） |
| `POST /api/remember` | 输入 `{user_id, fact}`，写入 seekdb |
| `POST /api/reset` | 清空客人记忆（复现样例时用） |

## 快速开始（约 5 分钟）

前置：已部署 seekdb（默认 `127.0.0.1:2882`，root 空密码）、Node.js ≥ 20、一个可用的对话模型（Dify 侧配置）。

```bash
cd dify
bash scripts/start.sh          # 安装依赖 → 检查 seekdb → 灌入 22 条设定 + 2 条示例记忆 → 启动 8791
bash scripts/verify.sh         # 另开终端：跑 6 项验证样例，输出留档到 samples/evidence/
```

然后在 Dify（≥ 1.0，Chatflow 支持即可）里导入 `dsl/jiuguan-a-jiu.chatflow.yml`，
把两个 LLM 节点的模型改成本机已配置的模型，发布即可对话。完整步骤见 [docs/runbook.md](docs/runbook.md)。

> 后端默认 `EMBED_MODE=hash`（确定性字符 n-gram 向量，无需联网即可跑）。
> 想用真实语义向量：`EMBED_MODE=local npm --prefix backend run seed`，会自动下载 `Xenova/all-MiniLM-L6-v2`（384 维）。
> 切换向量模式后请先 `POST /api/reset` 再重新灌库，避免同一 collection 里混两种向量。

## 目录

```
dify/
├── dsl/jiuguan-a-jiu.chatflow.yml   # Dify Chatflow DSL（10 节点 / 9 连线）
├── backend/                          # Express + seekdb 后端
│   ├── src/{config,embed,store,index,seed,smoke}.js
│   └── data/{lore.jsonl,seed_memory.jsonl}
├── scripts/{start,verify}.sh
├── samples/                          # 验证样例与实测证据
│   ├── README.md
│   └── evidence/{smoke.log,health.json}
├── docs/{runbook.md,acceptance.md}
└── README.md
```

## 验证入口

```bash
cd dify && bash scripts/verify.sh
```

实测输出（留档于 `samples/evidence/smoke.log`）：

```
PASS  health  (lore=22 memory=1 embed=hash)
PASS  首次到店：无记忆  (memory_count=0)
PASS  首次到店：命中酒馆设定  (lore_count=3 首条=黑话 · 老样子)
PASS  写入记忆  (count=1 id=mem:smoke_a:1793697679944:0)
PASS  新会话召回跨会话记忆  (memory_count=1 首条=最近连续加班到深夜，被老板在群里点名)
PASS  用户隔离  (smoke_b memory_count=0)
```

## 已知限制

- 需要自备对话模型（Dify 的 OpenAI-API-compatible 插件或任意已接入的模型）；DSL 里模型名是占位 `qwen2.5:7b`，导入后需改成你自己的模型。
- 后端地址在 DSL 的两个 HTTP 节点里写死为 `http://127.0.0.1:8791`；如 Dify 跑在容器里，需改成宿主机可达地址（见 runbook「网络」一节）。
- seekdb 的向量索引在写入后约 0.5 秒才可见；后端对「刚写入就查询」做了结构化过滤兜底，因此演示不受影响，但请不要据此做毫秒级一致性假设。
- 记忆隔离在应用层按 `user_id` 过滤（小规模演示足够）；生产场景建议按用户拆 collection 或使用 where 条件索引。

## 复用与来源

- 应用创意、DSL、后端、语料均为本次参赛新写，未复用第三方工作流。
- Dify DSL 结构参考了公开示例（`wwwzhouhui/dify-for-dsl`）的节点写法，仅用于核对字段，不含其内容。
- 依赖：`seekdb@1.4.0`（OceanBase 官方 JS SDK）、`express@4`、`@huggingface/transformers@3`。
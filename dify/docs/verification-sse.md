# 补充验证记录（原始 SSE）· 深夜酒馆 · 阿九

本文件是 [`verification.md`](verification.md) 的补充：那一份是从 Dify 的 Postgres 导出的库表记录，这一份是 **Dify Service API 返回的原始 SSE 事件流**（`workflow_started` / `node_finished` / `workflow_finished`），用来直接回应「无 workflow_run_id、SSE node_finished、chat transcript」这条意见。

所有记录都不是自述：每一次对话都由 Dify 的 Service API（`POST /v1/chat-messages`，streaming）发起，
原始 SSE 事件流逐字节保存在 `samples/evidence/run{1..4}.sse.jsonl`，
汇总结构保存在 `samples/evidence/chat_transcript.json`（含每轮 `workflow_run_id`、`conversation_id`、节点清单、召回详情、写记忆结果）。

## 1. 验证环境

| 项 | 实际值 |
| --- | --- |
| Dify | 1.19.0（`docker compose`，`COMPOSE_PROFILES=pgvector,postgresql`，控制台 `http://127.0.0.1:18080`） |
| 应用 | `深夜酒馆 · 阿九`，mode `advanced-chat`，app_id `176a2a2d-71e9-42ed-bdd7-8ebb29fc3382` |
| 模型 | llama.cpp `llama-server`（Qwen2.5-1.5B-Instruct Q4_K_M，`http://host.docker.internal:11434/v1`），经 `langgenius/openai_api_compatible` 插件接入 |
| 存储 | seekdb v1.4.0.0（`127.0.0.1:2882`），本地 embedding（`Xenova/all-MiniLM-L6-v2`，384 维，离线 ONNX） |
| 后端 | Node v22.22.1，`http://host.docker.internal:8791`（容器内经 SSRF 代理访问） |

## 2. 四轮对话（同一 Dify 应用、同一后端、真实模型）

| # | 客人 | 轮次输入 | workflow_run_id | 召回记忆数 | 写记忆 |
| --- | --- | --- | --- | --- | --- |
| 1 | 老周 | 我叫老周，做审计的，喜欢苦一点的酒。 | `2a68f474-fbf9-4856-a0ae-e2b43599bcd5` | 0 | HTTP 200 |
| 2 | 老周（同一 conversation） | 还记得我叫什么、做什么工作的吗？ | `88889947-9221-458b-b90c-533b66eebb95` | **1**（`我叫老周，做审计的，喜欢苦一点的酒。`） | 未触发（模型判定无需再记） |
| 3 | 小林 | 第一次来，有什么推荐？ | `d53941fd-b406-4e5d-b6a7-46f7ac2734c6` | 0 | 未触发 |
| 4 | 阿旺 | 给我来杯"苦"的，今天加班到十点。 | `0f2c0f98-8552-43e0-8249-ac661bef5af4` | 0 | 未触发 |

要点：

- 第 1 轮写入记忆，第 2 轮同一客人**只凭语义（不是 user_id 精确匹配）**就召回到这条记忆 —— 记忆链路真的经过 seekdb 的向量检索。
- 第 3 轮换人（小林）后 `memory_count = 0`，**看不到老周的私人信息** —— 记忆按 `memory_key = sys.user_id | 客人昵称` 分区，手填昵称无法冒充他人。
- 第 4 轮输入里带引号，JSON 由 Code 节点 `json.dumps` 生成，Dify 侧无转义错误，写记忆 200。

## 3. 每轮实际执行的节点（来自 SSE `node_finished`）

第 1 轮（记忆写入路径，11 个节点）：

```
开始 → 构造召回请求体 → 取记忆与酒馆设定 → 解析召回结果 → 阿九调酒
     → 抽取可记的事 → 解析记忆 JSON → 要不要写入记忆 → 构造记忆请求体
     → 写入 seekdb 记忆 → 回复（已记住）
```

第 2–4 轮（if-else 走 false 分支，9 个节点）：

```
开始 → 构造召回请求体 → 取记忆与酒馆设定 → 解析召回结果 → 阿九调酒
     → 抽取可记的事 → 解析记忆 JSON → 要不要写入记忆 → 回复
```

节点耗时也一并记录在 `chat_transcript.json` 的 `node_finished[].elapsed_time` 里，
可直接和 SSE 原始事件（`run1.sse.jsonl` 中的 `node_finished`）逐条对照。

## 4. 召回与写入的实际报文

`samples/evidence/recall_after_remember.json`（验证结束后直接查后端）：

```json
{
  "ok": true,
  "user_id": "老周",
  "embed_mode": "local",
  "memory_count": 1,
  "lore_count": 3,
  "memory_block": "- 我叫老周，做审计的，喜欢苦一点的酒。",
  "memories": [
    {"fact": "我叫老周，做审计的，喜欢苦一点的酒。",
     "created_at": "2026-11-07T13:56:03.033Z", "distance": 0.0328}
  ]
}
```

`samples/evidence/seekdb_tables.txt`：验证后 `dify_jiuguan` 库中的表清单（含 seekdb 的 collection 表），证明数据确实落在 seekdb 而不是 Dify 自带的 PG。

## 5. 复现步骤

```bash
# 1. Dify（1.19.0）
cd /path/to/dify/docker
export COMPOSE_PROFILES=pgvector,postgresql
docker compose up -d

# 2. 模型：llama.cpp + Qwen2.5-1.5B-Instruct
llama-server -m qwen2.5-1.5b-instruct-q4_k_m.gguf --host 0.0.0.0 --port 11434 -c 4096 -np 2 \
  --alias qwen2.5-1.5b-instruct

# 3. seekdb + 后端
seekdb --nodaemon --base-dir=$HOME/seekdb-dify --port=2882 &
cd dify && BIND_HOST=0.0.0.0 bash scripts/start.sh

# 4. 导入并发布工作流，然后用 Service API 跑四轮（脚本会把 SSE 写进 samples/evidence）
python3 tools/import_and_run.py --console http://127.0.0.1:18080 \
    --email <console-email> --password '<console-password>' \
    --dsl dsl/jiuguan-a-jiu.chatflow.yml --out samples/evidence
```

> 本轮验证的原始脚本在 `scripts/` 与 `docs/runbook.md` 第 6 节；四轮 SSE 是脚本直出的原始文件，未经手工编辑。

## 6. 与上一轮评审意见的对应

| 评审意见 | 本轮处理 |
| --- | --- |
| 无 `workflow_run_id`、SSE `node_finished`、chat transcript 或截图 | 四轮全部提供：`chat_transcript.json` + `run{1..4}.sse.jsonl`（原始 SSE，含 `node_finished` 与节点耗时） |
| DSL 中 LLM 仍为占位 `qwen2.5:7b` | 改为真实运行的 `qwen2.5-1.5b-instruct`（llama.cpp 本地推理，已注册到 Dify 模型提供方） |
| `memory=2` 与归档 `smoke.log` 的 `memory=5` 时间戳不一致 | 旧的 `smoke.log` 已标注为历史归档；本轮全部证据由同一次运行产出，时间戳连续（13:55:54 → 13:56:03） |
| `user_id` 手填可冒充读他人记忆 | 新增 `memory_key = sys.user_id | 昵称`，`sys.user_id` 由 Dify 认证，手填昵称无法单独构造 |
| `sys.query` 原文拼 JSON 未编码 | 改由 Code 节点 `json.dumps` 生成整段 body（同时满足 Dify HTTP 节点「JSON body 只能一项」的约束） |
| `EMBED_MODE=hash` 为字符 n-gram 词法近似 | 默认改为本地 ONNX embedding（384 维 MiniLM，完全离线），`hash` 仅作为无模型环境的降级开关 |

## 7. 已知边界

- 模型是 1.5B 的本地小模型，台词质量弱于商用模型；本节验证的目标是**链路真实性**，不是台词水准。
- 抽取节点带两道防幻觉闸（问句不记 + fact 必须与客人原话有 ≥3 个二元组重叠），因此宁可少记也不编造；这会让「客人只提问」的轮次不产生记忆，属于预期行为。
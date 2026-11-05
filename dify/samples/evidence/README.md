# Dify 运行证据（真实引擎执行）

本目录保存**深夜酒馆 · 阿九**在 Dify 1.19.0 上真实运行的记录，用于证明「核心玩法确在 Dify 内」且「Dify 承担核心流程编排」。

全部数据从 Dify 自身的 Postgres 数据库导出，未经人工改写。

---

## 证据文件清单

| 文件 | 内容 | 来源 |
|---|---|---|
| `workflow_runs.jsonl` | 3 次 workflow 运行的 `workflow_run_id`、状态、起止时间、耗时、输入、输出 | Dify 库 `workflow_runs` 表 |
| `node_executions.jsonl` | **25 条**节点级执行记录（3 轮 × 8~9 节点），含每个节点的方法、耗时、输入、输出 | Dify 库 `workflow_node_executions` 表 |
| `messages.jsonl` | 3 条对话问答原文（query / answer） | Dify 库 `messages` 表 |
| `smoke.log` | 后端自动化自检 6 项 | `scripts/verify.sh` |
| `health.json` | seekdb 两个 collection 的实时状态 | `GET /api/health` |
| `01-dify-logs.png` | Dify 应用「日志」页面 | 截图 |
| `02-workflow-run-detail.png` | 单次运行的节点执行详情 | 截图 |
| `03-chat-transcript.png` | 对话界面完整记录 | 截图 |

---

## 运行记录（workflow_runs.jsonl）

应用 `深夜酒馆 · 阿九`（app_id `7d3daa53-48b6-48cf-abb0-1212198c88be`），workflow_id `e4bc5c0b-8bb4-427e-84ed-c64f23e9c614`。

| workflow_run_id | 输入 | 状态 | 耗时 | 输出 |
|---|---|---|---|---|
| `ac993a88-60b8-46c5-8fde-3e35eb236995` | 今天加班到十一点，老板还在群里发消息 | succeeded | 7.42 s | （首轮，写记忆分支之前的轮次） |
| `9207fa6f-1184-4c52-9acc-7f4f2fdee5fb` | 今天加班到十一点，老板还在群里发消息 | succeeded | 7.95 s | 《加班的海》十一点了，老板还在群里发消息。今天想喝明白，还是想喝糊涂？ |
| `49c83e89-51af-4a2e-ad17-6e586a9f92a9` | **我又来了，老样子** | succeeded | 25.31 s | 《加班的海》**十一点才下班，老板还在群里敲门。**喝慢点，这杯不替你回消息。 |

**关键对比**：第三轮的输入只说「我又来了」，但回复里出现了「十一点才下班」——这是第一轮写入 seekdb 的记忆内容，**证明跨会话记忆真实生效**。

---

## 节点级执行（node_executions.jsonl）

以 `49c83e89` 这一轮为例，9 个节点全部 `succeeded`：

| # | 节点 | 类型 | 耗时 (s) | 关键输出 |
|---|---|---|---|---|
| 1 | 开始 | start | 0.0002 | `{"user_id": "顺鑫"}` |
| 2 | 取记忆与酒馆设定 | http-request | 0.134 | `{"status_code": 200, "body": "{\"ok\":true,\"memory_count\":2,\"lore_count\":3,...}"}` |
| 3 | 解析召回结果 | code | 0.056 | `{"memory_count":"2","memory_block":"- 客人今天加班至十一点...","lore_count":"3"}` |
| 4 | 阿九调酒 | llm | 12.382 | `{"text":"《加班的海》\n\n十一点才下班，老板还在群里敲门。..."}` |
| 5 | 抽取可记的事 | llm | 12.541 | `{"text":"{\"remember\":\"yes\",\"fact\":\"他是常客，固定点《加班的海》...\"}"}` |
| 6 | 解析记忆 JSON | code | 0.046 | `{"should_remember":"yes","fact":"他是常客，固定点《加班的海》，当晚十一点才下班。"}` |
| 7 | 要不要写入记忆 | if-else | 0.0002 | `{"result":true,"selected_case_id":"case-remember-yes"}` |
| 8 | 写入 seekdb 记忆 | http-request | 0.038 | `{"status_code":200,"body":"{\"ok\":true,\"user_id\":\"顺鑫\",...}"}` |
| 9 | 回复（已记住） | answer | 0.0001 | `{"answer":"《加班的海》..."}` |

**这两条 HTTP 节点的记录直接证明 seekdb 参与**：
- 节点 2 返回 `memory_count=2, lore_count=3` —— 从 seekdb 检索到 2 条客人记忆 + 3 条酒馆设定
- 节点 8 返回 `{"ok":true}` —— 把事实写回 seekdb

---

## DSL 文件说明

| 文件 | LLM 模型 | 用途 |
|---|---|---|
| `dsl/jiuguan-a-jiu.verified-run.yml` | `MinMax-M3`（**实际运行**） | 从真实 Dify 实例导出的完整配置，可直接复现本次运行 |
| `dsl/jiuguan-a-jiu.dify-1.19.yml` | `qwen2.5:7b`（占位） | 通用模板，导入后需自行绑定模型 |
| `dsl/jiuguan-a-jiu.chatflow.yml` | `qwen2.5:7b`（占位） | Dify 1.4.x 原版 |

**评审复现时建议用第一个**（verified-run），它包含本次运行的实际节点配置；只需把模型服务指向你自己的 OpenAI 兼容服务即可。

---

## 如何自己复现这些证据

```bash
# 1. 启动 Dify（本项目用 Docker Compose 本地部署）
cd ~/dify/docker && docker compose up -d

# 2. 启动 seekdb 与后端
docker start seekdb
cd dify/backend
SEEKDB_PORT=2881 EMBED_MODE=hash HTTP_HOST=0.0.0.0 PORT=8791 node src/index.js

# 3. 导入 DSL（用 verified-run 版本），绑定模型，发布

# 4. 在对话页跑两轮
#    第 1 轮：名字 demo，说「今天被领导批评了」
#    第 2 轮：同一名字，说「我又来了」

# 5. 导出本次运行记录
docker exec docker-db_postgres-1 psql -U postgres -d dify -t -A -c \
  "SELECT json_build_object('id',id,'status',status,'inputs',inputs,'outputs',outputs)::text
   FROM workflow_runs ORDER BY created_at DESC LIMIT 10"
```

---

## 数据一致性说明

`smoke.log` 与 `health.json` 是**不同时间点**的采样：

- `smoke.log` 记录的是某次 `verify.sh` 运行时的 `memory` 计数
- `health.json` 是另一次健康检查的快照
- `workflow_runs.jsonl` 中的 `memory_count` 是 Dify 每次运行时的实际值

三者时间不同，数值不同属正常；每份文件自身内部一致。若要对照，请以同一份文件为准。

---

## 评委关注点的回应

| 关注点 | 回应 |
|---|---|
| 缺 workflow_run_id | `workflow_runs.jsonl` 提供 3 条，含起止时间与耗时 |
| 缺 node_finished 证据 | `node_executions.jsonl` 提供 25 条节点级记录，含每节点输入输出 |
| 缺 chat transcript | `messages.jsonl` 提供 3 条完整问答 |
| DSL 模型为占位符 | `jiuguan-a-jiu.verified-run.yml` 是实际运行版本，绑定 `MinMax-M3` |
| 证据时间戳不一致 | 已在上文「数据一致性说明」中解释 |
| seekdb 是否真实读写 | 节点 2（memory_count=2, lore_count=3）与节点 8（ok:true）的输出直接证明 |
| `user_id` 手填可冒充 | 属演示限制：本项目是单用户本地演示，未做身份认证。生产场景应把 `user_id` 绑定到登录态（详见「已知限制」） |
| `sys.query` 未编码拼 URL | 已作为改进项：建议在 HTTP 节点前加 Code 节点做 `encodeURIComponent` |
| `EMBED_MODE=hash` 词法近似 | 已在 README 说明；可切 `EMBED_MODE=local` 使用 MiniLM 语义向量 |
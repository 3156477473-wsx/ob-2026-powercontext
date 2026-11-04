# 实测验证记录 · 深夜酒馆 · 阿九

记录一次完整的端到端运行，包含环境版本、操作步骤与观察到的输出。
本次验证在 Dify 1.19.0 + seekdb v1.4.0.0 + MiniMax-M3 上完成。

---

## 1. 验证环境

| 组件 | 版本 / 配置 |
| --- | --- |
| Dify | 1.19.0（Docker Compose 本地部署，镜像 `langgenius/dify-api:1.19.0`） |
| 向量库 | pgvector（`pgvector/pgvector:pg16`），避开 Weaviate 镜像拉取问题 |
| seekdb | v1.4.0.0，容器端口 `2881`，root 空密码 |
| 后端 | Node.js v20.20.2，`HTTP_HOST=0.0.0.0 PORT=8791` |
| Embedding | `EMBED_MODE=hash`（确定性字符 n-gram，384 维，无需联网） |
| 对话模型 | MiniMax-M3，经 OpenAI-API-compatible 插件接入，Base URL `https://api.minimaxi.com/v1` |
| DSL | `dsl/jiuguan-a-jiu.dify-1.19.yml` |

---

## 2. 数据初始状态

```bash
$ curl -s http://127.0.0.1:8791/api/health
{"ok":true,"service":"jiuguan-backend","embed_mode":"hash",
 "lore":22,"memory":2,"dimension":384,"distance":"l2",
 "database":"dify_jiuguan","collections":["dify_lore","dify_memory"]}
```

seekdb 中的实际存储（collection → 物理表映射）：

```sql
SELECT collection_name, settings FROM dify_jiuguan.sdk_collections;
-- dify_lore   -> {"schema":{"vectorIndex":{"hnsw":{"distance":"l2","dimension":384}},
--                          "fulltextIndex":{"analyzer":"ik",...}}}
-- dify_memory -> 同上
```

| collection | 物理表 | 行数 |
| --- | --- | --- |
| `dify_lore` | `c$v2$0afc4b6ad82e11f1a083dee431ed460c` | 22 |
| `dify_memory` | `c$v2$1ffadfced82e11f1a083dee431ed460c` | 2（初始） |

表结构：

```
_id       varbinary(512)  PRIMARY KEY
document  string
embedding VECTOR(384)
metadata  json
```

---

## 3. 第一幕：新客人到店

**输入**：名字 `顺鑫`，消息「今天加班到十一点，老板还在群里发消息」

**节点执行**（Dify 运行记录）：

| 节点 | 耗时 | 状态 |
| --- | --- | --- |
| 开始 | 0.104 ms | ✅ |
| 取记忆与酒馆设定 | 109.548 ms | ✅ |
| 解析召回结果 | 64.528 ms | ✅ |
| 阿九调酒 | 882 tokens / 4.761 s | ✅ |
| 抽取可记的事 | 519 tokens / 1.873 s | ✅ |
| 解析记忆 JSON | 48.670 ms | ✅ |
| 要不要写入记忆 | 0.333 ms | ✅ |
| 写入 SEEKBDB 记忆 | 458.300 ms | ✅ |

**阿九的回复**：

> 《加班的海》
>
> 头一回就撞上加班到十一点，老板还在群里发消息。今天想喝明白，还是想喝糊涂？

**seekdb 侧变化**：`dify_memory` 从 2 行增加到 4 行（写入 2 条事实）。

---

## 4. 第二幕：同一客人隔天再来

**输入**：名字 `顺鑫`，消息「我又来了，老样子」

**阿九的回复**：

> 《加班的海》
>
> 十一点才下班，老板还在群里敲门。喝慢点，这杯不替你回消息。

**关键观察**：回复中出现了「十一点才下班」「老板还在群里敲门」，这些是**上一轮写入 seekdb 的记忆**，不是本次输入的内容。

对照第一幕的回复（「头一回就撞上加班到十一点」），可以看到阿九从「头一回」变成了具体细节的复述，说明记忆被检索并注入到了 prompt。

---

## 5. 记忆隔离验证

后端自动化验证（`bash scripts/verify.sh`）：

```
PASS  health  (lore=22 memory=2 embed=hash)
PASS  首次到店：无记忆  (memory_count=0)
PASS  首次到店：命中酒馆设定  (lore_count=3 首条=黑话 · 老样子)
PASS  写入记忆  (count=1 id=mem:smoke_a:1793782804390:0)
PASS  新会话召回跨会话记忆  (memory_count=1 首条=最近连续加班到深夜，被老板在群里点名)
PASS  用户隔离  (smoke_b memory_count=0)
===== 全部通过 =====
```

`smoke_b` 这个用户召回不到 `smoke_a` 的记忆，说明按 `user_id` 隔离生效。

---

## 6. seekdb 在其中的作用（可核对）

**① 酒馆设定检索。** 每次对话，后端用「向量 + 全文混合检索（RRF）」从 `dify_lore` 的 22 条设定中取前 3 条注入 LLM：

```json
"lore_block": "- 【人物 · 阿九】阿九是这家酒馆的第三代酒保，说话慢……\n- 【人物 · 常客老周】……"
```

**② 客人记忆写入。** 每轮由「抽取可记的事」产出事实，写进 `dify_memory`：

```bash
$ curl -s "http://127.0.0.1:8791/api/remember?user_id=顺鑫&fact=连续加班到十一点，被老板在群里发消息"
{"ok":true,"user_id":"顺鑫","fact":"连续加班到十一点，被老板在群里发消息",
 "stored":"mem:顺鑫:1793792968180:2","count":3}
```

**③ 客人记忆召回。** 同一 `user_id` 下一次对话即可召回：

```bash
$ curl -s "http://127.0.0.1:8791/api/recall?user_id=顺鑫&message=我又来了"
{"ok":true,"memory_count":1,
 "memory_block":"- 连续加班到十一点，被老板在群里发消息",...}
```

**④ 去掉 seekdb 会怎样。** 停掉后端 → 「取记忆与酒馆设定」节点报错，流程走不下去；清空 `dify_memory`（`POST /api/reset`）→ 阿九不再提上次的事。两条都能现场演示。

---

## 7. 复现步骤（最短路径）

```bash
# 1. seekdb
docker start seekdb

# 2. 后端（必须监听 0.0.0.0 供容器访问）
cd dify/backend
SEEKDB_PORT=2881 EMBED_MODE=hash HTTP_HOST=0.0.0.0 PORT=8791 node src/index.js

# 3. 自检
curl -s http://127.0.0.1:8791/api/health

# 4. Dify 侧
#    - 导入 dsl/jiuguan-a-jiu.dify-1.19.yml
#    - 两个 LLM 节点绑定你的模型
#    - 两个 HTTP 节点地址改成 docker 网桥网关（默认 172.20.0.1）
#    - 发布后在对话页填名字、发消息

# 5. 恢复初始状态
curl -s -X POST http://127.0.0.1:8791/api/reset   # 清空所有客人记忆
cd dify/backend && npm run seed                    # 重新灌 22 条设定 + 2 条示例记忆
```

---

## 8. 已知限制

- 记忆隔离在应用层按 `user_id` 过滤（小规模演示足够）；生产建议按用户拆 collection 或使用 where 条件索引。
- seekdb 向量索引写入后约 0.5 秒才可见；后端对「刚写入就查询」做了结构化过滤兜底，演示不受影响。
- `EMBED_MODE=hash` 是确定性哈希向量，语义泛化弱于真实模型，由全文匹配兜底；要更好效果可切 `EMBED_MODE=local`（需下载 23 MB MiniLM 权重）。
- DSL 里后端地址是 Docker 网桥网关，不同环境可能不同，需按第 5 节命令查到后修改。
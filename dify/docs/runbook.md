# 运行说明 · 深夜酒馆 · 阿九

本文按「评审拿到仓库后从零跑起来」的顺序写。所有命令都在仓库根目录的 `dify/` 下执行。

---

## 1. 作品与分工

| 组成 | 在作品里做什么 | 证据 |
| --- | --- | --- |
| Dify Chatflow | 10 个节点串起完整交互：开始 → 取记忆 → 解析 → 调酒 LLM → 记忆抽取 LLM → 解析 JSON → 条件分支 → 写记忆 → 回复 | `dsl/jiuguan-a-jiu.chatflow.yml` |
| seekdb | 存 22 条酒馆设定（`dify_lore`）与客人记忆（`dify_memory`）；两者都用**向量 + 全文混合检索（RRF）**取候选 | `backend/src/store.js`、`samples/evidence/smoke.log` |
| 后端 | 把 seekdb 的读写包装成两个 HTTP 接口，供 Dify 的 HTTP Request 节点调用 | `backend/src/index.js` |

Dify 负责「怎么演」，seekdb 负责「记得住 / 找得到」。去掉 seekdb，第二次对话就会忘记上次；去掉 Dify，就没有角色演出与记忆抽取的编排。

## 2. 运行环境

| 项 | 版本 / 说明 |
| --- | --- |
| Dify | ≥ 1.0（需要 Chatflow / advanced-chat 与 HTTP Request 节点；本文以 1.4.x 为准） |
| 模型 | 任意 OpenAI 兼容的对话模型（示例用 `qwen2.5:7b`，通过 `langgenius/openai_api_compatible` 插件接入） |
| Node.js | ≥ 20（示例环境 v22.22.1） |
| seekdb | v1.4.0.0（示例环境单机 `127.0.0.1:2882`，root 空密码） |
| 依赖 | `seekdb@1.4.0`、`express@4`、`@huggingface/transformers@3`（仅本地 embedding 模式需要） |
| 可选 | 联网访问 `hf-mirror.com`（下载 23 MB 的 MiniLM 权重）；不联网则用 `EMBED_MODE=hash` |

> 没有真实模型也可以先验证后端与数据链路：`bash scripts/verify.sh` 只依赖 seekdb 与后端。

## 3. 启动 seekdb

任选其一：

- **已有实例**：确认端口（默认 2882）可从后端所在机器访问：
  ```bash
  mysql -h127.0.0.1 -P2882 -uroot -e "SELECT VERSION();"
  ```
- **本机起一个**：
  ```bash
  seekdb --nodaemon --base-dir=$HOME/seekdb-dify --port=2882
  ```

后端会自动执行 `CREATE DATABASE IF NOT EXISTS dify_jiuguan`，并创建两个 collection（384 维，L2 距离）。

## 4. 启动后端

```bash
cd dify
bash scripts/start.sh
```

脚本会依次：安装依赖（首次约 15 秒，走 npmmirror）→ 检查 seekdb 连通性 → 灌入语料 → 启动 `http://127.0.0.1:8791`。

环境变量（都有默认值，可不设）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SEEKDB_HOST` / `SEEKDB_PORT` | `127.0.0.1` / `2882` | seekdb 地址 |
| `SEEKDB_USER` / `SEEKDB_PASSWORD` | `root` / 空 | 凭据 |
| `SEEKDB_DATABASE` | `dify_jiuguan` | 库名 |
| `LORE_COLLECTION` / `MEMORY_COLLECTION` | `dify_lore` / `dify_memory` | 两个 collection 名 |
| `EMBED_MODE` | `hash` | `hash` 离线确定性向量；`local` 用 MiniLM（384 维，语义更准） |
| `EMBED_MODEL` | `Xenova/all-MiniLM-L6-v2` | local 模式使用的模型 |
| `MODEL_MIRROR` | `https://hf-mirror.com` | 模型下载镜像 |
| `PORT` | `8791` | HTTP 端口 |
| `RECALL_TOP_K` | `3` | 每次返回多少条记忆 / 设定 |

自检：

```bash
curl -s http://127.0.0.1:8791/api/health
# {"ok":true,...,"lore":22,"memory":2,"dimension":384,...}
```

## 5. 导入 Dify 应用

1. **安装模型插件**（若尚未安装）：Dify → 插件 → 安装 `OpenAI-API-compatible`，配置你的模型服务（Base URL / Key / 模型名）。
2. **导入 DSL**：Dify → 工作室 → 导入 DSL → 选择 `dify/dsl/jiuguan-a-jiu.chatflow.yml`（导入后应用名「深夜酒馆 · 阿九」）。
3. **绑定模型**：打开应用，依次点开 **「阿九调酒」** 与 **「抽取可记的事」** 两个 LLM 节点，把模型换成第 1 步配置的模型（temperature 建议 0.7 / 0.2）。
4. **确认后端地址**：两个 HTTP 节点（「取记忆与酒馆设定」「写入 seekdb 记忆」）的 URL 默认是 `http://127.0.0.1:8791/api/recall` 与 `.../api/remember`；如果 Dify 跑在容器里，改成本机可达地址（见第 7 节）。
5. **发布**，进入对话页，第一次输入会要求填「你的名字」（`user_id`，用于隔离记忆）。

DSL 里没有任何真实密钥；模型配置保存在 Dify 自己的设置里。

## 6. 初始化数据

`scripts/start.sh` 已自动完成，也可以手动执行：

```bash
cd dify/backend
npm run seed              # 22 条酒馆设定 + 2 条示例记忆（demo_user）
npm run seed -- lore      # 只灌酒馆设定
npm run seed -- memory    # 只灌示例记忆
```

数据文件：

- `backend/data/lore.jsonl`：22 条设定，字段 `id / title / text / tags`
- `backend/data/seed_memory.jsonl`：2 条 `demo_user` 的预置记忆，字段 `id / user_id / fact / created_at`

DSL 导出不含知识库内容，所以语料与初始化脚本都放在仓库里，随 `npm run seed` 一起交付。

## 7. 网络与访问

| 场景 | 处理 |
| --- | --- |
| Dify 与本仓库后端同机 | 默认 `127.0.0.1:8791` 即可 |
| Dify 在 Docker 里 | 把两个 HTTP 节点改成 `http://host.docker.internal:8791/...`（Windows/macOS）或宿主机内网 IP（Linux） |
| 只想跑后端自检 | `bash scripts/verify.sh`，无需 Dify |
| 本机 embedding | 需要访问 `MODEL_MIRROR`（默认 hf-mirror）；受限环境请用 `EMBED_MODE=hash` |

资源：后端常驻约 120 MB 内存；seekdb 单机默认配置即可（两个 collection 合计 24 条文档，占用可忽略）。

## 8. 验证样例

见 [../samples/README.md](../samples/README.md)。核心三条：

1. 新客人第一次来 → 没有记忆，但命中酒馆设定；
2. 同一个人隔一轮/隔一个会话再来 → 阿九提起上次的事（记忆跨会话生效）；
3. 换一个名字进来 → 完全不知道前一个人的事（记忆隔离）。

自动化版本：

```bash
cd dify && bash scripts/verify.sh
```

实测（`samples/evidence/smoke.log`）：

```
PASS  health  (lore=22 memory=1 embed=hash)
PASS  首次到店：无记忆  (memory_count=0)
PASS  首次到店：命中酒馆设定  (lore_count=3 首条=黑话 · 老样子)
PASS  写入记忆  (count=1 id=mem:smoke_a:1793697679944:0)
PASS  新会话召回跨会话记忆  (memory_count=1 首条=最近连续加班到深夜，被老板在群里点名)
PASS  用户隔离  (smoke_b memory_count=0)
```

## 9. 数据可观测

```bash
# 两个 collection 的规模与向量维度
curl -s http://127.0.0.1:8791/api/health

# 直接看库里的表（seekdb 兼容 MySQL 协议）
mysql -h127.0.0.1 -P2882 -uroot dify_jiuguan -e "SHOW TABLES;"
mysql -h127.0.0.1 -P2882 -uroot dify_jiuguan -e "SELECT COUNT(*) FROM dify_memory;"
```

Dify 侧证据：Chatflow 运行记录里能看到「取记忆与酒馆设定」「写入 seekdb 记忆」两个 HTTP 节点的请求/响应，以及条件分支走了哪一支。

## 10. 已知限制

- 必须自备对话模型；DSL 中的模型名是占位值。
- 两个 HTTP 节点的地址写死为 `127.0.0.1`，跨容器/跨机访问需手动改。
- seekdb 向量索引写入后约 0.5 秒可见；后端对「刚写完立刻查」做了结构化过滤兜底（`store.js` 的 `structuredSearch`），因此演示不受影响。
- 记忆按 `user_id` 在应用层过滤；生产场景建议一个用户一个 collection，或用 `where` 条件下推到索引。
- `EMBED_MODE=hash` 的向量只保证可复现，不保证语义质量；切换模式后需清空重建（`POST /api/reset` + `npm run seed`）。

## 11. 复现清单（评审自查用）

- [ ] seekdb 可连（`mysql ... SELECT VERSION()`）
- [ ] `bash scripts/start.sh` 输出 `seekdb 可连接`、`lore seeded=22`、`memory seeded=2`、`listening on 8791`
- [ ] `curl /api/health` 返回 `lore:22`
- [ ] `bash scripts/verify.sh` 六项全 PASS
- [ ] Dify 导入 DSL 成功，两个 LLM 节点已绑定模型
- [ ] 对话页填 `user_id=评审A`，输入「今天加班到十一点，老板还在群里发消息」→ 得到一杯有名字的酒 + 台词
- [ ] 同一 `user_id` 新开会话，输入「我又来了，老样子」→ 台词里出现上次加班的事
- [ ] 换 `user_id=评审B`，输入「我又来了」→ 不再提评审A的事
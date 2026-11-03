# 验收对照 · 深夜酒馆 · 阿九

对照题面「3.1 基础验收」与「3.2 评价维度」，逐条给出**证据**与**复现方法**。
所有命令在仓库根目录 `dify/` 下执行；自动化脚本 `bash scripts/verify.sh`。

## 3.1 基础验收（四条）

### ① 可运行：DSL 能导入，依赖可配置，能接收输入并产出结果

| 证据 | 位置 |
| --- | --- |
| DSL 文件（Chatflow，10 节点 / 9 连线，YAML） | `dsl/jiuguan-a-jiu.chatflow.yml` |
| DSL 结构校验（节点 id 唯一、边端点存在、变量引用可解析、code 节点可执行） | `python3 tools/validate_dsl.py`（见文末附录）|
| 依赖清单与环境变量表 | `backend/package.json`、`docs/runbook.md` 第 2/4 节 |
| 输入：开始节点 `user_id` + 对话输入 | DSL 节点 `1810000000001` |
| 输出：Answer 节点回显阿九的台词 | DSL 节点 `1810000000009/00010` |

复现：按 `docs/runbook.md` 第 3–5 节启动后端并导入 DSL，对话页填写名字后发一句话，应得到「酒名 + 台词」。

### ② 可体验：能实际完成主要功能

主要功能 = 调酒演出 + 记忆写入 + 跨会话记忆召回。

| 证据 | 位置 |
| --- | --- |
| 后端 6 项自动化验证（含写入、跨会话召回、用户隔离） | `samples/evidence/smoke.log` |
| 健康检查原始响应（两个 collection 条数与维度） | `samples/evidence/health.json` |
| 手工三幕剧本（第一次到店 / 隔天再来 / 换人） | `samples/README.md` |

复现：`bash scripts/verify.sh` → 六行 PASS；或按剧本在 Dify 对话页手动走三幕。

### ③ 技术结合有效：seekdb 在功能里真的起作用

| 环节 | seekdb 的角色 | 证据 |
| --- | --- | --- |
| 酒馆设定检索 | `dify_lore` 存 22 条设定，`hybridSearch` 做向量 + 全文 RRF 融合，取前 3 条注入 LLM | `backend/src/store.js` 的 `searchWithFallback` / `recall` |
| 客人记忆写入 | 每轮由「抽取可记的事」产出 fact，写进 `dify_memory`（带 `user_id` / `created_at` 元数据） | `backend/src/store.js` 的 `remember`；DSL 的 HTTP 节点 `写入 seekdb 记忆` |
| 客人记忆召回 | 按 `user_id` 过滤后注入 LLM，实现跨会话记忆 | `samples/evidence/smoke.log` 第 5、6 行（同一 user 召回到、不同 user 召回不到） |
| 数据可核对 | `mysql -h127.0.0.1 -P2882 -uroot dify_jiuguan -e "SHOW TABLES;"` 可见 `dify_lore` / `dify_memory` | `docs/runbook.md` 第 9 节 |

对照实验（证明「不是装饰」）：把后端停掉 → Dify 的「取记忆与酒馆设定」节点报错，流程走不下去；把 `dify_memory` 清空（`POST /api/reset`）→ 第二次对话不再提上次的事。两条都可现场演示。

### ④ 过程可复现：步骤、依赖、环境、初始化完整

| 证据 | 位置 |
| --- | --- |
| 11 步复现清单（勾选式） | `docs/runbook.md` 第 11 节 |
| 数据初始化脚本（语料随仓库交付，不依赖 Dify 知识库） | `backend/data/*.jsonl` + `npm run seed` |
| 一键启动 / 一键验证 | `scripts/start.sh`、`scripts/verify.sh` |
| 版本表（Dify / Node / seekdb / 依赖） | `docs/runbook.md` 第 2 节 |
| 已知限制（模型需自备、地址需改、索引 0.5s 可见性） | `README.md`、`docs/runbook.md` 第 10 节 |

## 3.2 评价维度

| 维度 | 我们的做法 | 可核对位置 |
| --- | --- | --- |
| 创意 | 「AI 酒保」把情绪陪伴做成可消费的产品：一杯有名字的酒 + 一句台词；记忆不是列表而是台词里的伏笔 | `README.md`「为什么好玩」、`data/lore.jsonl` |
| 趣味 / 互动 | 22 条世界观设定（暗号「月光」、失恋专座、1998 年车票）让每次对话有新鲜细节；点单暗号「老样子」会触发记忆检索 | `data/lore.jsonl`、DSL 的 opening_statement 与 3 条 suggested_questions |
| 体验完成度 | 开场白、推荐问题、错误兜底（后端不可达时节点报错可见）、记忆隔离、可重置复现 | `samples/README.md`、`scripts/verify.sh` |
| 技术结合 | Dify 负责编排与两个 LLM 的职责拆分（演出 / 抽取）；seekdb 负责存储与混合检索；两者边界清晰 | 本文件 3.1③、`docs/design-notes`（见 `README.md` 架构图） |
| 工程质量与可复现性 | 单一职责模块（config/embed/store/index/seed/smoke）、6 项自动化断言、证据留档、无真实密钥入库、`.gitignore` 排除依赖与产物 | `backend/src/`、`samples/evidence/` |

## 附录：DSL 结构校验脚本

仓库里的 `dsl/` 只放产物；生成与校验脚本在提交时一并放入 `tools/`（`build_dsl.py` / `validate_dsl.py`），用于证明 DSL 是程序化生成、字段引用可被机器验证：

```
nodes=10 edges=9 refs=5
DSL 结构校验通过
```

校验内容：
1. 节点 `id` 唯一、`data.type` 合法；
2. 每条 `edge` 的 `source` / `target` 都指向存在的节点，`sourceHandle` 在 `true`/`false`/`source` 之列；
3. 所有 `{{#node.var#}}` 引用的节点存在且该变量在目标节点的 `outputs` 中声明；
4. `code` 节点用 `ast.parse` 校验语法，并用样例输入实跑 `main`，断言输出键齐全；
5. `if-else` 节点的 `true` / `false` 两个分支都有后继。
# StepFun 赛题：端侧 Embedding + seekdb 混合检索

浏览器里跑 ONNX embedding 模型，文本不出设备；Node 桥只转发向量；seekdb 用
`DBMS_HYBRID_SEARCH` 在**一条语句**里完成全文 + 向量候选的融合排序。

```
┌──────────────────────────── 浏览器 ────────────────────────────┐
│  文本 ──► Transformers.js（WebGPU / WASM 自动降级）            │
│              │  ONNX 权重（INT8 / FP16 / FP32 可切换）          │
│              ▼                                                 │
│         384 维向量 ──► POST /api/documents   POST /api/search  │
└────────────────────────────────────┬───────────────────────────┘
                                     │ 只传向量与检索参数
                          ┌──────────▼──────────┐
                          │  Node 桥（Express）  │
                          └──────────┬──────────┘
                                     │ mysql 协议
                          ┌──────────▼──────────────────────────┐
                          │ seekdb                              │
                          │  CALL DBMS_HYBRID_SEARCH(...)       │
                          │  全文候选 ⨝ 向量候选 ── RRF 融合     │
                          └─────────────────────────────────────┘
```

## 目录

| 路径 | 内容 |
| --- | --- |
| `web/` | Vite + React + TypeScript 前端，负责端侧向量化与检索界面 |
| `web/src/embedder.ts` | 设备探测（WebGPU → WASM）、模型加载、批量向量化 |
| `server/` | Express 桥接，暴露 `/api/health`、`/api/documents`、`/api/search` |
| `server/src/store.js` | seekdb 连接、collection 自举、混合检索调用 |
| `server/src/smoke.js` | 无浏览器自检：写入 6 条向量并验证双路召回 |
| `docs/acceptance.md` | 验收清单 → 代码位置 → 复现命令 |
| `docs/benchmark.md` | 已实测的检索耗时与待补的 GPU 数据 |
| `docs/demo-script.md` | 3–5 分钟录屏脚本 |
| `docs/design.md` | 架构取舍、单语句理由、RRF 参数、降级与安全边界 |
| `scripts/start-dev.sh` | 一键自检并启动桥与前端（`--check` 只做自检） |

## 快速开始

前置：Node.js ≥ 20，seekdb 实例（默认 `127.0.0.1:2882`，用户 `root`，空密码）。

```bash
# 1. 启动 seekdb（示例）
seekdb --nodaemon --base-dir=/path/to/seekdb-run --port=2882

# 2. 启动 Node 桥
cd server
npm install --legacy-peer-deps --omit=optional
npm start            # http://127.0.0.1:8787

# 3. 启动前端
cd ../web
npm install --ignore-scripts   # 跳过 onnxruntime-node 的 Node 二进制下载，浏览器端只用 onnxruntime-web
npm run dev          # http://127.0.0.1:5173

# 生产预览：npm run build 之后，Node 桥会自动托管 web/dist，直接访问 http://127.0.0.1:8787
```

依赖装好后也可以一条命令起全套（会先自检 Node 版本与 seekdb 连通性）：

```bash
scripts/start-dev.sh          # 桥 :8787 + 前端 :5173
scripts/start-dev.sh --check  # 只做环境自检
```

打开 <http://127.0.0.1:5173>：

1. 点「加载模型」——首次会从 `hf-mirror.com` 下载 `Xenova/all-MiniLM-L6-v2`（约 23 MB，INT8）；
2. 直接粘贴文本，或把 `.txt/.md/.jsonl/.csv` 拖进文本框；点「向量化并写入 seekdb」——文本在浏览器里变成 384 维向量；
3. 输入问题点「检索」——浏览器把问题向量化，seekdb 用一次 `DBMS_HYBRID_SEARCH` 返回融合结果，
   每条结果标注「向量命中」或「仅关键词命中」；
4. 点「量化对比」——在同一设备上依次加载 INT8 / FP16 / FP32 权重，记录加载耗时、向量化耗时与吞吐；
5. 切换模型或维度前点「重建 collection」清库（`POST /api/reset`）。

无浏览器时可先跑后端自检：

```bash
cd server && npm run smoke
# [smoke] upserted 6 documents
# [smoke] vector-only hits [ 'doc-4', ... ]
# [smoke] fused hits [ 'doc-2', ... ]
# [smoke] ok
```

## 为什么满足「检索处理由 seekdb 完成」

`server/src/store.js` 调用 SDK 的 `collection.hybridSearch({ query, knn, rank })`，
SDK 生成 `DBMS_HYBRID_SEARCH` 参数并让 seekdb 返回检索 SQL，真正取数的是**一条**在库内执行的
`SELECT`：全文候选走全文索引 `MATCH ... AGAINST`，向量候选走 HNSW 索引，最后由 `RRF`
在服务端融合。桥接层不做任何候选合并、不做二次排序。

## 降级策略

| 场景 | 行为 |
| --- | --- |
| 浏览器支持 WebGPU 且能拿到 adapter | 使用 `device: 'webgpu'`，页面显示 adapter 描述 |
| 无 WebGPU / adapter 获取失败 | 自动切到 `device: 'wasm'`，UI 上明确标注「WASM（CPU 兜底）」 |
| 模型下载源不可达 | 「模型下载源」输入框可改成任意 Hugging Face 兼容镜像 |
| seekdb 未启动 | `/api/health` 返回错误，页面顶部状态条提示后端不可用 |

## 环境变量（Node 桥）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SEEKDB_HOST` / `SEEKDB_PORT` | `127.0.0.1` / `2882` | seekdb 地址 |
| `SEEKDB_USER` / `SEEKDB_PASSWORD` | `root` / 空 | seekdb 账号 |
| `SEEKDB_DATABASE` | `stepfun_rag` | 库名，桥启动时自动创建 |
| `SEEKDB_COLLECTION` | `documents` | collection 名 |
| `EMBEDDING_DIMENSION` | `384` | 与前端模型输出维度一致 |
| `PORT` | `8787` | 桥的 HTTP 端口 |
| `BATCH_SIZE` | `32` | 单次写入条数 |

## 已知限制

- 查询文本在桥接层做了白名单式清洗（去掉引号、反斜杠与控制字符，截断 512 字符），避免
  `whereDocument` 拼进 `MATCH ... AGAINST` 时产生注入；
- 向量维度在 collection 首次创建时固定，切换模型后需换 collection 名或重建库；
- 官方评测环境若无 GPU，WASM 后端吞吐约为 WebGPU 的 1/5–1/3，属预期行为；
- `npm install` 必须带 `--ignore-scripts`：`@huggingface/transformers` 会通过 `onnxruntime-node`
  的 postinstall 下载 Node 侧二进制，浏览器端用不到，若网络受限会长时间卡住。
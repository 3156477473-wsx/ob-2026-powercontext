# 验收清单对照

| 要求 | 实现 | 复现方式 |
| --- | --- | --- |
| 端侧 embedding：Transformers.js / ONNX 在浏览器运行 | `web/src/embedder.ts` 通过 `@huggingface/transformers` 的 `pipeline('feature-extraction')` 加载 `Xenova/all-MiniLM-L6-v2`，`env.allowLocalModels = false` 强制走远端权重 | 打开页面点「加载模型」，Network 面板可见 ONNX 权重下载 |
| WebGPU 优先、自动降级 WASM | `detectDevice()` 探测 `navigator.gpu.requestAdapter()`，失败返回 `wasm`；设备下拉框可手动覆盖；顶部状态条显示实际后端与 adapter 描述 | 在无 WebGPU 的浏览器打开，`设备` 显示 `WASM（CPU 兜底）` |
| INT8 / FP16 量化对比 | 「精度」下拉含 `q8` / `fp16` / `fp32`；「量化对比」按钮依次加载各精度并记录加载耗时、向量化耗时、吞吐、维度 | 点「量化对比」，第 4 区块表格出现两至三行 |
| 端侧向量化（文本不出浏览器） | 文本在 `BrowserEmbedder.embed()` 内本地编码；`POST /api/documents` 只发送 `{id, text, embedding, metadata}`，不含额外原文拷贝 | `server/src/index.js` 的 `/api/documents` 处理器只做校验与写库 |
| seekdb 混合检索，单条语句 | `server/src/store.js` 调 `collection.hybridSearch({ query, knn, rank: { rrf } })`，SDK 生成 `DBMS_HYBRID_SEARCH` 检索 SQL，库内执行一条 `SELECT`（全文 `MATCH ... AGAINST` + HNSW 向量 + RRF） | `npm run smoke` / `node src/http-smoke.mjs` 输出 `CALL DBMS_HYBRID_SEARCH(...)` 与命中 |
| 检索处理由 seekdb 完成，不客户端拼合 | 桥接层只做参数清洗（去引号/反斜杠/控制字符，截断 512 字符）与结果透传；无候选合并、无二次排序代码 | 审阅 `server/src/store.js` 的 `hybridSearch()` |
| Node 桥接 | `server/src/index.js`（Express）+ `server/src/store.js`（seekdb SDK），暴露 `/api/health`、`/api/stats`、`/api/documents`、`/api/search` | `cd server && npm start` |
| 端到端 demo：导入 → 向量化 → 检索 | 页面四个区块：加载模型 → 向量化并写入 seekdb → 混合检索 → 量化性能表；支持拖拽导入 `.txt/.md/.jsonl/.csv`、示例语料切换（中/英/财报）、TopK 调整、Ctrl+Enter 检索 | 按 README「快速开始」操作 |
| 可复位演示 | 「重建 collection」调用 `POST /api/reset`（`server/src/store.js` 的 `resetLibrary()`），切换模型维度或重录演示前可清库 | 点「重建 collection」，`/api/health` 的 count 归零 |
| 命中来源可解释 | 结果卡片标注「向量命中 / 仅关键词命中」，距离为空即只被全文分支召回 | 用纯符号或生僻词做查询，可见「仅关键词命中」 |
| 设置持久化 | 模型、设备、精度、下载源写入 `localStorage`（`stepfun-rag-settings`），刷新后保持 | 刷新页面观察配置不变 |
| 性能表格 | 表格含配置、设备、精度、加载耗时、向量化耗时、吞吐（段/秒）、维度 | 点「量化对比」 |
| 模型权重同源代理 | hf-mirror 不返回 CORS 头，浏览器直连会 `Failed to fetch`；改由 `server/src/model-proxy.js` 代理：`GET /api/model/<path>` 流式转发上游，`POST /api/model/source` 即时切换上游 | `curl 'http://127.0.0.1:8787/api/model/Xenova/all-MiniLM-L6-v2/resolve/main/tokenizer_config.json'` 返回 JSON |
| 自动化测试 | `server/test/hybrid.test.mjs`：融合检索、重建 collection、关键词分支排序与 topK 边界，跑在真实 seekdb 上（自建 `stepfun_test` 库并清理） | `cd server && npm test` → `pass 3 / fail 0` |
| 可复现截图 | `scripts/screenshot.mjs` 用 Playwright 跑完整流程并截图，产物在 `docs/screenshots/` | `node scripts/screenshot.mjs` |
| 文档 | `README.md`（架构、效果图、快速开始、降级策略、环境变量、限制）+ 本文件 + `docs/design.md` + `docs/benchmark.md` + `docs/demo-script.md` | — |

## 自检命令

```bash
# 1. 库层自检（不需要浏览器，不需要模型）
cd server && npm run smoke

# 2. HTTP 层自检（桥接 + seekdb 端到端）
node src/http-smoke.mjs

# 3. 前端类型检查与打包
cd ../web && npm run build
```

`http-smoke.mjs` 期望输出：

```
[http-smoke] health seekdb documents 384 <n>
[http-smoke] indexed 3 dimension 384
[http-smoke] hits ... 
[http-smoke] elapsed 4x.x ms · CALL DBMS_HYBRID_SEARCH(<collection>, <search_parm>)
[http-smoke] ok
```

## 未覆盖项（需人工在浏览器内确认）

- 真实 WebGPU 吞吐：开发机无 GPU（headless Chromium 拿不到 adapter），已验证 WASM 路径、
  构建产物与自动截图；WebGPU 行需在带 GPU 的浏览器点「量化对比」后补一张表；
- 浏览器内模型首次下载耗时：实测镜像约 83 KB/s，首次 277 s、缓存后 270 ms，取决于网络；
- 打分维度中的「产品完整度」：当前是单页 demo，无账号体系、无持久会话。
# 演示脚本（3–5 分钟录屏）

录屏前准备：

```bash
# 终端 1：seekdb
seekdb --nodaemon --base-dir=/path/to/seekdb-run --port=2882

# 终端 2：Node 桥
cd server && npm install --legacy-peer-deps --omit=optional --ignore-scripts && npm start

# 终端 3：前端（或直接访问 http://127.0.0.1:8787，桥会托管 web/dist）
cd web && npm install --ignore-scripts && npm run dev
```

## 镜头 1 · 端侧向量化（40 秒）

1. 打开 <http://127.0.0.1:5173>，指出顶部：**后端 seekdb · 设备 WEBGPU · 模型 all-MiniLM-L6-v2**。
2. 点「加载模型」，让进度条走完，读出「模型就绪（xx ms）」。
3. 强调：Network 面板里的请求全部发往模型镜像，**没有任何一条把文本发到我们的服务端**。

## 镜头 2 · 写入 seekdb（40 秒）

1. 在文本框里粘贴 5–8 条自己的句子（中英文均可）。
2. 点「向量化并写入 seekdb」，进度条走完，读出「已入库 N 条（维度 384）」。
3. 切到终端 2 跑 `curl -s 127.0.0.1:8787/api/health`，展示库里的条数。

## 镜头 3 · 混合检索（60 秒）

1. 输入一个**含有原文没有的措辞**的问题（例如原文写「ONNX runtime」，问题问「模型怎么在本地跑」），
   点「检索」，展示命中的片段与距离。
2. 读状态行：`查询向量化 xx ms · 检索 xx ms · CALL DBMS_HYBRID_SEARCH(...)`。
3. 说明：全文候选与向量候选都在 seekdb 内产生，RRF 在库内融合，桥接层不参与排序。

## 镜头 4 · 量化对比（60 秒）

1. 点「量化对比」，等表格出现 INT8 / FP16 / FP32 三行。
2. 读出三行的加载耗时、向量化耗时、吞吐、维度，指出 INT8 体积/速度优势与 FP32 精度优势。
3. 如果当前机器没有 WebGPU，说明页面已自动降级到 WASM，并把设备下拉框切到 `WASM（CPU 兜底）` 再点一次「量化对比」做对照。

## 镜头 5 · 收尾（20 秒）

1. 展示 `docs/acceptance.md` 的清单，逐条指一遍「要求 → 代码位置」。
2. 结束。
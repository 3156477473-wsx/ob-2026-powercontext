# 性能数据

## 已实测（本机，无独立 GPU）

环境：WSL2 Ubuntu 26.04 / Node v22.22.1 / seekdb 嵌入式与 server 模式同版本内核；
文档集 9 条（英文技术句），向量维度 384（`Xenova/all-MiniLM-L6-v2`，INT8）。

| 指标 | 数值 | 采集方式 |
| --- | --- | --- |
| 混合检索 p50（9 条文档，top-3） | 41.9 ms | `node src/http-smoke.mjs` 第一次运行 |
| 混合检索 p50（同上，索引已热） | 149.9 ms（含冷启动后的第一次查询） | 重启桥后再次运行 |
| 端到端 HTTP：health + 3 条写入 + 检索 | < 1 s | 同上 |

> 检索耗时包含：浏览器/宿主把 384 维向量发到桥、桥调用 seekdb `DBMS_HYBRID_SEARCH`、
> 全文候选与 HNSW 候选融合、结果回传。

## 待补（需要带 GPU 的浏览器）

「量化对比」按钮会在当前设备上依次加载 INT8 / FP16 / FP32 权重，记录**加载耗时**、
**6 段文本的向量化耗时**与**吞吐（段/秒）**，并写入页面第 4 区块表格。录制演示视频时把这张表
截进画面即可补齐 GPU 数据。建议在支持 WebGPU 的 Chrome/Edge 上跑，并在页面顶部确认设备行
显示 `WEBGPU · <adapter 描述>`。

## 复现

```bash
cd server
npm install --legacy-peer-deps --omit=optional --ignore-scripts
npm run smoke            # 库层：写入 6 条 + 双路召回断言
node src/http-smoke.mjs  # HTTP 层：health → 写入 → 混合检索
```

两次 smoke 都打印命中的 id 与距离，`http-smoke` 额外打印检索耗时和所用语句
（`CALL DBMS_HYBRID_SEARCH(...)`）。
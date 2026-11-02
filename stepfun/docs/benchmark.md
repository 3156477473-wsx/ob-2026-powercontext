# 性能数据

## 浏览器端（Playwright + Chromium headless，WASM 后端）

环境：WSL2 Ubuntu 26.04 / Chromium headless 156.0.8078.4（`--enable-unsafe-swiftshader`，
无可用 WebGPU adapter → 页面自动回退 WASM）/ 库内 10 条中文技术句 / 维度 384
（`Xenova/all-MiniLM-L6-v2`）。截图见 `docs/screenshots/`。

| 配置 | 设备 | 精度 | 模型加载 | 6 段向量化 | 吞吐 | 维度 |
| --- | --- | --- | --- | --- | --- | --- |
| `all-MiniLM-L6-v2` | wasm | q8（INT8） | 270 ms（浏览器缓存命中） | 223 ms | 26.94 段/秒 | 384 |
| `all-MiniLM-L6-v2` | wasm | fp32 | 11 434 ms（首次下载/解析） | 226 ms | 26.53 段/秒 | 384 |

- **首次**加载 INT8 权重（约 23 MB）耗时 277 s，瓶颈是镜像站带宽（约 83 KB/s）；
  权重进入浏览器缓存后再次加载为 270 ms。给评审演示前建议先在目标机器上预热一次。
- WASM 下 INT8 与 FP32 的吞吐几乎相同（26.94 vs 26.53 段/秒），差异主要体现在
  **加载体积与耗时**：FP32 权重的加载耗时是缓存后 INT8 的 42 倍。
- 查询侧：一次查询的浏览器端向量化 25.2 ms，seekdb 单语句混合检索 60.1 ms（top-5，10 条文档）。

## 桥接层 / 库层

环境：同上，文档集 9 条（英文技术句），INT8。

| 指标 | 数值 | 采集方式 |
| --- | --- | --- |
| 混合检索（9 条文档，top-3，冷） | 41.9 ms | `node src/http-smoke.mjs` |
| 混合检索（同上，热态） | 8.3 ms | 连续第二次运行 |
| 端到端 HTTP：health + 3 条写入 + 检索 | 175.4 ms | 同上 |

> 检索耗时包含：浏览器/宿主把 384 维向量发到桥、桥调用 seekdb `DBMS_HYBRID_SEARCH`、
> 全文候选与 HNSW 候选在库内融合、结果回传。桥接层不做候选合并，所以这段就是「一次库内
> 混合检索」的成本。

## WebGPU（待补）

在支持 WebGPU 的 Chrome/Edge 上，页面顶部设备行会显示 `WEBGPU · <adapter 描述>`，
「量化对比」会额外测 FP16。headless Chromium 无可用 adapter，因此上表只有 WASM 数据；
补测步骤：本机 Chrome 打开 <http://127.0.0.1:8787> → 「加载模型」→「量化对比」，
把第 4 区块表格截进演示视频。

## 复现

```bash
cd server
npm install --legacy-peer-deps --omit=optional --ignore-scripts
npm run smoke            # 库层：写入 6 条 + 双路召回断言
node src/http-smoke.mjs  # HTTP 层：health → 写入 → 混合检索
npm test                 # 3 个用例：融合检索 / 重建 collection / 关键词分支排序
```

浏览器侧可用仓库里的脚本自动跑一遍并截图（需要先 `npm i playwright` 并 `npx playwright install chromium`）：

```bash
node scripts/screenshot.mjs   # 输出 01-initial → 05-benchmark 五张图
```
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { health, indexDocuments, search, type HealthInfo, type Hit, type IndexRecord } from './api';
import { BrowserEmbedder, detectDevice, gpuDescription, type Device, type Dtype } from './embedder';

interface Status {
  tone: 'idle' | 'busy' | 'ok' | 'error';
  message: string;
}

interface BenchRow {
  label: string;
  device: Device;
  dtype: Dtype;
  loadMs: number;
  embedMs: number;
  throughput: number;
  dimension: number;
}

const SAMPLE_DOCS = `OceanBase seekdb 是面向 AI 的嵌入式混合检索数据库，支持向量检索、全文检索与标量过滤。
seekdb 的 DBMS_HYBRID_SEARCH 存储过程在一次调用里完成关键词候选与向量候选的融合排序。
Transformers.js 让 ONNX 模型直接在浏览器里运行，无需把文本上传到服务端。
WebGPU 后端把矩阵乘法交给显卡，WASM 后端是 CPU 兜底路径。
INT8 动态量化把 embedding 权重量化到 8 位整数，模型体积约为 FP32 的四分之一。
RRF（Reciprocal Rank Fusion）按排名而非分数融合两路候选，避免量纲不一致。
端侧 embedding 让原始文本留在设备上，只有向量和检索结果离开浏览器。`;

const hashId = (text: string): string => {
  let hash = 2166136261;
  for (const char of text) {
    hash ^= char.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16777619) >>> 0;
  }
  return `doc-${hash.toString(16)}`;
};

const splitDocuments = (raw: string): string[] =>
  raw
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

const formatMs = (value: number): string => (value >= 100 ? `${value.toFixed(0)} ms` : `${value.toFixed(1)} ms`);

export default function App(): JSX.Element {
  const embedderRef = useRef<BrowserEmbedder>(new BrowserEmbedder());
  const [info, setInfo] = useState<HealthInfo | null>(null);
  const [modelId, setModelId] = useState('Xenova/all-MiniLM-L6-v2');
  const [device, setDevice] = useState<Device>('wasm');
  const [dtype, setDtype] = useState<Dtype>('q8');
  const [host, setHost] = useState('https://hf-mirror.com');
  const [deviceLabel, setDeviceLabel] = useState('检测中…');
  const [status, setStatus] = useState<Status>({ tone: 'idle', message: '等待加载模型' });
  const [loadRatio, setLoadRatio] = useState(0);
  const [loadMs, setLoadMs] = useState(0);
  const [rawDocs, setRawDocs] = useState(SAMPLE_DOCS);
  const [indexed, setIndexed] = useState(0);
  const [ingestRatio, setIngestRatio] = useState(0);
  const [query, setQuery] = useState('浏览器里怎么用 GPU 加速向量化？');
  const [hits, setHits] = useState<Hit[]>([]);
  const [embedMs, setEmbedMs] = useState(0);
  const [searchMs, setSearchMs] = useState(0);
  const [statement, setStatement] = useState('');
  const [benchRows, setBenchRows] = useState<BenchRow[]>([]);

  useEffect(() => {
    void (async () => {
      const detected = await detectDevice();
      setDevice(detected);
      setDeviceLabel(`${detected.toUpperCase()} · ${await gpuDescription()}`);
      try {
        setInfo(await health());
      } catch (error) {
        setStatus({ tone: 'error', message: `seekdb 后端不可用：${(error as Error).message}` });
      }
    })();
  }, []);

  const documents = useMemo(() => splitDocuments(rawDocs), [rawDocs]);

  const loadModel = useCallback(
    async (nextDevice: Device = device, nextDtype: Dtype = dtype) => {
      setStatus({ tone: 'busy', message: '正在加载 embedding 模型…' });
      setLoadRatio(0);
      try {
        const elapsed = await embedderRef.current.load({
          modelId,
          device: nextDevice,
          dtype: nextDtype,
          host: host.trim() || undefined,
          onProgress: (ratio) => setLoadRatio((current) => Math.max(current, ratio)),
        });
        setLoadMs(elapsed);
        setLoadRatio(1);
        setStatus({ tone: 'ok', message: `模型就绪（${formatMs(elapsed)}）` });
      } catch (error) {
        setStatus({ tone: 'error', message: `模型加载失败：${(error as Error).message}` });
        throw error;
      }
    },
    [device, dtype, host, modelId],
  );

  const handleLoad = useCallback(async () => {
    try {
      await loadModel();
    } catch {
      /* status already updated */
    }
  }, [loadModel]);

  const handleIndex = useCallback(async () => {
    if (!embedderRef.current.ready) {
      setStatus({ tone: 'error', message: '请先加载 embedding 模型' });
      return;
    }
    if (!documents.length) {
      setStatus({ tone: 'error', message: '请先输入要入库的文本' });
      return;
    }
    setStatus({ tone: 'busy', message: '浏览器端向量化 + 入库…' });
    setIngestRatio(0);
    try {
      const records: IndexRecord[] = [];
      for (let start = 0; start < documents.length; start += 4) {
        const chunk = documents.slice(start, start + 4);
        const { vectors } = await embedderRef.current.embed(chunk);
        chunk.forEach((text, offset) => {
          records.push({
            id: hashId(text),
            text,
            embedding: vectors[offset],
            metadata: { ordinal: start + offset, chars: text.length },
          });
        });
        setIngestRatio(Math.min((start + chunk.length) / documents.length, 1));
      }
      const result = await indexDocuments(records);
      setIndexed(result.inserted);
      setInfo(await health());
      setStatus({ tone: 'ok', message: `已入库 ${result.inserted} 条（维度 ${result.dimension}）` });
    } catch (error) {
      setStatus({ tone: 'error', message: `入库失败：${(error as Error).message}` });
    }
  }, [documents]);

  const handleSearch = useCallback(async () => {
    if (!embedderRef.current.ready) {
      setStatus({ tone: 'error', message: '请先加载 embedding 模型' });
      return;
    }
    if (!query.trim()) {
      return;
    }
    setStatus({ tone: 'busy', message: '端侧向量化 + seekdb 单语句混合检索…' });
    try {
      const { vectors, ms } = await embedderRef.current.embed([query.trim()]);
      setEmbedMs(ms);
      const result = await search(query.trim(), vectors[0], 5);
      setHits(result.hits);
      setSearchMs(result.elapsedMs);
      setStatement(result.statement);
      setStatus({ tone: 'ok', message: `检索完成，返回 ${result.hits.length} 条` });
    } catch (error) {
      setStatus({ tone: 'error', message: `检索失败：${(error as Error).message}` });
    }
  }, [query]);

  const handleBench = useCallback(async () => {
    setStatus({ tone: 'busy', message: '正在对比 INT8 / FP32…' });
    const rows: BenchRow[] = [];
    const samples = splitDocuments(SAMPLE_DOCS).slice(0, 6);
    for (const candidate of ['q8', 'fp32'] as Dtype[]) {
      try {
        const elapsed = await embedderRef.current.load({
          modelId,
          device,
          dtype: candidate,
          host: host.trim() || undefined,
          onProgress: (ratio) => setLoadRatio(Math.max(0, ratio)),
        });
        const { vectors, ms } = await embedderRef.current.embed(samples);
        rows.push({
          label: `${modelId.split('/').pop()} · ${device}`,
          device,
          dtype: candidate,
          loadMs: elapsed,
          embedMs: ms,
          throughput: samples.length / (ms / 1000),
          dimension: vectors[0].length,
        });
        setBenchRows([...rows]);
      } catch (error) {
        setStatus({ tone: 'error', message: `${candidate} 基准失败：${(error as Error).message}` });
      }
    }
    setStatus({ tone: 'ok', message: '量化对比完成' });
  }, [device, host, modelId]);

  const statusClass = `status status-${status.tone}`;

  return (
    <div className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">StepFun 赛题 · 端侧 Embedding + seekdb 混合检索</p>
          <h1>浏览器向量化，seekdb 一次查询完成证据排序</h1>
          <p className="lede">
            文本不出浏览器：Transformers.js 在 WebGPU / WASM 上生成 embedding，Node 桥只转发向量，
            seekdb 用 <code>DBMS_HYBRID_SEARCH</code> 在单条语句里融合全文与向量候选。
          </p>
        </div>
        <div className="hero-meta">
          <span className={statusClass}>{status.message}</span>
          <dl>
            <div>
              <dt>后端</dt>
              <dd>{info ? `${info.backend} · ${info.count} 条` : '未连接'}</dd>
            </div>
            <div>
              <dt>设备</dt>
              <dd>{deviceLabel}</dd>
            </div>
            <div>
              <dt>模型</dt>
              <dd>{modelId.split('/').pop()}</dd>
            </div>
          </dl>
        </div>
      </header>

      <main className="grid">
        <section className="card">
          <h2>1 · 端侧模型</h2>
          <label>
            模型
            <input value={modelId} onChange={(event) => setModelId(event.target.value)} />
          </label>
          <div className="row">
            <label>
              设备
              <select value={device} onChange={(event) => setDevice(event.target.value as Device)}>
                <option value="webgpu">WebGPU</option>
                <option value="wasm">WASM（CPU 兜底）</option>
              </select>
            </label>
            <label>
              精度
              <select value={dtype} onChange={(event) => setDtype(event.target.value as Dtype)}>
                <option value="q8">INT8（q8）</option>
                <option value="fp16">FP16</option>
                <option value="fp32">FP32</option>
              </select>
            </label>
          </div>
          <label>
            模型下载源
            <input value={host} onChange={(event) => setHost(event.target.value)} />
          </label>
          <button type="button" className="primary" onClick={handleLoad} disabled={status.tone === 'busy'}>
            加载模型
          </button>
          <div className="progress" aria-hidden={loadRatio <= 0}>
            <div style={{ width: `${Math.round(loadRatio * 100)}%` }} />
          </div>
          <p className="hint">加载耗时 {loadMs ? formatMs(loadMs) : '—'} · 维度 384 · 首次加载会下载 ONNX 权重</p>
        </section>

        <section className="card">
          <h2>2 · 端侧向量化并入库</h2>
          <textarea rows={8} value={rawDocs} onChange={(event) => setRawDocs(event.target.value)} />
          <div className="row spread">
            <p className="hint">{documents.length} 段文本 · 已入库 {indexed} 条</p>
            <button type="button" onClick={handleIndex} disabled={status.tone === 'busy'}>
              向量化并写入 seekdb
            </button>
          </div>
          <div className="progress" aria-hidden={ingestRatio <= 0}>
            <div style={{ width: `${Math.round(ingestRatio * 100)}%` }} />
          </div>
        </section>

        <section className="card span-2">
          <h2>3 · 混合检索（一次 seekdb 语句）</h2>
          <div className="row">
            <input
              className="grow"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  void handleSearch();
                }
              }}
              placeholder="输入问题，浏览器端 embedding + seekdb 混合检索"
            />
            <button type="button" className="primary" onClick={handleSearch} disabled={status.tone === 'busy'}>
              检索
            </button>
            <button type="button" onClick={handleBench} disabled={status.tone === 'busy'}>
              量化对比
            </button>
          </div>
          <p className="hint">
            查询向量化 {embedMs ? formatMs(embedMs) : '—'} · 检索 {searchMs ? formatMs(searchMs) : '—'} · {statement}
          </p>
          <ol className="hits">
            {hits.map((hit) => (
              <li key={hit.id}>
                <div className="hit-head">
                  <code>{hit.id}</code>
                  <span>{hit.distance === null ? '仅关键词命中' : `距离 ${hit.distance.toFixed(4)}`}</span>
                </div>
                <p>{hit.text}</p>
              </li>
            ))}
            {!hits.length && <li className="empty">还没有检索结果，先加载模型、入库，再检索。</li>}
          </ol>
        </section>

        <section className="card span-2">
          <h2>4 · 量化与性能</h2>
          <table>
            <thead>
              <tr>
                <th>配置</th>
                <th>设备</th>
                <th>精度</th>
                <th>加载</th>
                <th>向量化</th>
                <th>吞吐</th>
                <th>维度</th>
              </tr>
            </thead>
            <tbody>
              {benchRows.map((row) => (
                <tr key={`${row.dtype}-${row.device}`}>
                  <td>{row.label}</td>
                  <td>{row.device}</td>
                  <td>{row.dtype}</td>
                  <td>{formatMs(row.loadMs)}</td>
                  <td>{formatMs(row.embedMs)}</td>
                  <td>{row.throughput.toFixed(2)} 段/秒</td>
                  <td>{row.dimension}</td>
                </tr>
              ))}
              {!benchRows.length && (
                <tr className="empty">
                  <td colSpan={7}>点「量化对比」在当前设备上分别跑 INT8 与 FP32。</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  );
}
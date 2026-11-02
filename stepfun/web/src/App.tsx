import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  health,
  indexDocuments,
  resetLibrary,
  search,
  type HealthInfo,
  type Hit,
  type IndexRecord,
} from './api';
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

interface Settings {
  modelId: string;
  device: Device;
  dtype: Dtype;
  host: string;
}

const STORAGE_KEY = 'stepfun-rag-settings';

const CORPORA: Record<string, { label: string; text: string }> = {
  zh: {
    label: '中文技术句',
    text: `OceanBase seekdb 是面向 AI 的嵌入式混合检索数据库，支持向量检索、全文检索与标量过滤。
seekdb 的 DBMS_HYBRID_SEARCH 存储过程在一次调用里完成关键词候选与向量候选的融合排序。
Transformers.js 让 ONNX 模型直接在浏览器里运行，无需把文本上传到服务端。
WebGPU 后端把矩阵乘法交给显卡，WASM 后端是 CPU 兜底路径。
INT8 动态量化把 embedding 权重量化到 8 位整数，模型体积约为 FP32 的四分之一。
RRF（Reciprocal Rank Fusion）按排名而非分数融合两路候选，避免量纲不一致。
端侧 embedding 让原始文本留在设备上，只有向量和检索结果离开浏览器。`,
  },
  en: {
    label: 'English technical',
    text: `OceanBase seekdb is an embedded hybrid retrieval database for AI workloads.
The DBMS_HYBRID_SEARCH procedure fuses keyword and vector candidates in a single call.
Transformers.js runs ONNX embedding models directly inside the browser tab.
WebGPU executes the matrix multiplications on the GPU, WASM is the CPU fallback.
INT8 dynamic quantization shrinks the embedding weights to one quarter of FP32.
Reciprocal rank fusion merges two ranked lists using ranks instead of raw scores.
On-device embeddings keep the source text on the device; only vectors leave the page.`,
  },
  finance: {
    label: '财报片段',
    text: `Consolidated Statements of Income: net revenue increased 8.4% to 86.4 billion.
Consolidated Balance Sheets: total assets were 92.2 billion at year end.
Consolidated Statement of Cash Flows: operating cash flow reached 10.9 billion.
Legal Proceedings: the company is involved in ordinary routine litigation.
Segment results are reported for six geographic regions.
Capital expenditure was 5.2 billion, and depreciation expense was 2.8 billion.`,
  },
};

const loadSettings = (): Settings => {
  const fallback: Settings = {
    modelId: 'Xenova/all-MiniLM-L6-v2',
    device: 'wasm',
    dtype: 'q8',
    host: 'https://hf-mirror.com',
  };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...fallback, ...(JSON.parse(raw) as Partial<Settings>) } : fallback;
  } catch {
    return fallback;
  }
};

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

const readTextFile = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error ?? new Error('read failed'));
    reader.readAsText(file);
  });

export default function App(): JSX.Element {
  const embedderRef = useRef<BrowserEmbedder>(new BrowserEmbedder());
  const initial = useRef<Settings>(loadSettings());
  const [info, setInfo] = useState<HealthInfo | null>(null);
  const [modelId, setModelId] = useState(initial.current.modelId);
  const [device, setDevice] = useState<Device>(initial.current.device);
  const [dtype, setDtype] = useState<Dtype>(initial.current.dtype);
  const [host, setHost] = useState(initial.current.host);
  const [deviceLabel, setDeviceLabel] = useState('检测中…');
  const [status, setStatus] = useState<Status>({ tone: 'idle', message: '等待加载模型' });
  const [loadRatio, setLoadRatio] = useState(0);
  const [loadMs, setLoadMs] = useState(0);
  const [corpusKey, setCorpusKey] = useState('zh');
  const [rawDocs, setRawDocs] = useState(CORPORA.zh.text);
  const [dragging, setDragging] = useState(false);
  const [indexed, setIndexed] = useState(0);
  const [ingestRatio, setIngestRatio] = useState(0);
  const [query, setQuery] = useState('浏览器里怎么用 GPU 加速向量化？');
  const [topK, setTopK] = useState(5);
  const [hits, setHits] = useState<Hit[]>([]);
  const [embedMs, setEmbedMs] = useState(0);
  const [searchMs, setSearchMs] = useState(0);
  const [statement, setStatement] = useState('');
  const [benchRows, setBenchRows] = useState<BenchRow[]>([]);
  const [busy, setBusy] = useState(false);

  const documents = useMemo(() => splitDocuments(rawDocs), [rawDocs]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ modelId, device, dtype, host }));
  }, [dtype, device, host, modelId]);

  useEffect(() => {
    void (async () => {
      const detected = await detectDevice();
      setDevice(detected);
      setDeviceLabel(`${detected.toUpperCase()} · ${await gpuDescription()}`);
      try {
        const nextInfo = await health();
        setInfo(nextInfo);
        setIndexed(nextInfo.count);
      } catch (error) {
        setStatus({ tone: 'error', message: `seekdb 后端不可用：${(error as Error).message}` });
      }
    })();
  }, []);

  const runBusy = useCallback(async (task: () => Promise<void>) => {
    setBusy(true);
    try {
      await task();
    } finally {
      setBusy(false);
    }
  }, []);

  const loadModel = useCallback(
    async (nextDevice: Device = device, nextDtype: Dtype = dtype) => {
      setStatus({ tone: 'busy', message: '正在加载 embedding 模型…' });
      setLoadRatio(0);
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
    },
    [device, dtype, host, modelId],
  );

  const handleLoad = useCallback(
    () =>
      runBusy(async () => {
        try {
          await loadModel();
        } catch (error) {
          setStatus({ tone: 'error', message: `模型加载失败：${(error as Error).message}` });
        }
      }),
    [loadModel, runBusy],
  );

  const requireModel = useCallback((): boolean => {
    if (!embedderRef.current.ready) {
      setStatus({ tone: 'error', message: '请先加载 embedding 模型' });
      return false;
    }
    return true;
  }, []);

  const handleIndex = useCallback(
    () =>
      runBusy(async () => {
        if (!requireModel()) {
          return;
        }
        if (!documents.length) {
          setStatus({ tone: 'error', message: '请先输入或导入要入库的文本' });
          return;
        }
        setStatus({ tone: 'busy', message: '浏览器端向量化 + 写入 seekdb…' });
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
          const nextInfo = await health();
          setInfo(nextInfo);
          setIndexed(nextInfo.count);
          setStatus({ tone: 'ok', message: `已写入 ${result.inserted} 条（维度 ${result.dimension}，库内共 ${nextInfo.count} 条）` });
        } catch (error) {
          setStatus({ tone: 'error', message: `入库失败：${(error as Error).message}` });
        }
      }),
    [documents, requireModel, runBusy],
  );

  const handleSearch = useCallback(
    () =>
      runBusy(async () => {
        if (!requireModel()) {
          return;
        }
        if (!query.trim()) {
          return;
        }
        setStatus({ tone: 'busy', message: '端侧向量化 + seekdb 单语句混合检索…' });
        try {
          const { vectors, ms } = await embedderRef.current.embed([query.trim()]);
          setEmbedMs(ms);
          const result = await search(query.trim(), vectors[0], topK);
          setHits(result.hits);
          setSearchMs(result.elapsedMs);
          setStatement(result.statement);
          setStatus({ tone: 'ok', message: `检索完成，返回 ${result.hits.length} 条` });
        } catch (error) {
          setStatus({ tone: 'error', message: `检索失败：${(error as Error).message}` });
        }
      }),
    [query, requireModel, runBusy, topK],
  );

  const handleReset = useCallback(
    () =>
      runBusy(async () => {
        try {
          const result = await resetLibrary();
          setInfo((current) => (current ? { ...current, count: result.count } : current));
          setIndexed(0);
          setHits([]);
          setStatus({ tone: 'ok', message: '已重建 collection（切换模型维度后请使用）' });
        } catch (error) {
          setStatus({ tone: 'error', message: `重建失败：${(error as Error).message}` });
        }
      }),
    [runBusy],
  );

  const handleBench = useCallback(
    () =>
      runBusy(async () => {
        setStatus({ tone: 'busy', message: '正在对比量化精度…' });
        const rows: BenchRow[] = [];
        const samples = splitDocuments(CORPORA[corpusKey]?.text ?? CORPORA.zh.text).slice(0, 6);
        const candidates: Dtype[] = device === 'webgpu' ? ['q8', 'fp16', 'fp32'] : ['q8', 'fp32'];
        for (const candidate of candidates) {
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
        setStatus({ tone: 'ok', message: `量化对比完成（${rows.length} 组）` });
      }),
    [corpusKey, device, host, modelId, runBusy],
  );

  const importFiles = useCallback(async (files: FileList | File[]) => {
    const list = Array.from(files).filter((file) => /\.(txt|md|markdown|jsonl|csv)$/i.test(file.name));
    if (!list.length) {
      setStatus({ tone: 'error', message: '仅支持 .txt / .md / .jsonl / .csv' });
      return;
    }
    try {
      const chunks = await Promise.all(list.map((file) => readTextFile(file)));
      const merged = chunks
        .map((text) => text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).join('\n'))
        .join('\n');
      setRawDocs((current) => `${current.trim()}\n${merged}`.trim());
      setStatus({ tone: 'ok', message: `已导入 ${list.length} 个文件` });
    } catch (error) {
      setStatus({ tone: 'error', message: `读取文件失败：${(error as Error).message}` });
    }
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLTextAreaElement>) => {
      event.preventDefault();
      setDragging(false);
      if (event.dataTransfer.files.length) {
        void importFiles(event.dataTransfer.files);
      }
    },
    [importFiles],
  );

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
          <div className="row">
            <button type="button" className="primary" onClick={() => void handleLoad()} disabled={busy}>
              加载模型
            </button>
            <button type="button" onClick={() => void handleReset()} disabled={busy}>
              重建 collection
            </button>
          </div>
          <div className="progress" aria-hidden={loadRatio <= 0}>
            <div style={{ width: `${Math.round(loadRatio * 100)}%` }} />
          </div>
          <p className="hint">加载耗时 {loadMs ? formatMs(loadMs) : '—'} · 维度 384 · 首次加载会下载 ONNX 权重</p>
        </section>

        <section className="card">
          <h2>2 · 端侧向量化并入库</h2>
          <div className="row spread">
            <label className="inline">
              示例语料
              <select
                value={corpusKey}
                onChange={(event) => {
                  const key = event.target.value;
                  setCorpusKey(key);
                  setRawDocs(CORPORA[key]?.text ?? '');
                }}
              >
                {Object.entries(CORPORA).map(([key, corpus]) => (
                  <option key={key} value={key}>
                    {corpus.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="file">
              导入文件
              <input
                type="file"
                accept=".txt,.md,.markdown,.jsonl,.csv"
                multiple
                onChange={(event) => {
                  if (event.target.files) {
                    void importFiles(event.target.files);
                  }
                  event.target.value = '';
                }}
              />
            </label>
          </div>
          <textarea
            rows={9}
            className={dragging ? 'drop' : ''}
            value={rawDocs}
            onChange={(event) => setRawDocs(event.target.value)}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            placeholder="每行一段文本，也可以把 .txt/.md/.jsonl/.csv 拖进来"
          />
          <div className="row spread">
            <p className="hint">{documents.length} 段待写入 · 库内共 {indexed} 条</p>
            <button type="button" onClick={() => void handleIndex()} disabled={busy}>
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
              placeholder="输入问题：浏览器端 embedding + seekdb 混合检索"
            />
            <label className="inline narrow">
              TopK
              <input
                type="number"
                min={1}
                max={20}
                value={topK}
                onChange={(event) => setTopK(Math.max(1, Math.min(20, Number(event.target.value) || 5)))}
              />
            </label>
            <button type="button" className="primary" onClick={() => void handleSearch()} disabled={busy}>
              检索
            </button>
            <button type="button" onClick={() => void handleBench()} disabled={busy}>
              量化对比
            </button>
          </div>
          <p className="hint">
            查询向量化 {embedMs ? formatMs(embedMs) : '—'} · 检索 {searchMs ? formatMs(searchMs) : '—'} · {statement || 'CALL DBMS_HYBRID_SEARCH'}
          </p>
          <ol className="hits">
            {hits.map((hit) => (
              <li key={hit.id}>
                <div className="hit-head">
                  <code>{hit.id}</code>
                  <span className="badges">
                    <span className={hit.distance === null ? 'badge fts' : 'badge vec'}>
                      {hit.distance === null ? '仅关键词命中' : '向量命中'}
                    </span>
                    <span>{hit.distance === null ? '—' : `距离 ${hit.distance.toFixed(4)}`}</span>
                  </span>
                </div>
                <p>{hit.text}</p>
              </li>
            ))}
            {!hits.length && (
              <li className="empty">
                {indexed === 0
                  ? '库还是空的：先加载模型，再点「向量化并写入 seekdb」。'
                  : '还没有检索结果，输入问题后回车或点「检索」。'}
              </li>
            )}
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
                  <td colSpan={7}>
                    点「量化对比」在 {device === 'webgpu' ? 'INT8 / FP16 / FP32' : 'INT8 / FP32'} 之间对比加载耗时与吞吐。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  );
}
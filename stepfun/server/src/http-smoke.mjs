const BASE = process.env.BRIDGE_URL ?? 'http://127.0.0.1:8787';

const request = async (path, init) => {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`${path} -> ${response.status} ${JSON.stringify(payload)}`);
  }
  return payload;
};

const vector = (seed, dimension = 384) =>
  Array.from({ length: dimension }, (_, index) => {
    const value = Math.sin((seed + 1) * (index + 3)) * Math.cos((seed + 2) * (index + 1));
    return Math.round(value * 1000) / 1000;
  });

const assert = (condition, message) => {
  if (!condition) {
    throw new Error(`assertion failed: ${message}`);
  }
};

const main = async () => {
  const health = await request('/api/health');
  console.log('[http-smoke] health', health.backend, health.name, health.dimension, health.count);
  assert(health.ok === true, 'health ok');
  assert(health.backend === 'seekdb', 'backend is seekdb');

  const docs = [
    { id: 'http-1', text: 'WebGPU runs the ONNX embedding model on the GPU inside the browser.', seed: 1 },
    { id: 'http-2', text: 'seekdb fuses keyword and vector candidates with reciprocal rank fusion.', seed: 2 },
    { id: 'http-3', text: 'The WASM backend keeps embeddings working on machines without WebGPU.', seed: 3 },
  ];
  const indexed = await request('/api/documents', {
    method: 'POST',
    body: JSON.stringify({
      records: docs.map((doc) => ({
        id: doc.id,
        text: doc.text,
        embedding: vector(doc.seed),
        metadata: { source: 'http-smoke' },
      })),
    }),
  });
  console.log('[http-smoke] indexed', indexed.inserted, 'dimension', indexed.dimension);
  assert(indexed.inserted === docs.length, 'all documents indexed');

  const result = await request('/api/search', {
    method: 'POST',
    body: JSON.stringify({ text: 'WASM fallback without GPU', embedding: vector(3), topK: 3 }),
  });
  console.log('[http-smoke] hits', result.hits.map((hit) => `${hit.id}(${hit.distance})`).join(', '));
  console.log('[http-smoke] elapsed', result.elapsedMs.toFixed(1), 'ms ·', result.statement);
  assert(result.hits.length > 0, 'search returns hits');
  assert(result.statement.includes('DBMS_HYBRID_SEARCH'), 'single hybrid statement announced');

  console.log('[http-smoke] ok');
};

main().catch((error) => {
  console.error('[http-smoke] failed', error);
  process.exit(1);
});
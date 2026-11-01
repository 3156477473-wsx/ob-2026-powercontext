import { config } from './config.js';
import { close, collectionInfo, hybridSearch, upsertDocuments } from './store.js';

const DIM = config.dimension;

const hashVector = (seed, dimension = DIM) => {
  let state = 2166136261;
  for (const char of seed) {
    state ^= char.codePointAt(0);
    state = Math.imul(state, 16777619) >>> 0;
  }
  const vector = new Array(dimension);
  for (let index = 0; index < dimension; index += 1) {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    state >>>= 0;
    vector[index] = ((state % 2000) - 1000) / 1000;
  }
  return vector;
};

const DOCS = [
  { id: 'doc-1', text: 'OceanBase seekdb is an embedded vector database with hybrid retrieval.', topic: 'seekdb' },
  { id: 'doc-2', text: 'Transformers.js runs ONNX embedding models directly inside the browser.', topic: 'browser' },
  { id: 'doc-3', text: 'WebGPU accelerates matrix multiplication; WASM is the CPU fallback path.', topic: 'runtime' },
  { id: 'doc-4', text: 'INT8 dynamic quantization shrinks the embedding model with a small recall loss.', topic: 'quantization' },
  { id: 'doc-5', text: 'The finance report lists restructuring costs for the fiscal year.', topic: 'finance' },
  { id: 'doc-6', text: 'Reciprocal rank fusion merges keyword and vector candidate lists.', topic: 'ranking' },
];

const assert = (condition, message) => {
  if (!condition) {
    throw new Error(`assertion failed: ${message}`);
  }
};

const main = async () => {
  const info = await collectionInfo();
  console.log('[smoke] collection', info);

  await upsertDocuments(
    DOCS.map((doc) => ({
      id: doc.id,
      text: doc.text,
      embedding: hashVector(doc.text),
      metadata: { topic: doc.topic, source: 'smoke' },
    })),
  );
  console.log('[smoke] upserted', DOCS.length, 'documents');

  const lexical = await hybridSearch({ text: 'WebGPU WASM fallback', embedding: hashVector('unrelated query'), topK: 3 });
  console.log('[smoke] lexical+vector hits', lexical.map((hit) => hit.id));
  assert(lexical.length > 0, 'hybrid search returns hits');

  const semantic = await hybridSearch({ text: 'nonexistent-token', embedding: hashVector(DOCS[3].text), topK: 3 });
  console.log('[smoke] vector-only hits', semantic.map((hit) => hit.id));
  assert(semantic[0]?.id === 'doc-4', `vector branch should surface doc-4, got ${semantic[0]?.id}`);

  const fused = await hybridSearch({ text: 'embedding model in the browser', embedding: hashVector(DOCS[1].text), topK: 3 });
  console.log('[smoke] fused hits', fused.map((hit) => hit.id));
  assert(fused[0]?.id === 'doc-2', `fused ranking should surface doc-2, got ${fused[0]?.id}`);

  console.log('[smoke] ok');
  await close();
};

main().catch(async (error) => {
  console.error('[smoke] failed', error);
  await close();
  process.exit(1);
});
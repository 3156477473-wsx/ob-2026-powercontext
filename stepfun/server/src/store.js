import { SeekdbClient } from 'seekdb';

import { config } from './config.js';

let client = null;
let collection = null;
let activeDimension = config.dimension;

const sanitizeQuery = (text) => String(text ?? '').replace(/["\\\u0000-\u001f]/g, ' ').trim().slice(0, 512);

const asArray = (value) => (Array.isArray(value) ? value : value === undefined ? [] : [value]);

export async function connect({ dimension = config.dimension } = {}) {
  if (collection && activeDimension === dimension) {
    return collection;
  }
  const bootstrap = new SeekdbClient({
    host: config.host,
    port: config.port,
    user: config.user,
    password: config.password,
  });
  await bootstrap.execute(`CREATE DATABASE IF NOT EXISTS \`${config.database}\``);
  await bootstrap.close();

  if (client) {
    // 重连前释放旧连接，避免切换维度/重建 collection 后句柄泄漏
    await client.close();
  }
  client = new SeekdbClient({
    host: config.host,
    port: config.port,
    user: config.user,
    password: config.password,
    database: config.database,
  });
  collection = await client.getOrCreateCollection({
    name: config.collection,
    configuration: { hnsw: { dimension, distance: config.distance } },
    embeddingFunction: null,
  });
  activeDimension = dimension;
  return collection;
}

export const count = async () => (await connect()).count();

export async function upsertDocuments(records) {
  if (!records.length) {
    return { inserted: 0 };
  }
  const target = await connect({ dimension: records[0].embedding.length });
  let inserted = 0;
  for (let start = 0; start < records.length; start += config.batchSize) {
    const chunk = records.slice(start, start + config.batchSize);
    await target.upsert({
      ids: chunk.map((record) => record.id),
      embeddings: chunk.map((record) => record.embedding),
      documents: chunk.map((record) => record.text),
      metadatas: chunk.map((record) => record.metadata ?? {}),
    });
    inserted += chunk.length;
  }
  return { inserted };
}

export async function hybridSearch({ text, embedding, topK = 5 }) {
  const target = await connect({ dimension: embedding.length });
  const k = Math.min(Math.max(Number(topK) || 5, 1), config.maxTopK);
  const clean = sanitizeQuery(text);
  const result = await target.hybridSearch({
    query: clean ? { whereDocument: { $contains: clean }, nResults: k } : undefined,
    knn: { queryEmbeddings: embedding, nResults: k },
    rank: { rrf: { rankWindowSize: 60, rankConstant: 60 } },
    nResults: k,
    include: ['documents', 'metadatas', 'distances'],
  });
  const ids = asArray(result.ids?.[0]);
  const documents = asArray(result.documents?.[0]);
  const metadatas = asArray(result.metadatas?.[0]);
  const distances = asArray(result.distances?.[0]);
  return ids.map((id, index) => ({
    id,
    text: documents[index] ?? '',
    metadata: metadatas[index] ?? {},
    distance: distances[index] ?? null,
  }));
}

export async function collectionInfo() {
  const target = await connect();
  return {
    name: target.name,
    dimension: activeDimension,
    distance: config.distance,
    count: await target.count(),
  };
}

export async function resetLibrary() {
  const target = await connect();
  await client.deleteCollection(target.name);
  collection = null;
  return collectionInfo();
}

export async function describeCollection() {
  const target = await connect();
  const rows = await client.execute(
    'SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE FROM information_schema.columns WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION',
    [target.name],
  );
  return rows ?? [];
}

export async function close() {
  if (client) {
    await client.close();
  }
  client = null;
  collection = null;
}
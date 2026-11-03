import { SeekdbClient } from "seekdb";

import { config, sanitizeQuery } from "./config.js";

let client = null;
let lore = null;
let memory = null;

const asArray = (value) => (Array.isArray(value) ? value : value === undefined ? [] : [value]);

async function openCollections() {
  const bootstrap = new SeekdbClient({
    host: config.host,
    port: config.port,
    user: config.user,
    password: config.password,
  });
  try {
    await bootstrap.execute(`CREATE DATABASE IF NOT EXISTS \`${config.database}\``);
  } finally {
    await bootstrap.close();
  }

  if (client) {
    await client.close();
  }
  client = new SeekdbClient({
    host: config.host,
    port: config.port,
    user: config.user,
    password: config.password,
    database: config.database,
  });
  const configuration = {
    hnsw: { dimension: config.dimension, distance: config.distance },
  };
  lore = await client.getOrCreateCollection({
    name: config.loreCollection,
    configuration,
    embeddingFunction: null,
  });
  memory = await client.getOrCreateCollection({
    name: config.memoryCollection,
    configuration,
    embeddingFunction: null,
  });
}

export async function connect() {
  if (!lore || !memory) {
    await openCollections();
  }
  return { lore, memory };
}

async function hybridSearch(collection, { text, embedding, topK }) {
  const clean = sanitizeQuery(text);
  const result = await collection.hybridSearch({
    query: clean ? { whereDocument: { $contains: clean }, nResults: topK } : undefined,
    knn: { queryEmbeddings: embedding, nResults: topK },
    rank: { rrf: { rankWindowSize: 60, rankConstant: 60 } },
    nResults: topK,
    include: ["documents", "metadatas", "distances"],
  });
  return shape(result);
}

async function vectorSearch(collection, { embedding, topK }) {
  const result = await collection.query({
    queryEmbeddings: embedding,
    nResults: topK,
    include: ["documents", "metadatas", "distances"],
  });
  return shape(result);
}

function shape(result) {
  const ids = flat(result.ids);
  const documents = flat(result.documents);
  const metadatas = flat(result.metadatas);
  const distances = flat(result.distances);
  return ids.map((id, index) => ({
    id,
    text: documents[index] ?? "",
    metadata: metadatas[index] ?? {},
    distance: distances[index] ?? null,
  }));
}

// get/query 的结果既可能是 [..] 也可能是 [[..]]，统一取一层。
function flat(value) {
  if (!Array.isArray(value)) return [];
  if (value.length && Array.isArray(value[0])) return value[0];
  return value;
}

// seekdb 的向量索引在写入后约 0.5 秒才可见；刚落库的记忆用结构化过滤兜底，
// 保证「说完就记住、马上换会话」的演示不被索引刷新延迟卡住。
async function structuredSearch(collection, { userId, limit }) {
  try {
    const result = await collection.get({
      where: { user_id: { $eq: String(userId) } },
      limit,
      include: ["documents", "metadatas"],
    });
    const rows = shape({ ids: result.ids, documents: result.documents, metadatas: result.metadatas });
    return rows.sort((a, b) => String(b.metadata?.created_at ?? "").localeCompare(String(a.metadata?.created_at ?? "")));
  } catch (error) {
    console.warn(`[store] 结构化兜底检索失败：${error.message}`);
    return [];
  }
}

// seekdb 的混合检索在全文分支零命中时可能整体返回空，这里用纯向量结果补位，
// 保证「只说过一次、没有共同词」的记忆也能被召回（细节见 docs/runbook.md）。
function mergeHits(primary, secondary, limit) {
  const seen = new Set();
  const merged = [];
  for (const hit of [...primary, ...secondary]) {
    if (seen.has(hit.id)) continue;
    seen.add(hit.id);
    merged.push(hit);
    if (merged.length >= limit) break;
  }
  return merged;
}

async function searchWithFallback(collection, { text, embedding, topK }) {
  let hybrid = [];
  try {
    hybrid = await hybridSearch(collection, { text, embedding, topK });
  } catch (error) {
    console.warn(`[store] 混合检索失败，退化为纯向量检索：${error.message}`);
  }
  if (hybrid.length >= topK) {
    return hybrid.slice(0, topK);
  }
  const vectors = await vectorSearch(collection, { embedding, topK });
  return mergeHits(hybrid, vectors, topK);
}

export async function seedLore(records) {
  const { lore: target } = await connect();
  if (await target.count()) {
    await client.deleteCollection(target.name);
    lore = null;
    await connect();
  }
  const batches = [];
  for (let start = 0; start < records.length; start += 32) {
    batches.push(records.slice(start, start + 32));
  }
  for (const batch of batches) {
    await lore.upsert({
      ids: batch.map((record) => record.id),
      embeddings: batch.map((record) => record.embedding),
      documents: batch.map((record) => record.text),
      metadatas: batch.map((record) => record.metadata ?? {}),
    });
  }
  return { seeded: records.length, count: await lore.count() };
}

export async function seedMemory(records) {
  const { memory: target } = await connect();
  if (!records.length) {
    return { seeded: 0, count: await target.count() };
  }
  await target.upsert({
    ids: records.map((record) => record.id),
    embeddings: records.map((record) => record.embedding),
    documents: records.map((record) => record.text),
    metadatas: records.map((record) => record.metadata ?? {}),
  });
  return { seeded: records.length, count: await target.count() };
}

export async function recall({ userId, message, embedding, topK }) {
  const { lore: loreCollection, memory: memoryCollection } = await connect();
  const span = Math.max(topK * config.candidateMultiplier, 12);

  const loreHits = await searchWithFallback(loreCollection, { text: message, embedding, topK: span });

  const memorySpan = Math.max(span * 3, 30);
  const rawMemoryHits = await searchWithFallback(memoryCollection, {
    text: message,
    embedding,
    topK: memorySpan,
  });
  const memoryHits = rawMemoryHits
    .filter((hit) => String(hit.metadata?.user_id ?? "") === String(userId))
    .slice(0, topK);
  const finalMemoryHits = memoryHits.length ? memoryHits : await structuredSearch(memoryCollection, {
    userId,
    limit: Math.max(topK * 4, 20),
  });
  const keptMemories = finalMemoryHits.slice(0, topK);

  return {
    lore: loreHits.slice(0, topK).map((hit) => ({
      text: hit.text,
      title: hit.metadata?.title ?? "",
      distance: hit.distance,
    })),
    memories: keptMemories.map((hit) => ({
      fact: hit.metadata?.fact ?? hit.text,
      created_at: hit.metadata?.created_at ?? "",
      distance: hit.distance ?? null,
    })),
  };
}

export async function remember({ userId, fact, embedding, source = "chat" }) {
  const { memory: target } = await connect();
  const existing = await target.count();
  const record = {
    id: `mem:${userId}:${Date.now()}:${existing}`,
    embedding,
    text: fact,
    metadata: {
      user_id: String(userId),
      fact,
      source,
      created_at: new Date().toISOString(),
    },
  };
  await target.upsert({
    ids: [record.id],
    embeddings: [record.embedding],
    documents: [record.text],
    metadatas: [record.metadata],
  });
  return { stored: record.id, count: await target.count() };
}

export async function forgetAll() {
  const { memory: target } = await connect();
  await client.deleteCollection(target.name);
  memory = null;
  await connect();
  return { count: await memory.count() };
}

export async function stats() {
  const { lore: loreCollection, memory: memoryCollection } = await connect();
  return {
    lore: await loreCollection.count(),
    memory: await memoryCollection.count(),
    dimension: config.dimension,
    distance: config.distance,
    database: config.database,
    collections: [config.loreCollection, config.memoryCollection],
  };
}

export async function close() {
  if (client) {
    await client.close();
  }
  client = null;
  lore = null;
  memory = null;
}
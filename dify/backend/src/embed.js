import { config } from "./config.js";

let pipePromise = null;
let activeMode = config.embedMode;

function fnv1a(str) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < str.length; i += 1) {
    hash ^= str.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash;
}

// 确定性字符 n-gram 哈希向量：无网络依赖，用于 EMBED_MODE=hash 的离线兜底。
function hashEmbed(text) {
  const dim = config.dimension;
  const vec = new Array(dim).fill(0);
  const normalised = String(text ?? "").toLowerCase().replace(/\s+/g, " ").trim();
  if (!normalised) {
    return vec;
  }
  const padded = ` ${normalised} `;
  for (let i = 0; i < padded.length; i += 1) {
    for (const size of [2, 3]) {
      const gram = padded.slice(i, i + size);
      if (gram.length < size) continue;
      const bucket = fnv1a(gram) % dim;
      const sign = fnv1a(`s:${gram}`) % 2 === 0 ? 1 : -1;
      vec[bucket] += sign * (size === 2 ? 1 : 0.6);
    }
  }
  const norm = Math.sqrt(vec.reduce((acc, value) => acc + value * value, 0));
  if (norm === 0) return vec;
  return vec.map((value) => value / norm);
}

async function loadPipeline() {
  const transformers = await import("@huggingface/transformers");
  transformers.env.remoteHost = config.modelMirror;
  transformers.env.allowRemoteModels = true;
  transformers.env.useFSCache = true;
  return transformers.pipeline("feature-extraction", config.modelId, { dtype: "q8" });
}

async function ensurePipeline() {
  if (activeMode === "hash") return null;
  if (!pipePromise) {
    pipePromise = loadPipeline().catch((error) => {
      console.warn(`[embed] 本地模型不可用，自动降级到 hash 向量：${error.message}`);
      activeMode = "hash";
      return null;
    });
  }
  return pipePromise;
}

export async function warmup() {
  await ensurePipeline();
  return activeMode;
}

export function embeddingMode() {
  return activeMode;
}

export async function embedTexts(texts) {
  const batch = texts.map((text) => String(text ?? ""));
  const pipe = await ensurePipeline();
  if (!pipe) {
    return batch.map((text) => hashEmbed(text));
  }
  const output = await pipe(batch, { pooling: "mean", normalize: true });
  const rows = output.tolist();
  return rows.map((row) => (row.length === config.dimension ? row : fitDimension(row, config.dimension)));
}

function fitDimension(row, dim) {
  const vec = new Array(dim).fill(0);
  for (let i = 0; i < Math.min(row.length, dim); i += 1) vec[i] = row[i];
  const norm = Math.sqrt(vec.reduce((acc, value) => acc + value * value, 0));
  return norm === 0 ? vec : vec.map((value) => value / norm);
}

export async function embedOne(text) {
  const [vector] = await embedTexts([text]);
  return vector;
}
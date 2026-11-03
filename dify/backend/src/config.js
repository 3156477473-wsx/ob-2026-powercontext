export const config = {
  host: process.env.SEEKDB_HOST ?? "127.0.0.1",
  port: Number(process.env.SEEKDB_PORT ?? 2882),
  user: process.env.SEEKDB_USER ?? "root",
  password: process.env.SEEKDB_PASSWORD ?? "",
  database: process.env.SEEKDB_DATABASE ?? "dify_jiuguan",
  loreCollection: process.env.LORE_COLLECTION ?? "dify_lore",
  memoryCollection: process.env.MEMORY_COLLECTION ?? "dify_memory",
  dimension: Number(process.env.EMBED_DIMENSION ?? 384),
  distance: process.env.EMBED_DISTANCE ?? "l2",
  httpPort: Number(process.env.PORT ?? 8791),
  embedMode: process.env.EMBED_MODE ?? "local",
  modelId: process.env.EMBED_MODEL ?? "Xenova/all-MiniLM-L6-v2",
  modelMirror: process.env.MODEL_MIRROR ?? "https://hf-mirror.com",
  recallTopK: Number(process.env.RECALL_TOP_K ?? 3),
  candidateMultiplier: Number(process.env.CANDIDATE_MULTIPLIER ?? 6),
};

export function sanitizeQuery(text, limit = 512) {
  const raw = String(text ?? "");
  const stripped = raw
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/[\\'"]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return stripped.slice(0, limit);
}
const num = (value, fallback) => {
  const parsed = Number.parseInt(value ?? '', 10);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export const config = {
  host: process.env.SEEKDB_HOST ?? '127.0.0.1',
  port: num(process.env.SEEKDB_PORT, 2882),
  user: process.env.SEEKDB_USER ?? 'root',
  password: process.env.SEEKDB_PASSWORD ?? '',
  database: process.env.SEEKDB_DATABASE ?? 'stepfun_rag',
  collection: process.env.SEEKDB_COLLECTION ?? 'documents',
  dimension: num(process.env.EMBEDDING_DIMENSION, 384),
  distance: process.env.SEEKDB_DISTANCE ?? 'cosine',
  httpPort: num(process.env.PORT, 8787),
  modelMirror: process.env.MODEL_MIRROR ?? 'https://hf-mirror.com',
  batchSize: num(process.env.BATCH_SIZE, 32),
  maxTopK: num(process.env.MAX_TOP_K, 50),
};

export const collectionName = () => config.collection;
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import cors from 'cors';
import express from 'express';

import { config } from './config.js';
import { proxyModel, setUpstream, upstream } from './model-proxy.js';
import { close, collectionInfo, count, hybridSearch, resetLibrary, upsertDocuments } from './store.js';

const here = dirname(fileURLToPath(import.meta.url));
const webDist = join(here, '..', '..', 'web', 'dist');

const app = express();
app.use(cors());
app.use(express.json({ limit: '32mb' }));

const badRequest = (message) => Object.assign(new Error(message), { status: 400 });

const validateEmbedding = (value, field) => {
  if (!Array.isArray(value) || !value.length) {
    throw badRequest(`${field} must be a non-empty array of numbers`);
  }
  for (const item of value) {
    if (typeof item !== 'number' || !Number.isFinite(item)) {
      throw badRequest(`${field} must contain only finite numbers`);
    }
  }
  return value;
};

app.get('/api/health', async (_req, res, next) => {
  try {
    const info = await collectionInfo();
    res.json({ ok: true, backend: 'seekdb', ...info });
  } catch (error) {
    next(error);
  }
});

app.get('/api/stats', async (_req, res, next) => {
  try {
    res.json({ documents: await count() });
  } catch (error) {
    next(error);
  }
});

app.post('/api/documents', async (req, res, next) => {
  try {
    const records = req.body?.records;
    if (!Array.isArray(records) || !records.length) {
      throw badRequest('records must be a non-empty array');
    }
    const dimension = validateEmbedding(records[0]?.embedding, 'records[0].embedding').length;
    const prepared = records.map((record, index) => {
      if (typeof record?.id !== 'string' || !record.id) {
        throw badRequest(`records[${index}].id must be a non-empty string`);
      }
      const embedding = validateEmbedding(record.embedding, `records[${index}].embedding`);
      if (embedding.length !== dimension) {
        throw badRequest(`records[${index}].embedding has dimension ${embedding.length}, expected ${dimension}`);
      }
      if (typeof record.text !== 'string' || !record.text.trim()) {
        throw badRequest(`records[${index}].text must be a non-empty string`);
      }
      const metadata = record.metadata && typeof record.metadata === 'object' ? record.metadata : {};
      return { id: record.id, text: record.text, embedding, metadata };
    });
    const result = await upsertDocuments(prepared);
    res.json({ ok: true, dimension, ...result });
  } catch (error) {
    next(error);
  }
});

app.post('/api/reset', async (_req, res, next) => {
  try {
    res.json({ ok: true, ...(await resetLibrary()) });
  } catch (error) {
    next(error);
  }
});

app.post('/api/search', async (req, res, next) => {
  try {
    const text = typeof req.body?.text === 'string' ? req.body.text : '';
    const embedding = validateEmbedding(req.body?.embedding, 'embedding');
    const topK = Number(req.body?.topK ?? 5);
    const startedAt = process.hrtime.bigint();
    const hits = await hybridSearch({ text, embedding, topK });
    const elapsedMs = Number(process.hrtime.bigint() - startedAt) / 1e6;
    res.json({ ok: true, topK, elapsedMs, hits, statement: 'CALL DBMS_HYBRID_SEARCH(<collection>, <search_parm>)' });
  } catch (error) {
    next(error);
  }
});

app.get('/api/model', (_req, res) => {
  res.json({ ok: true, upstream: upstream() });
});

app.post('/api/model/source', (req, res, next) => {
  try {
    res.json({ ok: true, upstream: setUpstream(req.body?.host) });
  } catch (error) {
    next(error);
  }
});

// 浏览器同源取模型权重：/api/model/<path> → <mirror>/<path>
app.get('/api/model/*', async (req, res, next) => {
  try {
    await proxyModel(req.params[0], res);
  } catch (error) {
    next(error);
  }
});

if (existsSync(webDist)) {
  app.use(express.static(webDist));
}

app.use((error, _req, res, _next) => {
  const status = error?.status ?? 500;
  if (status >= 500) {
    console.error('[server]', error);
  }
  res.status(status).json({ ok: false, error: error?.message ?? 'internal error' });
});

const server = app.listen(config.httpPort, () => {
  console.log(`[server] listening on http://127.0.0.1:${config.httpPort}`);
  console.log(`[server] seekdb ${config.host}:${config.port} db=${config.database} collection=${config.collection}`);
});

const shutdown = async () => {
  server.close();
  await close();
  process.exit(0);
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
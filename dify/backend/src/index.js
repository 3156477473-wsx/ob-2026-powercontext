import express from "express";

import { config } from "./config.js";
import { embedOne, embeddingMode, warmup } from "./embed.js";
import * as store from "./store.js";

const app = express();
app.use(express.json({ limit: "256kb" }));
app.use((req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }
  next();
});

const asText = (value) => (typeof value === "string" ? value.trim() : "");
const fail = (res, status, message) => res.status(status).json({ ok: false, error: message });

// user_id 是记忆隔离的唯一键。做基本规整，避免：
//  - 超长值撑爆索引/日志
//  - 控制字符与空白导致的「同名不同键」
// 注意：这是格式规整，不是身份认证。本项目为单机演示，
//      生产场景应把 user_id 绑定到登录态（见 README「已知限制」）。
const MAX_USER_ID_LEN = 64;
function normalizeUserId(raw) {
  const text = asText(raw);
  if (!text) return "guest";
  const cleaned = text.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, MAX_USER_ID_LEN).trim();
  return cleaned || "guest";
}

function memoryBlock(memories) {
  if (!memories.length) {
    return "（这位客人是第一次来，还没有任何记忆）";
  }
  return memories.map((item) => `- ${item.fact}`).join("\n");
}

function loreBlock(lore) {
  if (!lore.length) {
    return "（今晚没有特别的酒单提示）";
  }
  return lore.map((item) => `- ${item.title ? `【${item.title}】` : ""}${item.text}`).join("\n");
}

app.get("/api/health", async (req, res) => {
  try {
    const s = await store.stats();
    res.json({ ok: true, service: "jiuguan-backend", embed_mode: embeddingMode(), ...s });
  } catch (error) {
    fail(res, 500, error.message);
  }
});

// POST 与 GET 共用：参数可来自 body 或 URL query，任一有值即可。
// Dify 的 HTTP 节点在不同版本里对 body/query 的渲染行为不一致，
// 这里同时接受两种来源，保证工作流能稳定跑通。
function pickInput(req, ...names) {
  for (const name of names) {
    const fromBody = asText(req.body?.[name]);
    if (fromBody) return fromBody;
    const fromQuery = asText(req.query?.[name]);
    if (fromQuery) return fromQuery;
  }
  return "";
}

async function recallHandler(req, res) {
  const userId = normalizeUserId(pickInput(req, "user_id"));
  const message = pickInput(req, "message", "query");
  if (!message) {
    fail(res, 400, "message 不能为空");
    return;
  }
  try {
    const embedding = await embedOne(message);
    const { lore, memories } = await store.recall({
      userId,
      message,
      embedding,
      topK: config.recallTopK,
    });
    res.json({
      ok: true,
      user_id: userId,
      embed_mode: embeddingMode(),
      memory_count: memories.length,
      lore_count: lore.length,
      memory_block: memoryBlock(memories),
      lore_block: loreBlock(lore),
      memories,
      lore,
    });
  } catch (error) {
    fail(res, 500, error.message);
  }
}

app.post("/api/recall", recallHandler);
app.get("/api/recall", recallHandler);

async function rememberHandler(req, res) {
  const userId = normalizeUserId(pickInput(req, "user_id"));
  const fact = pickInput(req, "fact");
  if (!fact) {
    fail(res, 400, "fact 不能为空");
    return;
  }
  try {
    const embedding = await embedOne(fact);
    const result = await store.remember({ userId, fact, embedding });
    res.json({ ok: true, user_id: userId, fact, ...result });
  } catch (error) {
    fail(res, 500, error.message);
  }
}

app.post("/api/remember", rememberHandler);
app.get("/api/remember", rememberHandler);

app.post("/api/reset", async (req, res) => {
  try {
    const result = await store.forgetAll();
    res.json({ ok: true, ...result });
  } catch (error) {
    fail(res, 500, error.message);
  }
});

app.use((req, res) => {
  fail(res, 404, `未知路径 ${req.path}`);
});

const server = app.listen(config.httpPort, config.httpHost, () => {
  console.log(`[server] listening on http://${config.httpHost}:${config.httpPort}`);
  console.log(`[server] seekdb ${config.host}:${config.port} db=${config.database}`);
  console.log(`[server] collections lore=${config.loreCollection} memory=${config.memoryCollection}`);
  warmup()
    .then((mode) => console.log(`[server] embedding mode=${mode}`))
    .catch((error) => console.warn(`[server] warmup failed: ${error.message}`));
});

const shutdown = async () => {
  server.close();
  await store.close();
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

export default app;
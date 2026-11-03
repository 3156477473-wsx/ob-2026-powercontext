import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { embedTexts, embeddingMode } from "./embed.js";
import * as store from "./store.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dataDir = process.env.DATA_DIR ?? path.join(root, "data");

async function loadJsonl(file) {
  const raw = await readFile(path.join(dataDir, file), "utf8");
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      try {
        return JSON.parse(line);
      } catch (error) {
        throw new Error(`${file} 第 ${index + 1} 行不是合法 JSON：${error.message}`);
      }
    });
}

async function seedLore() {
  const records = await loadJsonl("lore.jsonl");
  const embeddings = await embedTexts(records.map((record) => `${record.title} ${record.text}`));
  const result = await store.seedLore(
    records.map((record, index) => ({
      id: record.id,
      text: `${record.title}：${record.text}`,
      embedding: embeddings[index],
      metadata: { title: record.title, tags: record.tags ?? "", kind: "lore" },
    })),
  );
  console.log(`[seed] lore seeded=${result.seeded} count=${result.count} embed=${embeddingMode()}`);
}

async function seedMemory() {
  const records = await loadJsonl("seed_memory.jsonl");
  const embeddings = await embedTexts(records.map((record) => record.fact));
  const result = await store.seedMemory(
    records.map((record, index) => ({
      id: record.id,
      text: record.fact,
      embedding: embeddings[index],
      metadata: {
        user_id: record.user_id,
        fact: record.fact,
        source: "seed",
        created_at: record.created_at ?? new Date().toISOString(),
      },
    })),
  );
  console.log(`[seed] memory seeded=${result.seeded} count=${result.count}`);
}

const mode = process.argv[2] ?? "all";
try {
  if (mode === "lore" || mode === "all") await seedLore();
  if (mode === "memory" || mode === "all") await seedMemory();
  const stats = await store.stats();
  console.log(`[seed] stats lore=${stats.lore} memory=${stats.memory} dim=${stats.dimension}`);
} catch (error) {
  console.error(`[seed] failed: ${error.message}`);
  process.exitCode = 1;
} finally {
  await store.close();
}
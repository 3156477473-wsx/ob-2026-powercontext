import test from "node:test";
import assert from "node:assert/strict";

const DIMENSION = 384;
const COLLECTION = `test_${Date.now()}`;

process.env.SEEKDB_COLLECTION = COLLECTION;
process.env.SEEKB_DATABASE = process.env.SEEKB_DATABASE ?? "stepfun_test";

const store = await import("../src/store.js");

function vector(seed) {
  const out = new Array(DIMENSION).fill(0);
  out[seed % DIMENSION] = 1;
  out[(seed * 7 + 3) % DIMENSION] = 0.5;
  return out;
}

const records = [
  { id: "doc-1", text: "seekdb 混合检索 alpha", embedding: vector(1) },
  { id: "doc-2", text: "向量检索 beta", embedding: vector(2) },
  { id: "doc-3", text: "全文检索 gamma", embedding: vector(3) },
];

test("hybrid search fuses keyword and vector candidates", async (t) => {
  t.after(async () => {
    await store.resetLibrary();
    await store.close();
  });

  await store.upsertDocuments(records);
  const hits = await store.hybridSearch({ text: "alpha", embedding: vector(1), topK: 3 });

  assert.ok(hits.length > 0, "expected at least one hit");
  const ids = hits.map((hit) => hit.id);
  assert.equal(new Set(ids).size, ids.length, "ids must be unique");
  assert.ok(ids.includes("doc-1"), "keyword branch should surface doc-1");
  assert.equal(hits[0].text.length > 0, true, "documents must be included");
});

test("collection reset empties the library without breaking it", async (t) => {
  t.after(async () => {
    await store.resetLibrary();
    await store.close();
  });

  await store.upsertDocuments([records[0]]);
  const before = await store.collectionInfo();
  assert.equal(before.count, 1);

  await store.resetLibrary();
  const after = await store.collectionInfo();
  assert.equal(after.count, 0);

  await store.upsertDocuments([records[1]]);
  const again = await store.collectionInfo();
  assert.equal(again.count, 1);
});

test("keyword branch ranks the matching document first and topK bounds results", async (t) => {
  t.after(async () => {
    await store.resetLibrary();
    await store.close();
  });

  await store.upsertDocuments(records);
  const hits = await store.hybridSearch({ text: "gamma", embedding: vector(2), topK: 2 });

  const indexed = new Set(records.map((record) => record.id));
  assert.ok(hits.length > 0, "expected the keyword branch to contribute");
  assert.equal(hits.length <= 2, true, "topK must bound the result set");
  for (const hit of hits) {
    assert.ok(indexed.has(hit.id), `unexpected id ${hit.id}`);
  }
  assert.equal(hits[0].id, "doc-3", "the only document containing 'gamma' should rank first");
});
const BASE = (process.env.BACKEND_BASE_URL ?? "http://127.0.0.1:8791").replace(/\/+$/, "");

const rows = [];
let failed = 0;

function check(name, ok, detail) {
  rows.push({ name, ok: ok ? "PASS" : "FAIL", detail });
  if (!ok) failed += 1;
}

async function call(path, body) {
  const response = await fetch(`${BASE}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`${path} 返回非 JSON：${text.slice(0, 160)}`);
  }
  if (!response.ok) {
    throw new Error(`${path} HTTP ${response.status}: ${payload.error ?? text.slice(0, 160)}`);
  }
  return payload;
}

async function main() {
  const health = await call("/api/health");
  check("health", health.ok === true && health.lore > 0, `lore=${health.lore} memory=${health.memory} embed=${health.embed_mode}`);

  await call("/api/reset", {});
  const first = await call("/api/recall", {
    user_id: "smoke_a",
    message: "今天加班到十一点，老板还在群里发消息",
  });
  check("首次到店：无记忆", first.memory_count === 0, `memory_count=${first.memory_count}`);
  check("首次到店：命中酒馆设定", first.lore_count >= 1, `lore_count=${first.lore_count} 首条=${first.lore[0]?.title ?? "-"}`);

  const written = await call("/api/remember", {
    user_id: "smoke_a",
    fact: "最近连续加班到深夜，被老板在群里点名",
  });
  check("写入记忆", written.ok === true && written.count >= 1, `count=${written.count} id=${written.stored}`);

  const second = await call("/api/recall", { user_id: "smoke_a", message: "我又来了，老样子" });
  const recalled = second.memories.some((item) => String(item.fact).includes("加班"));
  check("新会话召回跨会话记忆", second.memory_count >= 1 && recalled, `memory_count=${second.memory_count} 首条=${second.memories[0]?.fact ?? "-"}`);

  const other = await call("/api/recall", { user_id: "smoke_b", message: "老样子" });
  check("用户隔离", other.memory_count === 0, `smoke_b memory_count=${other.memory_count}`);

  console.log("\n===== 验证样例执行结果 =====");
  for (const row of rows) {
    console.log(`${row.ok}  ${row.name}  (${row.detail})`);
  }
  console.log(`===== ${failed === 0 ? "全部通过" : `${failed} 项失败`} =====`);
  if (failed !== 0) process.exitCode = 1;
}

main().catch((error) => {
  console.error(`[smoke] 执行失败：${error.message}`);
  process.exitCode = 1;
});
#!/usr/bin/env bash
# 启动「深夜酒馆 · 阿九」后端（Express + seekdb）。
# 用法：bash scripts/start.sh
set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ ! -d node_modules ]; then
  echo "[start] 安装依赖（首次约 15 秒）"
  npm install --ignore-scripts --legacy-peer-deps --no-audit --no-fund \
    --registry="${NPM_REGISTRY:-https://registry.npmmirror.com}"
fi

echo "[start] 检查 seekdb ${SEEKDB_HOST:-127.0.0.1}:${SEEKDB_PORT:-2882}"
node -e '
import("seekdb").then(async ({ SeekdbClient }) => {
  const client = new SeekdbClient({
    host: process.env.SEEKDB_HOST ?? "127.0.0.1",
    port: Number(process.env.SEEKDB_PORT ?? 2882),
    user: process.env.SEEKDB_USER ?? "root",
    password: process.env.SEEKDB_PASSWORD ?? "",
  });
  await client.execute("SELECT 1");
  await client.close();
  console.log("[start] seekdb 可连接");
}).catch((error) => {
  console.error(`[start] seekdb 不可连接：${error.message}`);
  process.exit(1);
});
'

echo "[start] 初始化酒馆设定与示例记忆"
node src/seed.js all

echo "[start] 启动 HTTP 服务 http://127.0.0.1:${PORT:-8791}"
exec node src/index.js
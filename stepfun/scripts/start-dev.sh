#!/usr/bin/env bash
# 一键启动：检查 seekdb → 启动 Node 桥 → 启动 Vite。
# 用法：scripts/start-dev.sh [--check]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEEKDB_HOST="${SEEKDB_HOST:-127.0.0.1}"
SEEKDB_PORT="${SEEKDB_PORT:-2882}"
BRIDGE_PORT="${PORT:-8787}"
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

fail() {
  echo "[start-dev] $1" >&2
  exit 1
}

command -v node >/dev/null || fail "未找到 node（需要 Node.js >= 20）"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[[ "$NODE_MAJOR" -ge 20 ]] || fail "Node.js 版本过低：$(node -v)，需要 >= 20"

if ! (exec 3<>"/dev/tcp/${SEEKDB_HOST}/${SEEKDB_PORT}") 2>/dev/null; then
  fail "连不上 seekdb ${SEEKDB_HOST}:${SEEKDB_PORT}；请先启动：seekdb --nodaemon --base-dir=<dir> --port=${SEEKDB_PORT}"
fi
echo "[start-dev] seekdb 可连接 ${SEEKDB_HOST}:${SEEKDB_PORT}"

[[ -d "${ROOT}/server/node_modules" ]] || echo "[start-dev] 提示：server 依赖未安装，请先执行 cd server && npm install --legacy-peer-deps --omit=optional --ignore-scripts"
[[ -d "${ROOT}/web/node_modules" ]] || echo "[start-dev] 提示：web 依赖未安装，请先执行 cd web && npm install --ignore-scripts"

[[ "$CHECK_ONLY" -eq 1 ]] && { echo "[start-dev] 自检通过"; exit 0; }

cleanup() {
  trap - INT TERM EXIT
  [[ -n "${BRIDGE_PID:-}" ]] && kill "$BRIDGE_PID" 2>/dev/null
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null
}
trap cleanup INT TERM EXIT

(cd "$ROOT/server" && PORT="$BRIDGE_PORT" node src/index.js) &
BRIDGE_PID=$!
for _ in $(seq 1 30); do
  sleep 1
  curl -sf "http://127.0.0.1:${BRIDGE_PORT}/api/health" >/dev/null && break
done
curl -sf "http://127.0.0.1:${BRIDGE_PORT}/api/health" >/dev/null || fail "Node 桥启动失败，检查 ${BRIDGE_PORT} 端口"
echo "[start-dev] Node 桥就绪 http://127.0.0.1:${BRIDGE_PORT}"

cd "$ROOT/web"
npm run dev &
WEB_PID=$!
echo "[start-dev] 前端启动中：http://127.0.0.1:5173（Ctrl+C 退出）"
wait "$WEB_PID"
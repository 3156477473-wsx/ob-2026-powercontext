#!/usr/bin/env bash
# 执行验证样例并把输出留档到 samples/evidence/smoke.log
# 用法：bash scripts/verify.sh
# 若设定库为空（例如刚复制仓库、还没跑过 seed），会先自动灌入语料，保证样例可复现。
set -euo pipefail
cd "$(dirname "$0")/../backend"
EVIDENCE=../samples/evidence
mkdir -p "$EVIDENCE"
export BACKEND_BASE_URL="${BACKEND_BASE_URL:-http://127.0.0.1:8791}"
echo "[verify] backend=${BACKEND_BASE_URL}"

lore_count() {
  curl -s "${BACKEND_BASE_URL}/api/health" | node -e '
let raw = "";
process.stdin.on("data", (chunk) => (raw += chunk));
process.stdin.on("end", () => {
  try {
    process.stdout.write(String(JSON.parse(raw).lore ?? 0));
  } catch {
    process.stdout.write("0");
  }
});
'
}

if [ "$(lore_count)" = "0" ]; then
  echo "[verify] 设定库为空，先灌入 22 条酒馆设定"
  node src/seed.js lore
fi

node src/smoke.js | tee "$EVIDENCE/smoke.log"
echo
echo "[verify] 健康检查原始响应："
curl -s "${BACKEND_BASE_URL}/api/health" | tee "$EVIDENCE/health.json"
echo
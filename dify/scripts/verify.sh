#!/usr/bin/env bash
# 执行验证样例并把输出留档到 samples/evidence/smoke.log
# 用法：bash scripts/verify.sh
set -euo pipefail
cd "$(dirname "$0")/../backend"
EVIDENCE=../samples/evidence
mkdir -p "$EVIDENCE"
export BACKEND_BASE_URL="${BACKEND_BASE_URL:-http://127.0.0.1:8791}"
echo "[verify] backend=${BACKEND_BASE_URL}"
node src/smoke.js | tee "$EVIDENCE/smoke.log"
echo
echo "[verify] 健康检查原始响应："
curl -s "${BACKEND_BASE_URL}/api/health" | tee "$EVIDENCE/health.json"
echo
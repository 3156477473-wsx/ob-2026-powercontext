#!/bin/bash
# 端到端验证：索引 → 上下文 → 测试(前) → 保存状态 → 重启 → 复用 → 测试(后)
set +e
export PATH="$HOME/.local/bin:$PATH"
WORK="$HOME/minimax-task"
SRC="/mnt/d/Ocean base/ob-2026-powercontext/minimax"

rm -rf "$WORK/ctx" "$WORK/business" "$WORK/business-after"
cp -r "$SRC/ctx" "$WORK/"
cp -r "$SRC/business" "$WORK/"
cd "$WORK"
. .venv/bin/activate
uv pip install --index-url https://mirrors.aliyun.com/pypi/simple/ pymysql requests pytest 2>&1 | tail -2

TASK="为任务列表增加按创建时间范围过滤的功能，需要改哪些代码和测试"

echo "############ 1. 索引工程资料 ############"
python -m ctx.cli index --project business 2>&1 | tail -8

echo ""
echo "############ 2. 构造任务上下文 ############"
python -m ctx.cli build --task "$TASK" --top-k 3 \
  | python -c "
import json,sys
d=json.load(sys.stdin)
print('规格:', [s['symbol'] for s in d['specs']])
print('代码:', [c['symbol'] for c in d['code']])
print('测试:', [t['symbol'] for t in d['tests']])
print('seekdb:', d['sources']['seekdb'])
print('pc scope:', d['sources']['powercontext']['scope_id'])
"

echo ""
echo "############ 3. 修改前测试 ############"
cd business
echo "--- 回归 ---"
python -m pytest tests/test_regression.py -q 2>&1 | tail -2
echo "--- 目标（应失败）---"
python -m pytest tests/test_time_filter.py -q 2>&1 | tail -3
cd ..

echo ""
echo "############ 4. 保存任务状态 ############"
python -m ctx.cli save \
  --task "为任务列表增加按创建时间范围过滤" \
  --summary "SPEC-005 时间范围过滤" \
  --status in_progress \
  --done "已索引规格/代码/测试，已生成上下文" \
  --todo "等待 MiniMax 生成修改并跑测试" 2>&1 | tail -6

echo ""
echo "############ 5. 重启上下文模块（新进程）后复用状态 ############"
python -m ctx.cli resume --task "时间范围过滤" 2>&1 | head -20

echo ""
echo "############ 6. 应用参考实现后测试 ############"
rm -rf business-after && cp -r business business-after
cp business/reference/task_service_spec005.py business-after/src/task_service.py
cd business-after
python -m pytest tests -q 2>&1 | tail -3

echo ""
echo "############ 7. 数据库证据 ############"
docker exec seekdb mysql -h127.0.0.1 -P2881 -uroot -e \
  "SELECT doc_type, COUNT(*) n FROM test.eng_docs GROUP BY doc_type;" 2>&1
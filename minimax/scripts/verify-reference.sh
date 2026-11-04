#!/bin/bash
# 验证：参考实现可让目标测试全部通过
set +e
export PATH="$HOME/.local/bin:$PATH"
WORK="$HOME/minimax-task"
SRC="/mnt/d/Ocean base/ob-2026-powercontext/minimax/business"

cd "$WORK"
rm -rf business-after
cp -r "$SRC" business-after
cd business-after

# 用参考实现替换目标文件
cp reference/task_service_spec005.py src/task_service.py

echo "=== 修改后：回归测试 ==="
"$WORK/.venv/bin/python" -m pytest tests/test_regression.py -q 2>&1 | tail -6

echo ""
echo "=== 修改后：目标测试 ==="
"$WORK/.venv/bin/python" -m pytest tests/test_time_filter.py -q 2>&1 | tail -8

echo ""
echo "=== 全部测试 ==="
"$WORK/.venv/bin/python" -m pytest tests -q 2>&1 | tail -5
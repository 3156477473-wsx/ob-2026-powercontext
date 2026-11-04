#!/bin/bash
# 运行测试：记录修改前状态
set +e
export PATH="$HOME/.local/bin:$PATH"

WORK="$HOME/minimax-task"
BUS="/mnt/d/Ocean base/ob-2026-powercontext/minimax/business"

mkdir -p "$WORK"
cd "$WORK"

rm -rf business
cp -r "$BUS" business
cd business

echo "=== 用 uv 安装 pytest ==="
uv pip install --python "$WORK/.venv/bin/python" --index-url https://mirrors.aliyun.com/pypi/simple/ pytest 2>&1 | tail -3

echo ""
echo "=== 回归测试（应全部通过）==="
"$WORK/.venv/bin/python" -m pytest tests/test_regression.py -q 2>&1 | tail -8
RC1=$?
echo "回归测试退出码: $RC1"

echo ""
echo "=== 目标测试（修改前应失败）==="
"$WORK/.venv/bin/python" -m pytest tests/test_time_filter.py -q 2>&1 | tail -18
RC2=$?
echo "目标测试退出码: $RC2"
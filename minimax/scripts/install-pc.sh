#!/bin/bash
# 在独立 venv 中安装 PowerContext 1.5.0
set -e

export PATH="$HOME/.local/bin:$PATH"
export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORK="$HOME/minimax-task"
mkdir -p "$WORK"
cd "$WORK"

echo "=== 用 Python 3.11 创建 venv ==="
if [ ! -d .venv ]; then
    uv venv --python 3.11 .venv
fi
. .venv/bin/activate
python --version

echo ""
echo "=== 安装 powercontext[cli,server]==1.5.0 ==="
uv pip install --index-url https://mirrors.aliyun.com/pypi/simple/ \
    "powercontext[cli,server]==1.5.0" 2>&1 | tail -12

echo ""
echo "=== 验证 ==="
powercontext --version 2>&1 || echo "powercontext 命令不可用"
which powercontext
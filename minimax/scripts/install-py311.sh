#!/bin/bash
# 用 uv 安装 Python 3.11
set -e

export PATH="$HOME/.local/bin:$PATH"
export UV_PYTHON_INSTALL_MIRROR=https://mirrors.aliyun.com/python-build-standalone/releases/download

echo "=== uv 版本 ==="
~/.local/bin/uv --version

echo ""
echo "=== 安装 Python 3.11 ==="
~/.local/bin/uv python install 3.11 2>&1 | tail -10

echo ""
echo "=== 已安装的 Python ==="
~/.local/bin/uv python list 2>&1 | head -10

echo ""
echo "=== 3.11 路径 ==="
PY311=$(~/.local/bin/uv python find 3.11 2>/dev/null || echo "")
if [ -n "$PY311" ]; then
  echo "路径: $PY311"
  $PY311 --version
else
  echo "未找到 3.11"
fi
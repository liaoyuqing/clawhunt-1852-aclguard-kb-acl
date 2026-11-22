#!/usr/bin/env bash
# 干净副本自检：把除 .venv / 缓存 / 产物 以外的文件复制到临时目录，在那里跑完整测试与指标。
# 目的：证明测试不依赖原目录残留（等价于干净 clone）。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON_BIN:-$ROOT/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then PY="$(command -v python)"; fi
TMP="$(mktemp -d)"
echo "[1/4] copy -> $TMP"
cd "$ROOT"
for item in aclguard tests fixtures scripts README.md pytest.ini; do
  [ -e "$item" ] && cp -r "$item" "$TMP"/
done
mkdir -p "$TMP/reports"
echo "[2/4] pytest in clean dir"
cd "$TMP" && PYTHONIOENCODING=utf-8 "$PY" -m pytest -q
PYTEST_EXIT=$?
echo "pytest EXIT=$PYTEST_EXIT"
echo "[3/4] metrics in clean dir"
PYTHONIOENCODING=utf-8 "$PY" scripts/collect_metrics.py > /dev/null
METRICS_EXIT=$?
echo "metrics EXIT=$METRICS_EXIT"
echo "[4/4] tree listing"
find . -type f -not -path "./.venv/*" -not -path "*/__pycache__/*" | sort
rm -rf "$TMP"
[ "$PYTEST_EXIT" -eq 0 ] && [ "$METRICS_EXIT" -eq 0 ]
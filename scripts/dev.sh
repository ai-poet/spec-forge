#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${SPECFORGE_PYTHON:-python}"

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "SpecForge requires Python 3.12+. Activate a 3.12 environment or set SPECFORGE_PYTHON." >&2
  exit 1
fi

if [[ -d "$ROOT_DIR/backend/.venv" ]] && ! "$ROOT_DIR/backend/.venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
  rm -rf "$ROOT_DIR/backend/.venv"
fi

if [[ ! -d "$ROOT_DIR/backend/.venv" ]]; then
  "$PYTHON_BIN" -m venv "$ROOT_DIR/backend/.venv"
fi

source "$ROOT_DIR/backend/.venv/bin/activate"
python -m pip install -q --upgrade pip setuptools wheel
pip install -q -e "$ROOT_DIR/backend"[dev]

if [[ "${SPECFORGE_SKIP_UI:-}" != "1" ]]; then
  if command -v npx >/dev/null 2>&1; then
    npx --yes --package @playwright/cli playwright-cli install-browser || \
      echo "warn: playwright-cli browser install failed (Web UI Agent may warn)" >&2
  else
    echo "warn: npx not found; install Node.js for playwright-cli Web UI verification" >&2
  fi
else
  echo "Skipping playwright-cli setup (SPECFORGE_SKIP_UI=1)." >&2
fi

if [[ "${SPECFORGE_SKIP_CUA:-}" != "1" ]]; then
  if [[ -f "$ROOT_DIR/computer-use/backend/install_cua_driver.py" ]]; then
    python "$ROOT_DIR/computer-use/backend/install_cua_driver.py" || \
      echo "warn: cua-driver install failed (native / text-based Web UI may be skipped)" >&2
  else
    echo "warn: computer-use/install_cua_driver.py not found; skipping CuaDriver install" >&2
  fi
else
  echo "Skipping CuaDriver install (SPECFORGE_SKIP_CUA=1)." >&2
fi

if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  (cd "$ROOT_DIR/frontend" && npm install)
fi

trap 'kill 0' EXIT

(cd "$ROOT_DIR/backend" && uvicorn specforge.main:app --reload --port 8787) &
(cd "$ROOT_DIR/frontend" && npm run dev) &

wait

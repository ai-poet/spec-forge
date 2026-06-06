#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${SPECFORGE_PYTHON:-python}"
CODEX_SDK_REQUIREMENT="openai-codex>=0.1.0b2"

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
if ! python -m pip --version >/dev/null 2>&1; then
  echo "Bootstrapping pip into backend/.venv..."
  python -m ensurepip --upgrade
fi
python -m pip install -q --upgrade pip setuptools wheel
if [[ "${SPECFORGE_SKIP_UI:-}" != "1" ]]; then
  pip install -q -e "$ROOT_DIR/backend[dev,ui]"
else
  pip install -q -e "$ROOT_DIR/backend[dev]"
fi

ensure_codex_sdk_dep() {
  if python -c 'import importlib.util; raise SystemExit(0 if importlib.util.find_spec("openai_codex") else 1)' >/dev/null 2>&1; then
    return 0
  fi

  echo "Installing missing Codex SDK dependency ($CODEX_SDK_REQUIREMENT)..."
  if python -m pip --version >/dev/null 2>&1; then
    python -m pip install -q "$CODEX_SDK_REQUIREMENT"
  elif python -m ensurepip --upgrade >/dev/null 2>&1; then
    python -m pip install -q "$CODEX_SDK_REQUIREMENT"
  elif command -v uv >/dev/null 2>&1; then
    (cd "$ROOT_DIR/backend" && uv pip install --python "$ROOT_DIR/backend/.venv/bin/python" "$CODEX_SDK_REQUIREMENT")
  else
    echo "Codex SDK is missing and neither pip nor uv is available to install it." >&2
    return 1
  fi

  python -c 'import importlib.util; raise SystemExit(0 if importlib.util.find_spec("openai_codex") else 1)'
}

ensure_codex_sdk_dep

if [[ "${SPECFORGE_SKIP_UI:-}" != "1" ]]; then
  python -m playwright install chromium || \
    echo "warn: Python Playwright browser install failed (Web UI smoke may warn)" >&2
  if command -v npx >/dev/null 2>&1; then
    npx --yes --package @playwright/cli playwright-cli install-browser || \
      echo "warn: playwright-cli browser install failed (Web UI Agent may warn)" >&2
  else
    echo "warn: npx not found; install Node.js for playwright-cli Web UI verification" >&2
  fi
else
  echo "Skipping UI automation setup (SPECFORGE_SKIP_UI=1)." >&2
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

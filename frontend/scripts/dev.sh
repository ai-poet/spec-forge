#!/usr/bin/env bash
set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$(cd "$FRONTEND_DIR/.." && pwd)"
CODEX_SDK_REQUIREMENT="openai-codex>=0.1.0b2"

is_py312_plus() {
  local bin="$1"
  [[ -n "$bin" ]] && command -v "$bin" >/dev/null 2>&1 || return 1
  "$bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null
}

discover_python() {
  # 1. Honor explicit override.
  if [[ -n "${SPECFORGE_PYTHON:-}" ]]; then
    if is_py312_plus "$SPECFORGE_PYTHON"; then
      echo "$SPECFORGE_PYTHON"
      return 0
    fi
    echo "SPECFORGE_PYTHON='$SPECFORGE_PYTHON' is not Python 3.12+." >&2
    return 1
  fi

  # 2. Reuse an existing 3.12+ venv if it's already there.
  local venv_py="$ROOT_DIR/backend/.venv/bin/python"
  if is_py312_plus "$venv_py"; then
    echo "$venv_py"
    return 0
  fi

  # 3. Common interpreter names on PATH.
  local candidate
  for candidate in python3.14 python3.13 python3.12 python3 python; do
    if is_py312_plus "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done

  # 4. uv can find or install a suitable Python without touching system state.
  if command -v uv >/dev/null 2>&1; then
    local uv_python
    uv_python="$(uv python find '>=3.12' 2>/dev/null || true)"
    if is_py312_plus "$uv_python"; then
      echo "$uv_python"
      return 0
    fi
    echo "Installing Python 3.12 via uv..." >&2
    if uv python install 3.12 >&2; then
      uv_python="$(uv python find '>=3.12' 2>/dev/null || true)"
      if is_py312_plus "$uv_python"; then
        echo "$uv_python"
        return 0
      fi
    fi
  fi

  # 5. conda envs (Anaconda/Miniconda) — pick the first env whose python is 3.12+.
  local conda_base=""
  if command -v conda >/dev/null 2>&1; then
    conda_base="$(conda info --base 2>/dev/null || true)"
  fi
  if [[ -n "$conda_base" && -d "$conda_base/envs" ]]; then
    local env_py
    for env_py in "$conda_base"/envs/*/bin/python; do
      if is_py312_plus "$env_py"; then
        echo "$env_py"
        return 0
      fi
    done
  fi

  return 1
}

if ! PYTHON_BIN="$(discover_python)"; then
  cat >&2 <<'EOF'
SpecForge requires Python 3.12+, but none was found.

Tried (in order):
  1. $SPECFORGE_PYTHON
  2. backend/.venv
  3. python3.14 / python3.13 / python3.12 / python3 / python on PATH
  4. uv (auto-install)
  5. conda envs

Fix options:
  - brew install python@3.12        # then re-run
  - uv python install 3.12          # then re-run
  - SPECFORGE_PYTHON=/path/to/py3.12 npm run dev:all
EOF
  exit 1
fi

echo "Using Python: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

# Drop a stale venv that points at an older Python.
if [[ -d "$ROOT_DIR/backend/.venv" ]] && ! is_py312_plus "$ROOT_DIR/backend/.venv/bin/python"; then
  echo "Recreating backend/.venv (existing one is not Python 3.12+)..."
  rm -rf "$ROOT_DIR/backend/.venv"
fi

ensure_backend_deps() {
  if command -v uv >/dev/null 2>&1; then
    echo "Syncing backend dependencies with uv..."
    if [[ "${SPECFORGE_SKIP_UI:-}" != "1" ]]; then
      (cd "$ROOT_DIR/backend" && uv sync --extra dev --extra ui)
    else
      (cd "$ROOT_DIR/backend" && uv sync --extra dev)
    fi
    return 0
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
}

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

ensure_backend_deps
source "$ROOT_DIR/backend/.venv/bin/activate"
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

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  (cd "$FRONTEND_DIR" && npm install)
fi

free_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  [[ -z "$pids" ]] && return 0
  echo "Port $port is in use by PID(s): $pids — terminating..."
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    sleep 0.3
    pids="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    [[ -z "$pids" ]] && return 0
  done
  echo "Port $port still in use — sending SIGKILL to: $pids"
  # shellcheck disable=SC2086
  kill -9 $pids 2>/dev/null || true
  sleep 0.3
}

free_port 8787
free_port 5178

trap 'kill 0' EXIT

echo "Starting backend on http://127.0.0.1:8787"
echo "Starting frontend on http://127.0.0.1:5178"

(cd "$ROOT_DIR/backend" && uvicorn specforge.main:app --reload --port 8787) &
(cd "$FRONTEND_DIR" && npm run dev) &

wait

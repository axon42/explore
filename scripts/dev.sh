#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo 'uv is required. Install it: https://docs.astral.sh/uv/getting-started/installation/'; exit 1; }
node -e 'const [major,minor]=process.versions.node.split(".").map(Number); if(major<22 || (major===22 && minor<12)) { console.error("Node 22.12+ required; run nvm use if available."); process.exit(1); }'
uv sync --project backend --locked
if [[ ! -d frontend/node_modules ]]; then npm --prefix frontend ci; fi
# Python reads .env as data, never shell code. Children receive the same effective settings.
exec uv run --project backend python scripts/dev.py

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
exec uv run --env-file ../.env -- python -m app.replay "$@"

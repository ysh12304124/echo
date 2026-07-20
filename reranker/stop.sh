#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [[ ! -f log/reranker.pid ]]; then
  echo "reranker is not running"
  exit 0
fi

pid="$(cat log/reranker.pid)"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
fi
rm -f log/reranker.pid
echo "reranker stopped"

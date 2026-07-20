#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
pid_file="log/clip.pid"
if [[ ! -f "$pid_file" ]]; then
  echo "clip service is not running"
  exit 0
fi

pid="$(cat "$pid_file")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
fi
rm -f "$pid_file"

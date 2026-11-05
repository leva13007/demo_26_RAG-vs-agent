#!/usr/bin/env bash
# Агент-гравець: Claude Code з Grep/Glob/Read у папці corpus/
# ./agent/ask.sh "питання"            — дивитися кроки агента наживо
# ./agent/ask.sh "питання" --json     — фінальний JSON (для арени)
set -euo pipefail
Q="${1:?Usage: ./agent/ask.sh \"питання\" [--json]}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEM="$(cat "$ROOT/agent/system.md")"

FLAGS=(
  -p "$Q"
  --model "${MODEL:-sonnet}"
  --tools "Grep,Glob,Read"   # без --allowedTools: читання лише всередині corpus/, решту Claude Code відхиляє
  --system-prompt "$SYSTEM"
  --disable-slash-commands --strict-mcp-config --setting-sources ""
  --no-session-persistence
  --max-budget-usd "${BUDGET:-0.5}"
)

cd "$ROOT/corpus"

if [[ "${2:-}" == "--json" ]]; then
  claude "${FLAGS[@]}" --output-format json < /dev/null
else
  claude "${FLAGS[@]}" --output-format stream-json --verbose < /dev/null | jq -r '
    if .type=="system" and .subtype=="init" then "🤖 \(.model)"
    elif .type=="assistant" then
      (.message.content[] |
        if .type=="tool_use" then "🔧 \(.name) \(.input|tostring|.[0:160])"
        elif .type=="text" then "💬 \(.text)"
        else empty end)
    elif .type=="result" then
      "\n⏱  \(.duration_ms/1000) s · кроків \(.num_turns) · tokens in \((.usage.input_tokens//0)+(.usage.cache_read_input_tokens//0)+(.usage.cache_creation_input_tokens//0)) / out \(.usage.output_tokens//0) · ~$\(.total_cost_usd)"
    else empty end'
fi

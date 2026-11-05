#!/usr/bin/env bash
# Гібрид: агент з Grep/Glob/Read + semantic_search (RAG як інструмент через MCP)
# ./hybrid/ask.sh "питання"          — дивитися кроки наживо
# ./hybrid/ask.sh "питання" --json   — фінальний JSON (для арени)
set -euo pipefail
Q="${1:?Usage: ./hybrid/ask.sh \"питання\" [--json]}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEM="$(cat "$ROOT/agent/system.md")"   # той самий промпт, що в агента — різниця лише в інструменті

# MCP-конфіг з абсолютними шляхами (генеруємо на льоту)
MCP_CONFIG="$(mktemp -t mcp-rag.XXXXXX).json"
trap 'rm -f "$MCP_CONFIG"' EXIT
cat > "$MCP_CONFIG" <<JSON
{
  "mcpServers": {
    "rag": {
      "command": "$(command -v node)",
      "args": ["$ROOT/hybrid/mcp-rag.ts"],
      "env": { "RAG_INDEX": "$ROOT/rag/index" }
    }
  }
}
JSON

FLAGS=(
  -p "$Q"
  --model "${MODEL:-sonnet}"
  --tools "Grep,Glob,Read"
  --allowedTools "mcp__rag__semantic_search"   # читання лише всередині corpus/, решту Claude Code відхиляє
  --mcp-config "$MCP_CONFIG" --strict-mcp-config
  --system-prompt "$SYSTEM"
  --disable-slash-commands --setting-sources ""
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
        if .type=="tool_use" then "🔧 \(.name|sub("mcp__rag__";"🧠 ")) \(.input|tostring|.[0:160])"
        elif .type=="text" then "💬 \(.text)"
        else empty end)
    elif .type=="result" then
      "\n⏱  \(.duration_ms/1000) s · кроків \(.num_turns) · tokens in \((.usage.input_tokens//0)+(.usage.cache_read_input_tokens//0)+(.usage.cache_creation_input_tokens//0)) / out \(.usage.output_tokens//0) · ~$\(.total_cost_usd)"
    else empty end'
fi

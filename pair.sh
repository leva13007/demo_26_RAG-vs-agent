#!/usr/bin/env bash
# ./pair.sh <N>  — питання №N з questions.txt: RAG → Agent → Hybrid.
# Вивід дублюється в results/QN_rag.txt і results/QN_agent.txt, results/QN_hybrid.txt
set -euo pipefail
cd "$(dirname "$0")"
N="${1:?Usage: ./pair.sh <номер питання 1..$(wc -l < questions.txt | tr -d " ")>}"
Q="$(sed -n "${N}p" questions.txt)"
[[ -z "$Q" ]] && { echo "Немає питання №$N у questions.txt"; exit 1; }
mkdir -p results
echo "════════ Q$N: $Q"
echo; echo "──────── RAG"
node rag/ask.ts "$Q" | tee "results/Q${N}_rag.txt"
echo; echo "──────── AGENT"
./agent/ask.sh "$Q" | tee "results/Q${N}_agent.txt"
echo; echo "──────── HYBRID (agent + semantic_search)"
./hybrid/ask.sh "$Q" | tee "results/Q${N}_hybrid.txt"

---
status: active
category: community
stack: Node.js, TypeScript, Ollama (bge-m3), Claude Code, Python
---

# demo_26 — RAG vs AI agent

Демо для стріму [IT Friday #026](https://youtube.com/live/aSMQZ5RQU3Q): троє гравців відповідають на ті самі питання по 25 розшифровках стрімів (58 годин), і ми порівнюємо якість, ціну й швидкість.

| Гравець | Як шукає | Запуск |
|---|---|---|
| RAG | Ембединги bge-m3, top-8, відповідь лише по цих фрагментах | `node rag/ask.ts "питання"` |
| Agent | Claude Code з Grep, Glob, Read у `corpus/`, без індексу | `./agent/ask.sh "питання"` |
| Hybrid | Той самий агент + `semantic_search` через MCP | `./hybrid/ask.sh "питання"` |

## Що де

```
corpus/      розшифровки, єдине джерело даних
rag/         RAG: ingest.ts, ask.ts, lib.ts, індекси (index*/ не в git)
agent/       Agent і спільний system.md
hybrid/      Hybrid і MCP-сервер mcp-rag.ts
arena/       керування експериментом: live.py, судді, еталони, звіти, тюнінг
results/     логи базового прогону
raw/         сирі субтитри (не в git)
vtt2md.ts    raw/ → corpus/
```

## Запуск

Потрібні: Node 23.6+, Python 3, `jq`, [Claude Code](https://claude.com/claude-code), Ollama з `ollama pull bge-m3`.

```bash
node rag/ingest.ts                 # побудувати індекс, ~2 хв, індекс не в git

cd arena
./live.py run 6                    # питання №6: троє паралельно + суддя + таблиця
./live.py show 6                   # відповіді й еталон
./live.py run air --reps 3         # ефірний набір, тричі
node eval_retrieval.ts --k 15      # тюнінг пошуку, без LLM, безкоштовно
```

## Ізоляція

Agent і Hybrid запускаються в `corpus/` і не можуть читати нічого за її межами, зокрема `arena/gold.json` з еталонами. Це забезпечує сам Claude Code: читання поза робочою папкою в режимі `-p` без явного дозволу відхиляється. Тому **не додавай `Read` або `Grep` у `--allowedTools`**: саме це раніше відкривало доступ. Додатково є правило в `agent/system.md`, але воно лише страховка.

## Обмеження

Це лабораторія, а не сервіс. Базовий прогон із `results/` зроблено до додавання ізоляції. Деталі, результати і застереження в документах стріму: `it_community_stuff/streams/026/`.

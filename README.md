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

## Прогін з іншою моделлю

Моделей дві, і міняються вони по-різному: **модель відповіді** пише текст, **модель ембедингів** шукає фрагменти.

### Модель відповіді: без переіндексації

Одна змінна `MODEL` перемикає всіх трьох гравців. Значення: псевдонім Claude Code (`haiku`, `sonnet`, `opus`) або точна назва (`claude-haiku-5-5`). За замовчуванням `sonnet`.

```bash
cd arena

# 1. Прогін: окремий --id, щоб не змішати з іншими моделями
MODEL=haiku ./live.py run air --id haiku

# 2. Перевірити, що модель справді та: кожен лог починається з 🤖
grep -h '🤖' runs/haiku/*.txt | sort | uniq -c

# 3. Подивитись відповіді й виправити бали, де суддя помилився
./live.py show 6 --id haiku
./live.py score 6 rag 1 --id haiku

# 4. Порівняти з основним прогоном
./live.py table --id haiku
./live.py table --id live
```

Звіт: `runs/haiku/report.html`. Один гравець окремо:

```bash
MODEL=haiku ./agent/ask.sh "питання"
MODEL=haiku ./hybrid/ask.sh "питання"
node rag/ask.ts "питання" --model haiku
```

Суддю міняє окрема змінна: `JUDGE_MODEL=sonnet ./live.py run 6`. Щоб порівнювати гравців чесно, суддя між прогонами має лишатись той самий.

Працюють лише моделі Claude: усі гравці запускаються через Claude Code.

### Модель ембедингів: потрібна переіндексація

Вектори різних моделей не порівнюються, тому нова модель означає новий індекс, ~2–3 хв. Спершу міряємо тільки пошук, це безкоштовно і без LLM:

```bash
# 1. Завантажити модель
ollama pull embeddinggemma

# 2. Побудувати окремий індекс, основний не чіпаємо
EMBED_MODEL=embeddinggemma node rag/ingest.ts --out rag/index-gemma

# 3. Порівняти якість пошуку з основним індексом
cd arena
node eval_retrieval.ts
EMBED_MODEL=embeddinggemma node eval_retrieval.ts --index rag/index-gemma
```

Якщо результат вартий уваги, можна подивитись на повну відповідь RAG:

```bash
EMBED_MODEL=embeddinggemma node rag/ask.ts "питання" --index rag/index-gemma
```

⚠ **`EMBED_MODEL` при пошуку має збігатися з моделлю індексу.** Код цього не перевіряє: при розбіжності помилки не буде, лише сміття у видачі. Модель індексу показує рядок 🔎 в `rag/ask.ts` та `jq .model rag/index-gemma/chunks.json`.

⚠ **`live.py` і Hybrid завжди працюють з `rag/index`.** Не задавай `EMBED_MODEL` разом із `live.py`. Щоб прогнати всіх трьох на іншій моделі ембедингів, треба перебудувати сам `rag/index`, а старий спершу зберегти під іншою назвою.

Деякі моделі просять префікс перед запитом: `eval_retrieval.ts --query-prefix "task: search result | query: "`. Префікси для документів `ingest.ts` не підтримує.

## Ізоляція

Agent і Hybrid запускаються в `corpus/` і не можуть читати нічого за її межами, зокрема `arena/gold.json` з еталонами. Це забезпечує сам Claude Code: читання поза робочою папкою в режимі `-p` без явного дозволу відхиляється. Тому **не додавай `Read` або `Grep` у `--allowedTools`**: саме це раніше відкривало доступ. Додатково є правило в `agent/system.md`, але воно лише страховка.

## Обмеження

Це лабораторія, а не сервіс. Базовий прогон із `results/` зроблено до додавання ізоляції. Деталі, результати і застереження в документах стріму: `it_community_stuff/streams/026/`.

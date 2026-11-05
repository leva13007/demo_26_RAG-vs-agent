// mcp-rag.ts — мінімальний MCP-сервер (stdio, без SDK), що дає агенту інструмент semantic_search
//
// Протокол MCP = JSON-RPC 2.0, одне повідомлення на рядок через stdin/stdout.
// Claude Code запускає цей процес сам (через --mcp-config) і спілкується з ним так:
//   → initialize               ← які можливості має сервер
//   → notifications/initialized  (без відповіді)
//   → tools/list               ← опис інструментів (name, description, inputSchema)
//   → tools/call               ← результат виклику
// ВАЖЛИВО: у stdout — тільки JSON-RPC. Будь-які логи — в stderr.
//
// Env: RAG_INDEX (default ../rag/index відносно цього файлу), OLLAMA_URL, EMBED_MODEL
import { createInterface } from "node:readline";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { embed, dot, loadIndex, fmt, modelMismatch } from "../rag/lib.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const INDEX = process.env.RAG_INDEX ?? join(HERE, "..", "rag", "index");
const { meta, vectors } = loadIndex(INDEX); // 16 МБ, вантажимо один раз при старті
const log = (...a: unknown[]) => console.error("[mcp-rag]", ...a);
log(`index loaded: ${meta.chunks.length} chunks from ${INDEX}`);

const TOOL = {
  name: "semantic_search",
  description:
    "Семантичний пошук по транскриптах стрімів (ембединги bge-m3). Знаходить фрагменти за ЗМІСТОМ, " +
    "навіть якщо в тексті інші слова або помилки розпізнавання. Повертає ім'я файлу, таймкод, назву стріму " +
    "і текст фрагмента (~75 с). Для точних деталей можна потім прочитати файл біля цього таймкоду.",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "Що шукати, своїми словами" },
      k: { type: "number", description: "Скільки фрагментів повернути (1–20, за замовчуванням 8)" },
    },
    required: ["query"],
  },
};

async function semanticSearch(query: string, k = 8): Promise<string> {
  // Падаємо на виклику, а не на старті: інакше Claude Code тихо запустив би агента без цього інструмента
  const mismatch = modelMismatch(meta, INDEX);
  if (mismatch) throw new Error(mismatch);
  const K = Math.min(Math.max(Math.round(k), 1), 20);
  const [qv] = await embed([query]);
  const top = vectors
    .map((v, i) => ({ i, score: dot(qv, v) }))
    .sort((a, b) => b.score - a.score)
    .slice(0, K);
  return top
    .map(({ i, score }, n) => {
      const c = meta.chunks[i];
      return `[${n + 1}] ${c.file} [${fmt(c.start)}–${fmt(c.end)}] score=${score.toFixed(3)}\nСтрім: ${c.title}\n${c.text}`;
    })
    .join("\n\n");
}

type Msg = { jsonrpc: "2.0"; id?: number | string; method?: string; params?: any };
const send = (m: object) => process.stdout.write(JSON.stringify(m) + "\n");
const reply = (id: Msg["id"], result: object) => send({ jsonrpc: "2.0", id, result });
const fail = (id: Msg["id"], code: number, message: string) => send({ jsonrpc: "2.0", id, error: { code, message } });

async function handle(msg: Msg): Promise<void> {
  const { id, method, params } = msg;
  if (id === undefined) return; // notification (напр. notifications/initialized) — відповідати не треба

  switch (method) {
    case "initialize":
      return reply(id, {
        protocolVersion: params?.protocolVersion ?? "2025-06-18",
        capabilities: { tools: {} },
        serverInfo: { name: "rag", version: "0.1.0" },
      });
    case "ping":
      return reply(id, {});
    case "tools/list":
      return reply(id, { tools: [TOOL] });
    case "tools/call": {
      if (params?.name !== TOOL.name) return fail(id, -32602, `Unknown tool: ${params?.name}`);
      const { query, k } = params.arguments ?? {};
      if (typeof query !== "string" || !query.trim()) {
        return reply(id, { content: [{ type: "text", text: "Помилка: потрібен параметр query" }], isError: true });
      }
      try {
        const t0 = Date.now();
        const text = await semanticSearch(query, k);
        log(`semantic_search("${query}", k=${k ?? 8}) ${Date.now() - t0} ms`);
        return reply(id, { content: [{ type: "text", text }] });
      } catch (e) {
        return reply(id, { content: [{ type: "text", text: `Помилка пошуку: ${(e as Error).message}` }], isError: true });
      }
    }
    default:
      return fail(id, -32601, `Method not found: ${method}`);
  }
}

createInterface({ input: process.stdin }).on("line", (line) => {
  if (!line.trim()) return;
  let msg: Msg;
  try { msg = JSON.parse(line); } catch { return fail(null as any, -32700, "Parse error"); }
  handle(msg).catch((e) => fail(msg.id, -32603, String(e)));
});

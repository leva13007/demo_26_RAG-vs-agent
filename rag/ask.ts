// ask.ts — RAG-гравець: питання → ембединг → top-k (brute-force cosine) → Claude відповідає по фрагментах
//
// node rag/ask.ts "питання" [--k 8] [--index rag/index] [--model sonnet] [--retrieve-only] [--json]
//
//   --retrieve-only  показати лише знайдені чанки, без виклику Claude (зручно для демо пошуку)
//   --json           вивести один JSON-об'єкт (для арени)
import { spawnSync } from "node:child_process";
import { parseArgs, embed, dot, loadIndex, fmt, ytLink } from "./lib.ts";

const args = parseArgs(process.argv.slice(2));
const question = args._.join(" ").trim();
if (!question) {
  console.error('Usage: node rag/ask.ts "питання" [--k 8] [--index rag/index] [--model sonnet] [--retrieve-only] [--json]');
  process.exit(1);
}
const K = Number(args.k ?? 8);
const INDEX = String(args.index ?? "rag/index");
const MODEL = String(args.model ?? "sonnet");
const CLAUDE_BIN = process.env.CLAUDE_BIN ?? "claude";
const asJson = Boolean(args.json);
const log = (...a: unknown[]) => { if (!asJson) console.log(...a); };

// 1. Retrieval
const tStart = Date.now();
const { meta, vectors } = loadIndex(INDEX);
const [qv] = await embed([question]);
const scored = vectors.map((v, i) => ({ i, score: dot(qv, v) }));
scored.sort((a, b) => b.score - a.score);
const top = scored.slice(0, K).map(({ i, score }) => ({ ...meta.chunks[i], score }));
const retrievalMs = Date.now() - tStart;

log(`\n🔎 Top-${K} з ${meta.chunks.length} чанків за ${retrievalMs} ms (${meta.model}, header=${meta.header})`);
top.forEach((c, n) =>
  log(`  [${n + 1}] ${c.score.toFixed(3)}  ${c.date}  [${fmt(c.start)}]  ${c.title.slice(0, 60)}`),
);
if (args["retrieve-only"]) process.exit(0);

// 2. Промпт
const SYSTEM = [
  "Ти відповідаєш на питання ВИКЛЮЧНО на основі наданих фрагментів транскриптів стрімів IT Friday.",
  "Транскрипти — автоматичне розпізнавання мови: терміни можуть бути записані з помилками (напр. кирилицею).",
  "Посилайся на фрагменти номерами у квадратних дужках: [1], [3].",
  'Якщо у фрагментах немає відповіді — прямо скажи: "У знайдених фрагментах відповіді немає." Нічого не вигадуй.',
  "Відповідай українською, коротко і по суті.",
].join("\n");

const context = top
  .map((c, n) => `[${n + 1}] Стрім: ${c.title} (${c.date}), ${fmt(c.start)}–${fmt(c.end)}\n${c.text}`)
  .join("\n\n");
const userPrompt = `Фрагменти:\n\n${context}\n\n---\nПитання: ${question}`;

// 3. Claude Code headless без інструментів — чиста генерація по контексту
const tLlm = Date.now();
const res = spawnSync(
  CLAUDE_BIN,
  [
    "-p", "--model", MODEL, "--output-format", "json",
    "--tools", "", "--system-prompt", SYSTEM,
    // без скілів, MCP-серверів і user/project налаштувань: накладні ~7.7k → ~1k токенів
    "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "",
    "--no-session-persistence",
  ],
  {
    input: userPrompt, encoding: "utf8", maxBuffer: 50 * 1024 * 1024,
    // кеш RAG-у не допомагає (кожен запит з новими фрагментами), а запис у кеш дорожчий
    env: { ...process.env, DISABLE_PROMPT_CACHING: process.env.DISABLE_PROMPT_CACHING ?? "1" },
  },
);
if (res.status !== 0) {
  console.error(`claude завершився з кодом ${res.status}\n${res.stderr || res.stdout}`);
  process.exit(1);
}
const out = JSON.parse(res.stdout) as {
  result: string;
  total_cost_usd?: number;
  duration_ms?: number;
  usage?: { input_tokens?: number; output_tokens?: number; cache_read_input_tokens?: number; cache_creation_input_tokens?: number };
};
const llmMs = Date.now() - tLlm;
const u = out.usage ?? {};
const inputTokens = (u.input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0);

// 4. Цитати: які [n] модель реально використала → посилання на YouTube з таймкодом
const used = [...new Set([...out.result.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])))]
  .filter((n) => n >= 1 && n <= top.length)
  .sort((a, b) => a - b);
const citations = used.map((n) => ({ n, title: top[n - 1].title, date: top[n - 1].date, time: fmt(top[n - 1].start), url: ytLink(top[n - 1]) }));

const metrics = {
  retrievalMs,
  llmMs,
  totalMs: Date.now() - tStart,
  inputTokens,
  outputTokens: u.output_tokens ?? 0,
  costUsd: out.total_cost_usd ?? null,
};

if (asJson) {
  console.log(JSON.stringify({ player: "rag", question, answer: out.result, citations, retrieved: top.map(({ text, ...c }) => c), metrics }, null, 2));
} else {
  log(`\n💬 ${out.result}\n`);
  if (citations.length) {
    log("📎 Джерела:");
    citations.forEach((c) => log(`  [${c.n}] ${c.date} ${c.time}  ${c.title.slice(0, 50)}  ${c.url}`));
  }
  log(
    `\n⏱  retrieval ${metrics.retrievalMs} ms · LLM ${(metrics.llmMs / 1000).toFixed(1)} s · ` +
      `tokens in ${metrics.inputTokens} / out ${metrics.outputTokens}` +
      (metrics.costUsd != null ? ` · ~$${metrics.costUsd.toFixed(4)}` : ""),
  );
}

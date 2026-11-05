// eval_retrieval.ts — вимірює лише ПОШУК RAG, без LLM: безкоштовно і за секунди. Для тюнінгу.
// Чи є докази правильної відповіді серед фрагментів, які модель отримала б?
//
// node eval_retrieval.ts [--index шлях] [--k 8] [--max-per-stream N] [--q 6] [--show]
//
//   --index           папка індексу (за замовчуванням rag/index)
//   --k               скільки фрагментів віддаємо моделі
//   --max-per-stream  не більше N фрагментів з одного стріму (проста різноманітність видачі)
//   --q               лише одне питання
//   --show            показати для кожного питання top-k
//   --query-prefix    текст перед запитом: деякі моделі його вимагають (qwen3-embedding)
//   Інша модель ембедингів: EMBED_MODEL=назва node eval_retrieval.ts --index ...
import { readFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const RAG = resolve(HERE, "..");
const { embed, dot, loadIndex, parseArgs, fmt, modelMismatch } = await import(join(RAG, "rag/lib.ts"));

// Доказ = стрім (date) і, за потреби, момент (sec). anyOf: досить будь-якого з варіантів.
type Ev = { date: string; sec?: number };
const hms = (s: string) => s.split(":").map(Number).reduce((a, v) => a * 60 + v, 0);
const e = (date: string, t?: string): Ev => ({ date, sec: t ? hms(t) : undefined });
const GOLD: Record<number, { name: string; need: Ev[][] }> = {
  1: { name: "Стек міні-Twitter", need: [[e("2026-09-05", "02:56:57")]] },
  2: { name: "Event Functions", need: [[e("2026-10-24", "00:18:14")]] },
  3: { name: "Музика Таланова", need: [[e("2026-06-13", "00:24:48"), e("2026-06-13", "00:25:39")]] },
  4: { name: "tmux", need: [[e("2026-07-11")]] },
  5: { name: "Graphify, висновок", need: [[e("2026-09-19", "03:00:15"), e("2026-09-19", "03:00:44"), e("2026-09-19", "03:15:23")]] },
  6: { name: "Чанк без шапки", need: [[e("2026-09-26", "00:24:13")]] },
  7: { name: "Таланов, 2 стріми", need: [[e("2026-06-13")], [e("2026-08-01")]] },
  8: { name: "Безпека входу, 2 стріми", need: [[e("2026-08-15")], [e("2026-08-22")]] },
  9: { name: "Гостя із Запоріжжя", need: [[e("2026-10-31", "00:01:20")]] },
  10: { name: "Блажейко, 8 стрімів", need: ["06-20", "06-27", "07-04", "08-15", "08-22", "08-29", "09-26", "10-17"].map((d) => [e("2026-" + d)]) },
  13: { name: "Kubernetes, 2 згадки", need: [[e("2026-10-03", "00:27:44")], [e("2026-10-03", "00:50:20")]] },
  14: { name: "GraphQL, 5 стрімів", need: [[e("2026-06-06", "01:09:59")], [e("2026-07-04", "01:31:20")], [e("2026-07-25", "00:25:10"), e("2026-07-25", "01:13:46")], [e("2026-08-01", "00:33:00")], [e("2026-09-12", "00:48:58")]] },
  15: { name: "Надбавка 62%", need: [[e("2026-10-10", "01:02:10")]] },
};

const args = parseArgs(process.argv.slice(2));
const K = Number(args.k ?? 8);
const MAXP = args["max-per-stream"] ? Number(args["max-per-stream"]) : Infinity;
const raw = String(args.index ?? "rag/index");
const INDEX = isAbsolute(raw) ? raw : join(RAG, raw);
const only = args.q ? Number(args.q) : null;
const questions = readFileSync(join(RAG, "questions.txt"), "utf8").trim().split("\n");
const { meta, vectors } = loadIndex(INDEX);
const mismatch = modelMismatch(meta, INDEX);
if (mismatch) {
  console.error(mismatch);
  process.exit(1);
}

const covers = (c: any, ev: Ev) => c.date === ev.date && (ev.sec === undefined || (c.start <= ev.sec && c.end > ev.sec));
let got = 0, total = 0, full = 0, n = 0, streamsSum = 0;
console.log(`${INDEX.replace(RAG + "/", "")} · чанків ${meta.chunks.length} · window ${meta.window} · stride ${meta.stride} · header ${meta.header} · k ${K}${MAXP < Infinity ? ` · max-per-stream ${MAXP}` : ""}\n`);
console.log("Питання                        знайдено  стрімів  ранг першого доказу");
for (const id of Object.keys(GOLD).map(Number)) {
  if (only && id !== only) continue;
  const g = GOLD[id];
  const [qv] = await embed([String(args["query-prefix"] ?? "") + questions[id - 1]]);
  const sorted = vectors.map((v: Float32Array, i: number) => ({ i, s: dot(qv, v) })).sort((a: any, b: any) => b.s - a.s);
  const perStream = new Map<string, number>(); const top: any[] = [];
  for (const x of sorted) {
    const c = meta.chunks[x.i]; const u = perStream.get(c.file) ?? 0;
    if (u >= MAXP) continue;
    perStream.set(c.file, u + 1); top.push({ ...c, s: x.s });
    if (top.length >= K) break;
  }
  const hit = g.need.filter((any) => any.some((ev) => top.some((c) => covers(c, ev)))).length;
  const firstRank = sorted.findIndex((x: any) => g.need.some((any) => any.some((ev) => covers(meta.chunks[x.i], ev)))) + 1;
  const streams = new Set(top.map((c) => c.file)).size;
  got += hit; total += g.need.length; n++; streamsSum += streams; if (hit === g.need.length) full++;
  console.log(`Q${String(id).padEnd(3)}${g.name.padEnd(27)}${`${hit}/${g.need.length}`.padEnd(10)}${String(streams).padEnd(9)}${firstRank}`);
  if (args.show) top.forEach((c, i) => console.log(`     [${i + 1}] ${c.s.toFixed(3)} ${c.date} [${fmt(c.start)}] ${c.title.slice(0, 50)}`));
}
console.log(`\nДоказів знайдено ${got}/${total} (${((100 * got) / total).toFixed(0)}%) · питань повністю ${full}/${n} · у середньому стрімів у видачі ${(streamsSum / n).toFixed(1)}`);

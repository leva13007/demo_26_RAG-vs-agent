// ingest.ts — corpus/*.md → чанки → ембединги (Ollama) → rag/index/{chunks.json, vectors.bin}
//
// node rag/ingest.ts [--corpus corpus] [--out rag/index] [--window 3] [--stride 2] [--batch 16] [--no-header]
//
//   --window   скільки блоків (~25 с кожен) в одному чанку        → 3 ≈ 75 с
//   --stride   крок вікна; stride < window = overlap               → 2 = перекриття 1 блок
//   --no-header  НЕ додавати "Стрім: <title> (<date>)" у текст для ембедингу
//                (для демо "чанк без шапки" — порівняти якість пошуку)
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { parseArgs, parseDoc, embed, fmt, EMBED_MODEL, type Chunk, type IndexMeta } from "./lib.ts";

const args = parseArgs(process.argv.slice(2));
const CORPUS = String(args.corpus ?? "corpus");
const OUT = String(args.out ?? "rag/index");
const WINDOW = Number(args.window ?? 3);
const STRIDE = Number(args.stride ?? 2);
const BATCH = Number(args.batch ?? 16);
const HEADER = !args["no-header"];

// 1. Чанкінг: ковзне вікно по блоках
const chunks: Chunk[] = [];
const files = readdirSync(CORPUS).filter((f) => f.endsWith(".md")).sort();
for (const file of files) {
  const doc = parseDoc(file, readFileSync(join(CORPUS, file), "utf8"));
  const { blocks } = doc;
  for (let i = 0; i < blocks.length; i += STRIDE) {
    const win = blocks.slice(i, i + WINDOW);
    chunks.push({
      id: chunks.length,
      file,
      title: doc.title,
      date: doc.date,
      youtubeId: doc.youtubeId,
      start: win[0].start,
      end: blocks[i + WINDOW]?.start ?? win[win.length - 1].start + 25,
      text: win.map((b) => b.text).join(" "),
    });
    if (i + WINDOW >= blocks.length) break;
  }
}
console.log(`${files.length} файлів → ${chunks.length} чанків (window=${WINDOW}, stride=${STRIDE}, header=${HEADER})`);
console.log(`Приклад чанку #0: [${fmt(chunks[0].start)}–${fmt(chunks[0].end)}] ${chunks[0].text.slice(0, 120)}…`);

// 2. Текст для ембедингу: з "шапкою" або без
const toEmbedText = (c: Chunk): string => (HEADER ? `Стрім: ${c.title} (${c.date})\n${c.text}` : c.text);

// 3. Ембединги батчами
const t0 = Date.now();
const vectors: Float32Array[] = [];
for (let i = 0; i < chunks.length; i += BATCH) {
  const batch = chunks.slice(i, i + BATCH);
  vectors.push(...(await embed(batch.map(toEmbedText))));
  const done = Math.min(i + BATCH, chunks.length);
  const sec = (Date.now() - t0) / 1000;
  const eta = (sec / done) * (chunks.length - done);
  process.stdout.write(`\r  ембединги: ${done}/${chunks.length}  ${sec.toFixed(0)}s  ETA ${eta.toFixed(0)}s   `);
}
process.stdout.write("\n");

// 4. Збереження: метадані в JSON, вектори — сирим Float32 (в рази менше за JSON)
const dim = vectors[0].length;
const all = new Float32Array(vectors.length * dim);
vectors.forEach((v, i) => all.set(v, i * dim));

mkdirSync(OUT, { recursive: true });
const meta: IndexMeta = {
  model: EMBED_MODEL, dim, header: HEADER, window: WINDOW, stride: STRIDE,
  createdAt: new Date().toISOString(), chunks,
};
writeFileSync(join(OUT, "chunks.json"), JSON.stringify(meta));
writeFileSync(join(OUT, "vectors.bin"), Buffer.from(all.buffer));
console.log(`✓ ${OUT}/  dim=${dim}, ${(all.byteLength / 1e6).toFixed(1)} MB векторів, ${((Date.now() - t0) / 1000).toFixed(0)}s`);

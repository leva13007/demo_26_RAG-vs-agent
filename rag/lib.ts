// lib.ts — спільне для ingest.ts і ask.ts: парсинг корпусу, ембединги, індекс
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const OLLAMA_URL = process.env.OLLAMA_URL ?? "http://localhost:11434";
export const EMBED_MODEL = process.env.EMBED_MODEL ?? "bge-m3";

export type Block = { start: number; text: string };
export type Doc = { file: string; title: string; date: string; youtubeId: string; blocks: Block[] };
export type Chunk = {
  id: number;
  file: string;
  title: string;
  date: string;
  youtubeId: string;
  start: number; // секунди
  end: number;
  text: string; // сирий текст без шапки (для промпта)
};
export type IndexMeta = {
  model: string;
  dim: number;
  header: boolean;
  window: number;
  stride: number;
  createdAt: string;
  chunks: Chunk[];
};

export const fmt = (s: number): string =>
  [Math.floor(s / 3600), Math.floor((s % 3600) / 60), Math.floor(s % 60)]
    .map((n) => String(n).padStart(2, "0"))
    .join(":");

export const ytLink = (c: Chunk): string => `https://youtu.be/${c.youtubeId}?t=${c.start}`;

// простий парсер аргументів: --key value | --flag
export function parseArgs(argv: string[]): { _: string[]; [k: string]: string | boolean | string[] } {
  const out: { _: string[]; [k: string]: string | boolean | string[] } = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) { out._.push(a); continue; }
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith("--")) out[key] = true;
    else { out[key] = next; i++; }
  }
  return out;
}

// .md з vtt2md.ts: frontmatter + рядки "[hh:mm:ss] текст"
export function parseDoc(file: string, raw: string): Doc {
  const m = raw.match(/^---\n([\s\S]*?)\n---\n/);
  const fm: Record<string, string> = {};
  if (m) {
    for (const line of m[1].split("\n")) {
      const i = line.indexOf(":");
      if (i > 0) fm[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    }
  }
  const title = fm.title?.startsWith('"') ? JSON.parse(fm.title) : (fm.title ?? file);
  const body = m ? raw.slice(m[0].length) : raw;
  const blocks: Block[] = [];
  for (const line of body.split("\n")) {
    const b = line.match(/^\[(\d{2}):(\d{2}):(\d{2})\] (.*)$/);
    if (b) blocks.push({ start: +b[1] * 3600 + +b[2] * 60 + +b[3], text: b[4] });
  }
  return { file, title, date: fm.date ?? "", youtubeId: fm.youtubeId ?? "", blocks };
}

// L2-нормалізація: після неї cosine similarity = звичайний dot product
function normalize(v: number[]): Float32Array {
  let n = 0;
  for (const x of v) n += x * x;
  n = Math.sqrt(n) || 1;
  return Float32Array.from(v, (x) => x / n);
}

export async function embed(texts: string[]): Promise<Float32Array[]> {
  const res = await fetch(`${OLLAMA_URL}/api/embed`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model: EMBED_MODEL, input: texts }),
  });
  if (!res.ok) throw new Error(`Ollama ${res.status}: ${await res.text()}`);
  const json = (await res.json()) as { embeddings: number[][] };
  return json.embeddings.map(normalize);
}

export function dot(a: Float32Array, b: Float32Array): number {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}

// Вектори різних моделей не порівнюються: без перевірки буде не помилка, а сміття у видачі.
// Повертає текст проблеми або null, якщо модель запиту збігається з моделлю індексу.
export function modelMismatch(meta: IndexMeta, dir: string): string | null {
  const norm = (m: string) => m.replace(/:latest$/, "");
  if (norm(meta.model) === norm(EMBED_MODEL)) return null;
  return `Індекс ${dir} побудований моделлю "${meta.model}", а запит рахується моделлю "${EMBED_MODEL}". Задай EMBED_MODEL=${meta.model} або інший індекс.`;
}

export function loadIndex(dir: string): { meta: IndexMeta; vectors: Float32Array[] } {
  const meta: IndexMeta = JSON.parse(readFileSync(join(dir, "chunks.json"), "utf8"));
  const buf = readFileSync(join(dir, "vectors.bin"));
  // копія буфера: Float32Array вимагає вирівнювання по 4 байти
  const all = new Float32Array(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
  const vectors: Float32Array[] = [];
  for (let i = 0; i < meta.chunks.length; i++) vectors.push(all.subarray(i * meta.dim, (i + 1) * meta.dim));
  return { meta, vectors };
}

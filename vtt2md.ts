// vtt2md.ts — YouTube VTT (+ info.json) → markdown corpus з таймкодами
// Запуск: node vtt2md.ts [rawDir=raw] [outDir=corpus] [blockSec=25]
// Node 23.6+ запускає .ts напряму; на Node 22: node --experimental-strip-types vtt2md.ts
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const [rawDir = "raw", outDir = "corpus", blockSecArg = "25"] = process.argv.slice(2);
const BLOCK_SEC = Number(blockSecArg);

type Cue = { start: number; lines: string[] };
type Line = { start: number; text: string };

const toSec = (t: string): number =>
  t.split(":").map(Number).reduce((acc, v) => acc * 60 + v, 0);

const fmt = (s: number): string => {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return [h, m, sec].map((n) => String(n).padStart(2, "0")).join(":");
};

// прибираємо word-level теги <00:00:01.234><c> ... </c> і HTML-сутності
const clean = (l: string): string =>
  l
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();

function parseVtt(text: string): Cue[] {
  const cues: Cue[] = [];
  for (const block of text.replace(/\r/g, "").split(/\n\n+/)) {
    const rows = block.split("\n");
    const i = rows.findIndex((r) => r.includes("-->"));
    if (i === -1) continue; // заголовок WEBVTT / Kind / Language
    const start = toSec(rows[i].split("-->")[0].trim());
    const lines = rows.slice(i + 1).map(clean).filter(Boolean);
    if (lines.length) cues.push({ start, lines });
  }
  return cues;
}

// YouTube auto-subs "котяться": кожен cue містить попередній рядок + новий.
// Беремо рядок лише якщо він відрізняється від останнього доданого.
function dedupe(cues: Cue[]): Line[] {
  const out: Line[] = [];
  let last = "";
  for (const c of cues) {
    for (const line of c.lines) {
      if (line === last) continue;
      out.push({ start: c.start, text: line });
      last = line;
    }
  }
  return out;
}

// склеюємо рядки в блоки по ~BLOCK_SEC секунд з таймкодом на початку
function group(lines: Line[], blockSec: number): string[] {
  const blocks: string[] = [];
  let start = -1;
  let buf: string[] = [];
  for (const l of lines) {
    if (start < 0) start = l.start;
    if (buf.length && l.start - start >= blockSec) {
      blocks.push(`[${fmt(start)}] ${buf.join(" ")}`);
      buf = [];
      start = l.start;
    }
    buf.push(l.text);
  }
  if (buf.length) blocks.push(`[${fmt(start)}] ${buf.join(" ")}`);
  return blocks;
}

mkdirSync(outDir, { recursive: true });
const files = readdirSync(rawDir);

// base = "20260815_abc123" (id YouTube не містить крапок)
const vttByBase = new Map<string, string[]>();
for (const f of files.filter((f) => f.endsWith(".vtt"))) {
  const base = f.split(".")[0];
  vttByBase.set(base, [...(vttByBase.get(base) ?? []), f]);
}

let ok = 0;
for (const infoFile of files.filter((f) => f.endsWith(".info.json"))) {
  const base = infoFile.split(".")[0];
  const vtts = vttByBase.get(base);
  if (!vtts) {
    console.warn(`⚠ ${base}: немає субтитрів`);
    continue;
  }
  // якщо їх кілька (uk, uk-orig, ...), беремо з найкоротшою назвою, тобто "uk"
  const vtt = vtts.sort((a, b) => a.length - b.length)[0];
  const info = JSON.parse(readFileSync(join(rawDir, infoFile), "utf8"));
  const d: string = info.upload_date ?? "00000000";
  const date = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;

  const lines = dedupe(parseVtt(readFileSync(join(rawDir, vtt), "utf8")));
  const blocks = group(lines, BLOCK_SEC);

  const md = [
    "---",
    `title: ${JSON.stringify(info.title ?? base)}`,
    `date: ${date}`,
    `youtubeId: ${info.id}`,
    `url: https://youtu.be/${info.id}`,
    `duration: ${fmt(info.duration ?? 0)}`,
    "---",
    "",
    ...blocks,
    "",
  ].join("\n");

  const outFile = join(outDir, `${date}_${info.id}.md`);
  writeFileSync(outFile, md);
  const words = lines.reduce((n, l) => n + l.text.split(" ").length, 0);
  console.log(`✓ ${outFile}  (${blocks.length} блоків, ~${words} слів)`);
  ok++;
}
console.log(`\nГотово: ${ok} файлів → ${outDir}/`);

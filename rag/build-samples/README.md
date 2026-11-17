# build-samples

Builds **samples for a golden dataset** (question/answer pairs with evidence) from the stream transcripts in `corpus/raw/`.
The notebooks turn raw captions into chunks, cluster the chunks by topic, and draw samples of growing difficulty
from the clusters.

## Pipeline

```
corpus/raw/*.md
   | clear_corpus.ipynb
   v
corpus/clean/*.json            text (raw) + text_clean (without fillers / noise tags)
   | corpus-chunking.ipynb
   v
corpus/chunks/time_chunks.json         chunks of 512-1024 tokens, 15% overlap
   | embed-chunks.ipynb  (embedder.py)
   v
corpus/chunks/time_chunks.npy          one vector per chunk, same order as the JSON
   | chunks-clustering.ipynb
   v
corpus/chunks/clusters.json            cluster of every chunk + cluster stats
   | build-samples.ipynb
   v
corpus/samples/samples.json            60 samples in 4 difficulty levels
```

Run the notebooks in this order. Each one reads the output of the previous one.

## Files

| File | Purpose |
|---|---|
| `clear_corpus.ipynb` | Parses `corpus/raw/*.md` (front matter + `[hh:mm:ss] text` lines) into JSON: `text` keeps the raw lines, `text_clean` has hesitations (`е-е`, `м-м`), sound tags (`[сміх]`), speaker markers (`>>`), fillers (`ну`, `от`, ...) and stutters removed. |
| `corpus-chunking.ipynb` | Time-based chunking over `text_clean` with the bge-m3 tokenizer: a chunk closes at ~768 tokens (limits 512-1024), the next one starts with ~15% of the previous. Chunk id = `youtubeId#start_timecode` (stable). Parameters are constants at the top. |
| `embedder.py` | `Embedder` class: embeds texts with `BAAI/bge-m3` (sentence-transformers, GPU/fp16 if available), returns normalised float32 matrices. |
| `embed-chunks.ipynb` | Embeds all chunks with `Embedder` and saves `time_chunks.npy` + `time_chunks.meta.json`. Row `i` of the matrix is chunk `i` of the JSON; the meta file stores the ids to detect a mismatch. |
| `chunks-clustering.ipynb` | PCA and UMAP views of the chunks, a search over UMAP dimensions x HDBSCAN settings (scored by stability across seeds), a cluster report (stats, c-TF-IDF keywords, typical chunks) and the export to `clusters.json`. |
| `build-samples.ipynb` | Draws 60 samples from `clusters.json` (excludes noise and meaningless clusters such as 7): level 1 single chunk (20), level 2 several chunks of one cluster (15), level 3 chunks from two similar clusters (15), level 4 from two different clusters (10). No chunk is reused and overlapping time spans are avoided. |
| `terms/stopwords_uk.txt` | Ukrainian stop words for the cluster keywords. One word per line, `#` starts a comment. Edit to tune the keywords. |
| `terms/farewell_words_uk.txt` | Word stems that flag an outro cluster ("farewell words"). |
| `requirements.txt` | Python dependencies. Install `torch` with CUDA first (see the comment in the file). |

## Output files (in `corpus/`, outside this folder)

- `clean/*.json` - one file per stream: `title`, `date`, `youtubeId`, `url`, `duration`, `text`, `text_clean` (lists of `{timecode: text}`).
- `chunks/time_chunks.json` - chunks with `id`, `start`/`end` (seconds), `tokens`, `text`.
- `chunks/clusters.json` - `labels` (chunk id -> cluster, -1 = noise), per-cluster stats and keywords, centroid similarity matrix.
- `samples/samples.json` - samples with chunk ids, clusters, time spans (YouTube links) and, for levels 3-4, the cluster similarity.

## Notes

- Gold labels should use the evidence span (`youtubeId`, `start`-`end`), not chunk ids, so they survive re-chunking.
- Everything is seeded (UMAP, sampler); the same inputs give the same clusters and samples.
- If you change chunking or embeddings, re-run everything after that step; `clusters.json` and `samples.json` are only valid for the chunks they were built from.
- Keep notebook code and comments ASCII-only (put Cyrillic in data files like `terms/*.txt`): non-ASCII text in notebook cells has been corrupted on save before.

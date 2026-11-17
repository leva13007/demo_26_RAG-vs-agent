"""Embedder: turns texts into a float32 numpy matrix with BAAI/bge-m3 from Hugging Face.

Runs locally through sentence-transformers (dense embeddings, CLS pooling - the bge-m3 default).
The vectors are NOT identical to the ones Ollama's GGUF build of bge-m3 produces in rag/lib.ts,
so don't mix the two in one similarity matrix.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

DEFAULT_MODEL = "BAAI/bge-m3"


class Embedder:
    """Batch embedder over a sentence-transformers model (loaded lazily).

    >>> emb = Embedder()
    >>> vectors = emb.embed(["перший текст", "другий текст"])   # shape (2, 1024), float32
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,      # None -> "cuda" if available, else "cpu"
        batch_size: int = 8,
        normalize: bool = True,
        fp16: bool | None = None,       # None -> half precision on GPU only
        max_seq_length: int = 2048,     # chunks are <= ~1030 tokens; a text longer than this raises
    ) -> None:
        self.model_name = model_name
        self._device = device
        self.batch_size = batch_size
        self.normalize = normalize
        self._fp16 = fp16
        self.max_seq_length = max_seq_length
        self._model = None

    # ---- model ----

    @property
    def model(self):
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            device = self._device or ("cuda" if torch.cuda.is_available() else "cpu")
            fp16 = self._fp16 if self._fp16 is not None else device.startswith("cuda")
            model = SentenceTransformer(self.model_name, device=device)
            model.max_seq_length = self.max_seq_length
            if fp16:
                model.half()
            self._model = model
            self._device, self._fp16 = device, fp16
        return self._model

    @property
    def device(self) -> str:
        return str(self.model.device)

    @property
    def fp16(self) -> bool:
        _ = self.model  # make sure the settings are resolved
        return bool(self._fp16)

    @property
    def dim(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    # ---- public API ----

    def count_tokens(self, texts: Iterable[str]) -> list[int]:
        """Token counts as the model sees them (special tokens included)."""
        ids = self.model.tokenizer(list(texts), truncation=False, add_special_tokens=True)["input_ids"]
        return [len(x) for x in ids]

    def embed(self, texts: Iterable[str], show_progress: bool = True) -> np.ndarray:
        """Embed texts in order. Row i of the result belongs to texts[i]."""
        texts = list(texts)
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        too_long = [i for i, n in enumerate(self.count_tokens(texts)) if n > self.max_seq_length]
        if too_long:  # refuse instead of silently truncating
            raise ValueError(f"{len(too_long)} text(s) exceed {self.max_seq_length} tokens, e.g. index {too_long[0]}")
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            convert_to_numpy=True,
            show_progress_bar=show_progress,
        )
        assert vectors.shape[0] == len(texts)
        return vectors.astype(np.float32, copy=False)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text], show_progress=False)[0]

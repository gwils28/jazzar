"""Embeddings locaux (bge-m3 via sentence-transformers). Singleton paresseux, GPU si disponible.

bge-m3 : multilingue (FR/EN), 1024 dimensions, vecteurs normalisés -> similarité cosinus = produit scalaire.
"""

from __future__ import annotations

import asyncio
import threading
from functools import lru_cache

import numpy as np

from jazzar.config import get_settings
from jazzar.logging import get_logger

log = get_logger(__name__)
_lock = threading.Lock()


class Embedder:
    def __init__(self, model_name: str, device: str = "auto", batch_size: int = 32) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.batch_size = batch_size
        self.model_name = model_name
        log.info("embedder.loading", model=model_name, device=device)
        self.model = SentenceTransformer(model_name, device=device)
        if device == "cuda":
            self.model.half()
        self.dim = int(self.model.get_sentence_embedding_dimension() or 0)
        log.info("embedder.ready", dim=self.dim)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with _lock:
            vecs = self.model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return np.asarray(vecs, dtype=np.float32)

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0].tolist()

    async def aencode(self, texts: list[str]) -> np.ndarray:
        return await asyncio.to_thread(self.encode, texts)

    async def aencode_one(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.encode_one, text)


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    return Embedder(s.embedding_model, s.embedding_device, s.embedding_batch_size)

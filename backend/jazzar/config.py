"""Configuration centralisée (variables d'environnement préfixées JAZZAR_)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JAZZAR_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Modèles Claude. "large" : synthèse, rédaction, SQL complexe. "small" : routage, extraction.
    model_large: str = "claude-opus-5-5"
    model_small: str = "claude-haiku-5-5"

    database_url: str = "postgresql+asyncpg://jazzar:jazzar@localhost:5433/jazzar"
    database_ro_url: str = "postgresql+asyncpg://jazzar_ro:jazzar_ro@localhost:5433/jazzar"
    redis_url: str = "redis://localhost:6379/0"

    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "auto"
    embedding_dim: int = 1024
    embedding_batch_size: int = 32

    data_dir: Path = Path("../data")

    semantic_cache_threshold: float = 0.95
    semantic_cache_ttl: int = 86400

    api_host: str = "0.0.0.0"
    api_port: int = 8100
    cors_origins: str = "http://localhost:3000"

    # Retrieval
    retrieval_top_k: int = 12
    retrieval_vector_candidates: int = 40
    retrieval_keyword_candidates: int = 40
    chunk_target_tokens: int = 400
    chunk_overlap_tokens: int = 60

    # Tarifs USD par million de tokens, pour le suivi de coût (mis à jour 2026-10).
    pricing: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0},
            "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
            "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write": 2.5},
        }
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def samples_dir(self) -> Path:
        return self.data_dir / "samples"

    @property
    def raw_dirs(self) -> list[Path]:
        return [self.data_dir / "raw" / "downbeat", self.data_dir / "raw" / "local"]


@lru_cache
def get_settings() -> Settings:
    return Settings()

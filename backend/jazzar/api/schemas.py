"""Schémas Pydantic de l'API publique."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FiltersIn(BaseModel):
    year_from: int | None = None
    year_to: int | None = None
    doc_types: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    source_kinds: list[str] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    lang: str | None = Field(default=None, description="fr | en ; défaut : langue détectée")
    filters: FiltersIn = Field(default_factory=FiltersIn)
    use_cache: bool = True


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    filters: FiltersIn = Field(default_factory=FiltersIn)
    top_k: int = Field(default=12, ge=1, le=50)
    mode: str = Field(default="hybrid", pattern="^(hybrid|keyword)$")


class FeedbackRequest(BaseModel):
    trace_id: str
    score: int = Field(ge=-1, le=1)
    comment: str | None = None


class DossierRequest(BaseModel):
    brief: str = Field(min_length=10, max_length=6000)
    lang: str = "fr"


class BIRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    lang: str = "fr"

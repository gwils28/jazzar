# Architecture Jazzar

## Objectifs (hérités de plan.md)
- Business : outil personnel d'abord, structuré pour devenir un SaaS (auth, organisations, abonnements à ajouter sans refonte).
- Tech : p95 < 1,5 s sur les requêtes simples (cache sémantique + routage small-model), coût < 0,01 $ par requête complexe (prompt caching, petit modèle pour le routage), **zéro hallucination sur dates et noms** (citations obligatoires, juge et golden set).

## Vue d'ensemble

```
PDFs / Markdown / Wikipedia ─► ingestion (Rust: clean_ocr, chunk, simhash) ─► bge-m3 (GPU) ─► Postgres
                                                                                 ├─ chunks (vector + tsvector)
                                                                                 ├─ documents / sources
                                                                                 └─ reviews / polls / artists (BI)

Question ─► Routeur (Haiku, sortie structurée) ─► Cache sémantique (Redis) ─► Recherche hybride (pgvector ∪ FTS, RRF)
         ─► Génération citée (Opus/Haiku selon route, flux SSE) ─► queries (trace, coût, feedback)
         └─ fail-open : extraits mots-clés si l'IA est indisponible

Commande de dossier ─► Planificateur ─► Chercheur ×N (tool runner : search_archive / read_document / query_metadata)
                     ─► Rédacteur (flux long) ─► Critique (vérifie chaque [S-xxxx]) ─► dossiers (markdown + citations)

Question BI ─► SQLPlan (Opus, structuré) ─► validate_sql (sqlglot, liste blanche, LIMIT) ─► jazzar_ro ─► Plotly spec + insight (Haiku)
```

## Décisions

| Sujet | Choix | Pourquoi |
|---|---|---|
| Vecteurs | pgvector (HNSW, cosinus) dans le même Postgres | Un seul service, filtres SQL exacts dans la même requête, suffisant jusqu'à plusieurs millions de chunks. Qdrant reste une option si le volume explose. |
| Plein-texte | `tsvector` généré + GIN, `websearch_to_tsquery`, repli OU | Gratuit, dans la base, et c'est le chemin fail-open sans LLM. |
| Fusion | Reciprocal Rank Fusion (k=60) + diversification (≤3 chunks/document) | Robuste sans calibration des scores. |
| Embeddings | `BAAI/bge-m3` local, 1024 d, fp16 sur GPU | Multilingue FR/EN (questions en français sur un corpus anglais), zéro coût d'API. |
| Routage | Haiku 5.5, `effort=low`, sortie structurée Pydantic | ~100 ms et quelques centièmes de centime ; repli heuristique si indisponible. |
| Génération | Opus 5.5 (`semantic`/`synthesis`), Haiku 5.5 (`lookup`) ; `fallbacks="default"` sur Opus | Qualité maximale là où ça compte, économie sur les faits simples. |
| Cache | Redis, entrées {question, embedding, réponse, citations}, cosinus ≥ 0,95, scope = filtres + langue | Les questions fréquentes sont servies en ~50 ms sans appel modèle. |
| Texte | Rust (PyO3) avec repli Python à interface identique | Le nettoyage/chunking tourne sur des millions de caractères OCR ; 20× plus rapide, et le projet garde un chemin pur Python. |
| Text-to-SQL | sqlglot + liste blanche + rôle `jazzar_ro` + `statement_timeout` | Le SQL généré est traité comme une entrée non fiable. |
| Graphiques | Spécification Plotly JSON rendue côté client | Pas d'exécution de code généré ; couleurs de la palette appliquées dans le frontend. |
| Observabilité | `llm_calls` + `queries` en base, en-têtes `x-request-id` / `x-response-time-ms`, logs structurés | Suffisant en local ; OpenTelemetry / LangSmith branchables plus tard. |
| Evals | Golden set JSON (factuel + pièges), juge Haiku, gates durs | Hérité du golden set « Blindfold » ; pièges = 100 % obligatoire. |

## Modèle de données
Voir `backend/jazzar/models.py`. Les tables analytiques exposées au Text-to-SQL sont `reviews`, `polls`, `documents`, `artists`, `sources` (description dans `BI_SCHEMA_DESCRIPTION`).

## Chemin vers le SaaS
1. Auth (ex. Clerk / Auth.js ou FastAPI-Users) + colonne `org_id` sur `queries`, `dossiers`, `documents` (sources privées vs communes).
2. Quotas par plan (compteur Redis par org) et Stripe pour l'abonnement ; le coût réel est déjà mesuré par appel.
3. Déploiement : image Docker du backend (CPU pour l'inférence d'embeddings, ou service d'embeddings séparé sur GPU), Postgres managé avec pgvector (Neon, Supabase, Cloud SQL), Redis managé, frontend sur Vercel ou conteneur. Alternative : un seul VPS avec Docker Compose + Caddy.
4. Travaux de fond (ingestion nocturne, dossiers longs) vers une file (arq / Celery) au lieu d'`asyncio.create_task`.

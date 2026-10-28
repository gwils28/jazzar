# Jazzar

> Quatre-vingt-dix ans d'archives jazz, interrogeables. Recherche hybride citée, dossiers de recherche générés par une équipe d'agents, et data-journalisme (Text-to-SQL + graphiques) sur les métadonnées.

Jazzar (comme *quasar*) est un SaaS en construction, hébergé en local pour commencer. Il s'appuie sur un corpus ouvert (Wikipedia, MusicBrainz) et sur des PDFs de magazines déposés localement (abonnement personnel).

## Les trois piliers

| Pilier | Ce que ça fait | Où |
|---|---|---|
| **Demander** (RAG hybride) | Routeur small-model → recherche vecteurs + plein-texte (RRF) → réponse citée `[n]` en flux. Cache sémantique Redis. Fail-open vers la recherche mots-clés si l'IA est hors ligne. | `backend/jazzar/llm/`, `retrieval/` |
| **Dossiers** (agents) | Planificateur → Chercheur (tool runner : recherche, lecture, SQL) → Rédacteur → Critique. Chaque affirmation porte une référence `[S-xxxx]` vers un extrait réel. | `backend/jazzar/agents/dossier.py` |
| **Insights** (BI as Code) | Question → SQL validé (sqlglot, liste blanche, rôle lecture seule) → données → spécification Plotly → lecture rédigée. | `backend/jazzar/bi/engine.py` |

Transversal : **Observatoire** (latence p95, coût par usage, taux de cache, feedback 👍/👎, golden set avec gates), **Bibliothèque** (documents, extraits, lien vers la page PDF citée).

## Stack

- **Backend** : Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL 17 + pgvector, Redis, Anthropic SDK (Claude Opus 5.5 pour la synthèse, Claude Haiku 5.5 pour le routage), embeddings locaux `BAAI/bge-m3` (GPU si disponible).
- **Rust** : `rust/jazzar-text` (PyO3) — nettoyage OCR, chunking, simhash. ~20× plus rapide que le repli Python, interface identique (`jazzar.text`).
- **Frontend** : Next.js 16, React 19, Tailwind 4, Plotly. Bilingue FR/EN (sélecteur), thème sombre par défaut, palette `#F4A261 · #7A1C1C · #F4F1DE · #2B1E1A · #4A4E69`.
- **Infra locale** : Docker Compose (Postgres sur le port 5433, Redis 6379). Backend et frontend tournent sur l'hôte.

## Démarrage

```bash
cp .env.example .env            # puis renseigner ANTHROPIC_API_KEY
make infra                      # Postgres + Redis
cd backend && uv sync --extra dev && cd ..
# Extension Rust (optionnelle, repli Python sinon) :
#   curl https://sh.rustup.rs -sSf | sh -s -- -y && cd rust/jazzar-text && \
#   VIRTUAL_ENV=../../backend/.venv ../../backend/.venv/bin/maturin develop --release
make db-init
make ingest-samples             # corpus d'exemple (télécharge bge-m3 au premier lancement)
make ingest-wikipedia           # ~60 articles ouverts (optionnel)
make api                        # http://localhost:8100/docs
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Déposer des PDFs dans `data/raw/downbeat/` (ou `data/raw/local/`) puis `make ingest-pdf`. Les pages sans couche texte sont ignorées : passer les scans par `ocrmypdf` en amont.

Sans clé Anthropic, l'application démarre en **mode dégradé** : recherche hybride et extraits, pas de synthèse ni d'agents.

## Commandes utiles

```bash
cd backend
uv run jazzar ask "Qui joue du piano sur Freddie Freeloader ?"   # question en CLI
uv run jazzar eval run                                             # golden set + gates
uv run jazzar cache clear
uv run pytest -q
```

## Qualité et garde-fous

- **Zéro affirmation sans source** : le modèle ne peut citer que les extraits fournis ; l'UI relie chaque `[n]` à sa source ; le critique du pipeline Dossiers supprime toute référence invalide.
- **Pièges anti-hallucination** : le golden set (`backend/jazzar/evals/golden_set_v1.json`) contient des prémisses fausses et des faits invérifiables ; le gate `refusal_trap_pass_rate = 1.0` bloque.
- **SQL généré** : une seule instruction SELECT, tables en liste blanche, `LIMIT` forcé, rôle Postgres lecture seule, `statement_timeout`.
- **Coûts** : chaque appel Claude est tracé (`llm_calls`) avec tokens, cache et coût ; le système prompt est mis en cache (prompt caching) ; le petit modèle sert au routage et aux extractions.

Voir `docs/CAHIER_DES_CHARGES.md` pour le périmètre, les exigences et la feuille de route, et `docs/ARCHITECTURE.md` pour le détail des décisions.

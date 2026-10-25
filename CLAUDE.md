# Jazzar — notes pour Claude Code

Monorepo : `backend/` (Python 3.12, uv, FastAPI), `frontend/` (Next.js 16, Tailwind 4), `rust/jazzar-text` (PyO3), `data/` (corpus), `infra/`.

## Conventions
- Commandes via `make` à la racine (`make help`). Backend : `cd backend && uv run …`. Jamais `pip`.
- Postgres tourne dans Docker sur le port **5433** (5432 est pris par un autre projet) ; Redis sur 6379 ; API sur **8100** ; web sur 3000. Le port 8080 est occupé par un autre projet.
- Appels Claude uniquement via `jazzar.llm.client.LLM` (tracing coûts + fallbacks). Modèles : `claude-opus-5-5` (large) et `claude-haiku-5-5` (small), configurables par env. Pas de `temperature`, pas de `budget_tokens`, pas de prefill assistant : adaptive thinking + `output_config.effort`.
- Sorties structurées : `client.messages.parse(output_format=PydanticModel)`.
- Le texte (nettoyage OCR, chunking, simhash) passe par `jazzar.text`, qui choisit Rust ou Python. Toute modification de l'algorithme doit être faite **dans les deux** implémentations et couverte par `tests/test_text.py` (test de parité).
- Frontend : pages en client components, i18n maison (`src/lib/i18n.tsx`, catalogues `src/messages/*.json`). Toute nouvelle chaîne UI va dans **fr.json et en.json**. Couleurs via les tokens CSS de `globals.css`, jamais en dur.
- Toute requête SQL générée par un modèle passe par `jazzar.bi.engine.validate_sql` et le moteur `jazzar_ro`.

## Flux de travail
1. `make infra && make db-init` puis `make ingest-samples`.
2. `make api` et `make web`.
3. Tests : `make test` (backend), `cd frontend && npx tsc --noEmit && npm run build`.
4. Qualité RAG : `make eval` (nécessite une clé API ; coût ≈ quelques centimes).

## Pièges connus
- Next 16 : lire `frontend/node_modules/next/dist/docs/` avant d'utiliser une API Next inconnue (cacheComponents activé, `proxy.ts` remplace `middleware.ts`).
- L'embedder bge-m3 se charge à la première recherche (quelques secondes, ~2,2 Go téléchargés une fois).
- `uv run jazzar ingest pdfs` ignore les pages sans couche texte : OCR en amont (`ocrmypdf`).

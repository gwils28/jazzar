# Jazzar — cahier des charges

> Document de référence du projet : vision, périmètre, données, décisions techniques, exigences, feuille de route.
> Il évolue avec l'application ; chaque changement de périmètre ou de décision doit être reporté ici.
> Détail des choix d'architecture : `docs/ARCHITECTURE.md`. Notes de développement : `CLAUDE.md`. Idée d'origine : `plan.md`.

Dernière mise à jour : 2026-10-28.

## 1. Vision et cible

**Jazzar** (jazz + quasar) rend interrogeables des décennies d'archives de presse jazz, avec des réponses sourcées à la page.

- Outil personnel d'abord, hébergé en local.
- Conçu pour devenir un SaaS B2B sans refonte : labels, documentaristes, programmateurs de festivals, journalistes culturels, historiens.
- Pitch cible : *Premium B2B archive monetization RAG ; routage LLM + recherche hybride ; p95 < 1,5 s ; coûts maîtrisés par cache sémantique ; évals anti-hallucination automatisées.*

## 2. Périmètre fonctionnel

Les trois piliers sont voulus « assez avancés » dès le MVP (décision du 2026-10-25), pas un seul à la fois.

| Pilier | Promesse | État au 2026-10-28 |
|---|---|---|
| **Demander** (RAG hybride) | Question FR ou EN → routeur (`lookup` / `semantic` / `synthesis`) → recherche vecteurs + plein-texte fusionnée (RRF) → réponse en flux, chaque affirmation citée `[n]` et cliquable vers la page du PDF. Cache sémantique Redis. Mode dégradé sans IA. | Codé. Validé en mode dégradé sur le vrai corpus. Synthèse Claude non testée en réel. |
| **Dossiers** (agents) | « Prépare-moi un dossier sur la scène de Chicago 1965-1975 » → Planificateur → Chercheur (outils : recherche, lecture, SQL) → Rédacteur → Critique qui supprime toute référence non vérifiable. Livrable sourcé `[S-xxxx]`. | Codé, jamais exécuté avec une clé API. |
| **Insights** (BI as Code) | Question chiffrée → SQL généré et validé (sqlglot, liste blanche, rôle lecture seule, `LIMIT`, timeout) → données → graphique Plotly + lecture rédigée. | Codé. Aucune donnée réelle dans `reviews` / `polls`. |

Transversal :
- **Bibliothèque** : documents, extraits, lien vers la page PDF citée.
- **Observatoire** : latence p95, coût par usage, taux de cache, feedback 👍/👎, golden set avec gates.
- **i18n** FR/EN avec sélecteur ; toute chaîne UI dans `fr.json` et `en.json`.

Pages frontend : `/` (Demander), `/explore`, `/dossiers`, `/insights`, `/library`, `/observatory`.
API (préfixe `/api`) : `health`, `stats`, `ask`, `feedback`, `queries`, `search`, `documents`, `documents/{id}`, `documents/{id}/pdf`, `dossiers`, `bi/analyze`, `bi/schema`, `evals`, `evals/run`.

## 3. Données

### Sources
- **Principale : numéros DownBeat** (abonnement personnel, usage privé). Un PDF = un document `issue` ; **la page est l'unité de citation**.
  - Au 2026-10-28 : 12 numéros 2025 (`DB25_01` à `DB25_12`), 1 124 pages, 3 381 chunks.
  - PDF natifs de l'éditeur (texte embarqué sur ~83 % des pages). Préparation : `ocrmypdf -l eng --skip-text --jobs 16 --output-type pdf` (texte natif conservé, OCR seulement des pages image, taille inchangée). Jamais `--force-ocr` (taille ×2,3, texte moins bon).
  - Les pubs pleine page restent sans texte : choix assumé (une passe `--redo-ocr` les récupérerait si besoin).
  - Les folios « 12 DOWNBEAT JULY 2025 » sont filtrés à l'extraction ; les chunks de moins de 60 caractères ne sont pas indexés.
  - Nommage `DBYY_MM` → titre « DownBeat — July 2025 », date au 1er du mois.
- **Archives historiques (1937-1999)** : worldradiohistory.com héberge 1 280 PDF (1 250 numéros + 30 yearbooks),
  catalogués dans `~/Documents/Jazz_project/downbeat_worldradiohistory_catalogue.csv`. Le site a retiré l'index
  public, bloque les clients non-navigateur et interdit les robots IA : **pas de téléchargement automatisé**.
  Acquisition à la main ou avec l'accord du responsable du site ; les noms de fichiers (`Down-Beat-1965-08-12`,
  `DB 1961-08-03`, `DB-1998-06`) devront être reconnus par `guess_date` avant ingestion.
- **Corpus ouvert** : Wikipedia (ingestion existante, CC BY-SA 4.0) ; MusicBrainz (table prévue, pas d'ingestion).
- **Corpus d'exemple** fictif (`data/samples/`, `source=sample`) : bouchon de développement, à retirer à terme.

### Modèle
Tables analytiques exposées au Text-to-SQL : `reviews`, `polls`, `documents`, `artists`, `sources`. Voir `backend/jazzar/models.py`.

### Dispositions futures
Sources privées vs communes par `org_id` (voir § 8).

## 4. Architecture et décisions

| Sujet | Choix retenu | Écart par rapport à `plan.md` |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy async, uv (jamais pip) | — |
| Stockage | PostgreSQL 17 + pgvector (HNSW, cosinus) pour tout ; Redis pour le cache | Qdrant / GCP Vector Search prévus ; un seul service suffit jusqu'à plusieurs millions de chunks |
| Plein-texte | `tsvector` + GIN, `websearch_to_tsquery` ; c'est le chemin fail-open | — |
| Fusion | Reciprocal Rank Fusion (k=60), ≤ 3 chunks par document | — |
| Embeddings | `BAAI/bge-m3` local, 1024 d, GPU si disponible, multilingue, coût nul | — |
| Modèles | Opus 5.5 (synthèse, SQL, dossiers), Haiku 5.5 (routage, lookup, insight, juge). Adaptive thinking + `output_config.effort` ; pas de `temperature`, pas de `budget_tokens`, pas de prefill. Sorties structurées via `messages.parse(output_format=...)`. Fallbacks serveur sur Opus. Tout appel passe par `jazzar.llm.client.LLM` (coûts tracés). | Gemini / GPT-4o / Llama 3 cités à l'origine |
| Orchestration agents | Tool runner maison sur le SDK Anthropic | LangGraph / CrewAI cités à l'origine |
| Texte | Rust (`rust/jazzar-text`, PyO3) pour nettoyage OCR, chunking, simhash ; repli Python à interface identique, parité couverte par `tests/test_text.py` | — |
| Text-to-SQL | sqlglot + liste blanche de tables + rôle `jazzar_ro` + `statement_timeout` + `LIMIT` forcé ; le SQL généré est une entrée non fiable | — |
| Graphiques | Spécification Plotly JSON rendue côté client ; aucun code généré n'est exécuté | Code Interpreter prévu à l'origine |
| Cache | Redis, entrées {question, embedding, réponse, citations}, cosinus ≥ 0,95, scope = filtres + langue | — |
| Observabilité | Tables `llm_calls` et `queries`, en-têtes `x-request-id` / `x-response-time-ms`, logs structurés | LangSmith / Datadog « branchables plus tard » |
| Évals | Golden set JSON (17 cas : factuel + pièges), juge Haiku, gates durs | RAGAS prévu à l'origine |
| Frontend | Next.js 16 (cacheComponents, `proxy.ts`), React 19, Tailwind 4, Plotly ; pages en client components ; i18n maison ; couleurs via tokens CSS uniquement | — |

## 5. Exigences de qualité et SLO

| Exigence | Cible | État |
|---|---|---|
| Aucune affirmation sans source | Le modèle ne cite que les extraits fournis ; l'UI relie chaque `[n]` ; le critique des dossiers supprime les références invalides | Implémenté, à vérifier par l'eval |
| Pièges anti-hallucination | Gate `refusal_trap_pass_rate = 1.0` sur le golden set | Implémenté, pas de ligne de base mesurée |
| Fail-open | L'app démarre et répond sans clé API (extraits classés par mots-clés) | Validé |
| Latence | p95 < 1,5 s | Non mesuré en réel |
| Coût | < 0,01 $ par requête complexe | Estimation : lookup < 0,001 $ ; semantic 0,04-0,06 $ ; synthesis 0,10-0,15 $ ; dossier 0,5-1,5 $ ; eval ≈ 1 $ par passage. Objectif non tenu sur Opus ; leviers : `effort=low` sur semantic, `MODEL_LARGE=claude-sonnet-5-5` par env. À arbitrer après l'eval, pas avant. |
| Business | 10 k$ MRR via un tier d'abonnement | Hors périmètre tant que l'outil perso n'est pas convaincant |

Facturation : l'API Anthropic se paie au token sur un compte Console, indépendamment de l'abonnement claude.ai. Chaque appel est tracé avec son coût réel dans `llm_calls` et visible dans l'Observatoire.

## 6. Identité visuelle (validée le 2026-10-28)

- Palette : orange `#F4A261`, bordeaux `#7A1C1C`, crème `#F4F1DE`, brun sombre `#2B1E1A`, ardoise `#4A4E69`.
- Thème sombre « cosmique » par défaut, thème clair disponible. Tokens dans `frontend/src/app/globals.css`.
- Typographies : Fraunces (affichage), Inter (texte), JetBrains Mono (code).
- Logo **croche-quasar** : tête de croche = disque d'accrétion incliné à −25°, hampe = jet, crochet = panache. Tokens `--logo-head` / `--logo-core` (orange et crème en sombre, bordeaux et orange en clair). Sous 20 px, l'anneau externe disparaît et la hampe s'épaissit. Favicon : `frontend/src/app/icon.svg`.
- Directions écartées (quasar épuré, monogramme J) archivées sur le canvas de design. Ne pas rouvrir.

## 7. Contraintes d'environnement

- Ports : Postgres **5433**, API **8100**, web 3000, Redis 6379 (8080 et 5432 occupés par un autre projet).
- Python système 3.14 incompatible torch → backend épinglé 3.12 via uv.
- Machine de développement : Linux, RTX 5070 Laptop 8 Go, 30 Go RAM, 32 cœurs.
- Commandes via `make` à la racine (`make help`).
- Données : `data/raw/**` ignoré par git ; `data/raw/downbeat/` contient les PDF prêts à l'ingestion (originaux supprimés après validation).

## 8. Feuille de route

Par priorité. Mettre à jour l'état ici quand une étape avance.

1. **Brancher Claude et mesurer** — clé API dans `backend/.env`, rejouer les questions qui échouent en mots-clés (ex. vainqueur du Critics Poll 2025), `make eval` pour une ligne de base chiffrée (fidélité, pièges, coût, latence). Coût ≈ 1-2 $.
2. **Remplir `reviews` et `polls` depuis DownBeat** — les notes des critiques sont des glyphes d'étoiles en police dingbat (`HHHH` = 4 étoiles), extractibles sans LLM avec artiste, album, label, auteur ; Critics Poll (numéro d'août) et Readers Poll (décembre) → `polls`. Débloque la BI sur données réelles.
3. **Segmenter les numéros en articles** — citations complètes (titre, auteur), filtres par auteur, meilleur reranking. Les critiques (étape 2) sont des articles bien délimités : commencer par elles.
4. **Dette et compléments** — `file_path` stocké relatif au cwd → relatif à `data_dir` ; ingestion MusicBrainz ; exploiter le feedback 👍/👎 (collecté, inutilisé) ; OCR `--redo-ocr` des pubs si les programmes de festivals deviennent utiles ; retirer le corpus d'exemple.
5. **Chemin SaaS** — auth (Clerk / Auth.js / FastAPI-Users) + `org_id` sur `queries`, `dossiers`, `documents` ; quotas par plan (compteur Redis) + Stripe ; déploiement (image Docker backend, Postgres managé avec pgvector, Redis managé, frontend Vercel ou VPS + Caddy) ; travaux de fond vers une file (arq / Celery) à la place d'`asyncio.create_task`.

## 9. Journal des décisions

| Date | Décision |
|---|---|
| 2026-10-25 | Trois piliers dès le MVP ; corpus ouvert + PDFs DownBeat ; fail-open obligatoire ; ports 5433 / 8100 / 3000. |
| 2026-10-28 | Corpus DownBeat 2025 ingéré (12 numéros). OCR `--skip-text`, pubs exclues, folios filtrés, chunks < 60 caractères écartés. Nommage `DBYY_MM` reconnu. |
| 2026-10-28 | Identité visuelle validée : logo croche-quasar, favicon, tokens `--logo-*`. |
| 2026-10-28 | Archives 1937-1999 : catalogue des 1 280 PDF de worldradiohistory.com établi ; pas de scraper (index retiré, scripts bloqués, robots.txt). Acquisition manuelle ou sur accord. |

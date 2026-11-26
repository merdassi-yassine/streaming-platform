# Plateforme de streaming sur Apache Cassandra, développée par une équipe d'agents IA

Projet NoSQL — Master SID-DS, ISGB — Yassine MERDASSI (Project Owner). Rendu du 28/11/2026.
Tout tourne en **local** (Docker) ; seuls les appels aux LLM sortent du PC.

Deux dépôts :

| Dépôt | Rôle |
|---|---|
| `streaming-platform` (ce dépôt) | L'application : cluster Cassandra 3 nœuds, code écrit par les agents, tests, démo, traces |
| `streaming-ai-squad` | L'équipe d'agents : orchestrateur LangGraph, prompts versionnés, outils contrôlés, rapport |

---

## 1. L'application

**Infrastructure** : 3 nœuds `cassandra:5.0` (datacenter `dc1`, `NetworkTopologyStrategy`, RF = 3) dans
`docker-compose.yml` ; un conteneur `tests` (pytest dans le réseau Docker) ; un service `api` (uvicorn).

**Architecture en couches** (exigée par l'enseignant), toutes écrites par les agents :

| Couche | Fichiers | Tâche |
|---|---|---|
| Modèle de données | `streaming/schema.py` (8 tables, une par requête Q1–Q8, `COMMENT` CQL) | T001 |
| DAO | `streaming/models.py`, `streaming/dao/{titles,users,ratings,views,stats}.py` | T002 |
| Tests DAO + métier | `tests/test_dao.py`, `tests/test_services.py` | T004 (fusion T003) |
| Métier | `streaming/services.py` (fiche + note moyenne, Top 10 du jour, avis) | T004 |
| Présentation | `streaming/api.py` (FastAPI : `create_app` / `build_app`) + `tests/test_api.py` | T005 |

**Modèle de données (orienté requêtes)** :

| Requête | Table | Partition → tri |
|---|---|---|
| Q1 fiche d'un titre | `title_by_id` | `title_id` |
| Q2 titres d'un genre | `titles_by_genre` | `genre` → `release_year DESC` |
| Q3 profil utilisateur | `user_by_id` | `user_id` |
| Q4 avis d'un titre | `reviews_by_title` | `title_id` → `created_at DESC` |
| Q5 avis d'un utilisateur | `reviews_by_user` | `user_id` → `created_at DESC` |
| Q6 historique | `watch_history_by_user` | `user_id` → `watched_at DESC` |
| Q7 statistiques (counters) | `title_stats` | `title_id` |
| Q8 vues du jour (counters) | `daily_views_by_title` | `view_date` → `title_id` |

Règles respectées (vérifiées par le relecteur et les tests) : aucune `ALLOW FILTERING`, chaque lecture vise une
partition, requêtes préparées une fois, compteurs jamais dans le même batch que les écritures normales.

## 2. Résultats réels

- **Tests : 24/24 OK** sur le cluster 3 nœuds (`docker compose --profile tests run --rm tests`) — schéma, DAO,
  services, API, cluster. Journal : `ai-trace/runs/T005-20261126-013959/tests_iter3.log`.
- **Démo de la distribution** (`bash demo/demo_distribution.sh`, sortie `reports/demo/demo-20261126-030349.txt`) :

  | État | ONE | QUORUM | ALL |
  |---|---|---|---|
  | 3 nœuds UP | OK | OK | OK |
  | `cassandra3` arrêté | OK | OK | **refusé** (2 réplicas vivants sur 3) |
  | `cassandra3` redémarré | OK | OK | OK |

  Choix CAP : avec RF = 3, QUORUM (2/3) garde la disponibilité en cas de panne d'un nœud tout en assurant une
  lecture cohérente (W + R > RF) ; ALL privilégie la cohérence et devient indisponible.
- **API en conditions réelles** (`reports/demo/api-smoke-*.txt`) : `/health` 3/3 nœuds, fiche avec moyenne 4,5,
  genre, Top 10 du jour, historique, 404 titre inconnu, 422 note hors 1..5, 201 avis valide.
  Documentation interactive : http://localhost:8000/docs.

## 3. L'équipe d'agents (streaming-ai-squad)

Graphe LangGraph (fichier `docs/graphe-squad.mmd`) :

```
prepare → developer → run_tests → reviewer → human_review ─┬─ approve → merge
              ▲                                            ├─ changes → developer
              └────────────────────────────────────────────┘
                                                           └─ reject  → discard
```

- **developer** : agent LLM (prompt `backend_developer v2`, 5 sections Context/Persona/Task/Constraints/Examples),
  outils `list_files` / `read_file` / `write_file` limités aux dossiers de la tâche ; ni shell, ni Git, ni `.env`.
- **run_tests** : exécuté par l'**orchestrateur**, jamais par le LLM (compileall + import + pytest sur le vrai cluster).
- **reviewer** : 2e agent en lecture seule (prompt `reviewer v1`), avis classé BLOQUANT / À AMÉLIORER / MINEUR.
- **human_review** : `interrupt()` LangGraph — rien n'est fusionné dans `main` sans décision.
- **Traçabilité** : chaque prompt, réponse brute, appel d'outil, test, avis et décision est un fichier JSON dans
  `ai-trace/runs/<run>/` ; chaque commit d'agent est signé « Squad Agent (rôle) ». Rapport détaillé :
  `docs/rapport-tracabilite.md` (généré par `python -m squad report`).

**Chiffres réels (7 runs)** : 307 appels au LLM — `gpt-oss-120b` ×116, `gemini-3.5-flash-lite` ×69,
`qwen3.8-27b` ×67, `gpt-oss-20b` ×51, `gemini-3.5-flash` ×4 ; ~1,29 M jetons en entrée, ~77 k en sortie ;
erreurs d'API relancées : 429 ×629, 503 ×15, 413 ×12, 400 ×10, appels d'outils invalides ×6, timeout ×2.

## 4. Décisions humaines (qui a décidé quoi)

| Tâche | Itérations | Décisions | Décidé par |
|---|---|---|---|
| T000 (pilote, bac à sable) | 1 | approve | Yassine MERDASSI |
| T001 modèle de données | 4 | changes ×3, approve | Yassine MERDASSI |
| T002 DAO v1 | 1 | reject (fichier tronqué) | Yassine MERDASSI |
| T002 DAO v2 | 4 | changes ×3, approve | Yassine MERDASSI |
| T004 1er run | 1 | reject (aucun fichier écrit) | Claude, par délégation |
| T004 métier + tests | 4 | changes ×3, approve | Claude, par délégation |
| T005 API | 3 | changes ×2, approve | Claude, par délégation |

Le 26/11/2026, le Project Owner, en révision pour un examen, a **délégué** les décisions à Claude (l'assistant qui
pilotait l'orchestrateur). Ces décisions sont enregistrées **au nom du délégué** (`squad decide … --by`), dans la
trace et dans les messages de fusion. Pour T001/T002, les textes de retour étaient souvent proposés par Claude
puis relus et lancés par le Project Owner.

## 5. Ce que le projet a montré (limites et leçons)

1. **Les LLM inventent des API** : `clustering_orders`, `.options`, `.data_type` (T001) — rattrapées par
   l'exécution réelle des tests, pas par la relecture.
2. **Le relecteur IA se trompe dans les deux sens** : il a raté une fixture qui **supprimait le keyspace de
   production** (T005 it. 2) et un `f` manquant dans une requête (bug de T002 trouvé par les tests de T004) ;
   il a bloqué T002 sur une limite de 90 lignes non exigée, et signalé à tort un import `cassandra` dans
   `services.py`. La validation humaine reste indispensable.
3. **Un test qui passe ne prouve rien si rien n'est testé** : T002 v1 (fichier tronqué) passait les anciens
   tests → ajout d'un contrôle `compileall` + import avant pytest.
4. **Offres gratuites** : Gemini en 503 pendant des heures (24/11) ; Groq limité à ~8 000 jetons/min
   (entrée + sortie demandée) → réponses tronquées, boucles de relecture. Le moteur a dû évoluer : repli entre
   modèles et fournisseurs, pauses croissantes, reprise d'un run interrompu (`squad resume`), compactage de
   l'historique, limite de 2 lectures par fichier, longueur de sortie ajustée au quota.
5. **Périmètre réduit** pour tenir le délai : recommandations retirées, T003 fusionnée dans T004 (décision du PO).
6. **Limite connue** : l'historique (`views.py`) enregistre un titre vide et une durée à 0 (valeurs provisoires
   signalées par le relecteur, non corrigées).

## 6. Reproduire

```bash
cd streaming-platform
docker compose up -d --wait                                   # cluster 3 nœuds (plusieurs minutes)
docker compose --profile tests run --rm tests                 # 24 tests
bash demo/demo_distribution.sh                                # démo panne d'un nœud
docker compose --profile tests run --rm tests python -m demo.seed   # données fictives
docker compose --profile app up -d api                        # API sur http://localhost:8000/docs

cd ../streaming-ai-squad                                      # équipe d'agents
.venv\Scripts\python -m squad run tasks/T001-modele-donnees.yaml --target ../streaming-platform
.venv\Scripts\python -m squad report --target ../streaming-platform
```

Ce qui n'a **pas** été écrit par les agents (et l'est par l'orchestrateur, Claude) : l'infrastructure Docker,
`tests/conftest.py`, `tests/test_cluster.py` (phase 1), `demo/` (démo + données fictives), ce document et le
moteur `streaming-ai-squad` lui-même.

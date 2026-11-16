# Journal — Phase 1 : environnement (16/11/2026)

**Auteur des fichiers** : Claude Code (assistant IA utilisé hors squad, en session interactive), sous la supervision de Yassine.
L'équipe d'agents n'existe pas encore : cette phase n'est **pas** du travail de la squad.

## Objectif
Infrastructure locale prête avant toute génération de code : Python 3.13, 2 dépôts git, cluster Cassandra 3 nœuds, test de connexion réellement exécuté.

## Décisions
| Décision | Raison |
|---|---|
| Python 3.13 au lieu de 3.15 | `cassandra-driver` 3.30.x supporte 3.10–3.14 (PyPI) |
| Image `cassandra:5.0` | Série GA actuelle |
| 1 datacenter `dc1`, `NetworkTopologyStrategy`, RF=3 | Démonstration de la réplication sur 3 nœuds avec un seul PC |
| Heap 768M, `mem_limit` 1700m par nœud | Docker dispose de ~7,1 Gio ; 1400m mesuré trop juste (1,36 Gio utilisés) |
| Démarrage séquentiel (`depends_on: service_healthy`) | Évite les bootstraps simultanés |
| Port 9142 côté PC | 9042 utilisé par un autre projet local |
| Tests exécutés dans un conteneur `tests` | Le pilote doit joindre les 3 nœuds ; sous Windows + Python ≥ 3.12 il n'a pas de boucle d'événements par défaut |

## Problèmes rencontrés
1. Import de `cassandra.cluster` sous Windows : `DependencyException: Unable to load a default connection class` (pas de libev, asyncore supprimé en 3.12). Les modules compilés du pilote se chargent (Smart App Control ne bloque rien) → contourné en exécutant les tests sous Linux (Docker).
2. Premier démarrage : erreur HTTP 500 transitoire de l'API Docker pendant l'arrêt d'une autre stack ; nœud 1 à 1,36/1,37 Gio → `mem_limit` relevé.
3. La stack `streaming-bigdata` a été arrêtée (`docker compose stop`, données conservées) avec l'accord de Yassine pour libérer la mémoire.

4. 1re exécution des tests : **2 réussis, 1 échoué** — `test_replication_rf3` → `OperationTimedOut` sur un DDL
   + « schema disagreement » entre nœuds, juste après le démarrage (pauses JVM de 5 à 24 s dans les logs).
   Vérification : `nodetool describecluster` → une seule version de schéma ensuite (problème transitoire).
   Correction : `request_timeout=60` et `max_schema_agreement_wait=60` via un `ExecutionProfile`
   (supprime aussi l'avertissement de dépréciation des paramètres hérités).

## Résultats des tests (exécutés réellement le 16/11/2026)
Versions : Cassandra **5.0.9**, cassandra-driver 3.30.1, pytest 9.2.0, Python 3.13.

`docker compose exec cassandra1 nodetool status` → 3 nœuds **UN** (172.20.0.2/.3/.4, dc1, rack1, 16 tokens chacun).

Après correction, 3 exécutions consécutives de `docker compose run --rm tests` :

| Exécution | Résultat |
|---|---|
| 1 | 3 passed in 6.53s |
| 2 | 3 passed in 5.55s |
| 3 | 3 passed in 5.24s |

Tests : version 5.x ; 3 nœuds visibles et up dans dc1 ; keyspace RF=3 → écriture et lecture en `ALL` OK
et le pilote voit 3 réplicas pour la clé.

Mémoire mesurée (`docker stats`) : ≈ 1,31–1,34 Gio par nœud pour une limite de 1,66 Gio.

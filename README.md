# streaming-platform

Plateforme de streaming (type Netflix) sur Apache Cassandra — projet académique NoSQL, exécuté **uniquement en local**.
Le code applicatif sera développé par l'équipe d'agents IA du dépôt voisin `streaming-ai-squad`, sous supervision humaine.

## Prérequis
- Docker Desktop (≈ 5,5 Go de RAM libres pour les 3 nœuds)
- Python 3.13 (le pilote `cassandra-driver` 3.30 ne supporte pas 3.15)

## Démarrer le cluster (3 nœuds, dc1)
```
docker compose up -d --wait        # les nœuds rejoignent l'anneau un par un (plusieurs minutes)
docker compose exec cassandra1 nodetool status
```
CQL depuis le PC : `localhost:9142` (cqlsh : `docker compose exec cassandra1 cqlsh`).

## Lancer les tests
```
docker compose run --rm tests
```
Les tests tournent dans le réseau Docker. Sous Windows avec Python ≥ 3.12, le pilote n'a pas de boucle
d'événements par défaut (ni libev ni asyncore) : le `.venv` local sert à l'éditeur, pas à exécuter les tests.

## Arrêter
```
docker compose stop      # conserve les données
docker compose down -v   # SUPPRIME les données
```

#!/usr/bin/env bash
# Démonstration de la distribution : 3 nœuds → arrêt d'un nœud → redémarrage.
# Lancer depuis la racine de streaming-platform (Git Bash) :   bash demo/demo_distribution.sh
# Sortie conservée dans reports/demo/ (preuve pour le rapport). Écrit par l'orchestrateur (Claude).
set -u
mkdir -p reports/demo
OUT="reports/demo/demo-$(date +%Y%m%d-%H%M%S).txt"
# --no-deps : sinon compose redémarre cassandra3 (dépendance du service tests) et la panne disparaît.
run() { docker compose --profile tests run --rm --no-deps -T tests python -m demo.demo_distribution "$1" 2>&1 | grep -v "Container\|level=warning" ; }
{
  echo "### Démo distribution — $(date)"
  echo; echo "--- nodetool status (3 nœuds) ---"; docker compose exec -T cassandra1 nodetool status | grep -E "^(UN|DN|UJ)"
  run "1) cluster complet : 3 nœuds UP"
  echo; echo "--- Arrêt de cassandra3 (panne simulée) ---"; docker compose stop cassandra3
  sleep 45  # laisse le temps au gossip et au pilote de voir le nœud DOWN
  docker compose exec -T cassandra1 nodetool status | grep -E "^(UN|DN)"
  run "2) un nœud en panne : ONE et QUORUM doivent réussir, ALL doit être refusé"
  echo; echo "--- Redémarrage de cassandra3 ---"; docker compose start cassandra3
  for i in $(seq 1 30); do [ "$(docker compose exec -T cassandra1 nodetool status | grep -c '^UN')" = 3 ] && break; sleep 10; done
  docker compose exec -T cassandra1 nodetool status | grep -E "^(UN|DN|UJ)"
  run "3) nœud revenu : ALL réussit de nouveau"
} | tee "$OUT"
echo; echo "Sortie enregistrée : $OUT"

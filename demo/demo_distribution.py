"""Démonstration de la distribution (exécutée DANS le réseau Docker par demo_distribution.sh).

Écrit par l'orchestrateur (Claude), pas par l'équipe d'agents : c'est un script d'exploitation pour la soutenance.
Il utilise le code applicatif des agents (schema + DAO) et montre :
  1. les 3 nœuds et le facteur de réplication 3 ;
  2. sur quels nœuds est stockée une partition (réplicas) ;
  3. selon l'état du cluster (passé en argument), quels niveaux de cohérence réussissent : ONE, QUORUM, ALL.
"""
import os
import sys
import uuid
from datetime import datetime, timezone

from cassandra import ConsistencyLevel, Unavailable
from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile
from cassandra.policies import DCAwareRoundRobinPolicy
from cassandra.query import SimpleStatement

from streaming.schema import create_schema

KS = "streaming_demo"
TITLE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")  # fixe : même partition à chaque étape


def main(step: str) -> None:
    points = os.environ.get("CASSANDRA_CONTACT_POINTS", "cassandra1").split(",")
    profile = ExecutionProfile(load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"), request_timeout=30)
    cluster = Cluster(points, execution_profiles={EXEC_PROFILE_DEFAULT: profile}, protocol_version=5)
    session = cluster.connect()
    print(f"\n===== {step} =====")
    hosts = sorted(cluster.metadata.all_hosts(), key=lambda h: str(h.endpoint))
    print("Nœuds vus par le pilote :", ", ".join(f"{h.endpoint} ({'UP' if h.is_up else 'DOWN'})" for h in hosts))

    create_schema(session, KS, replication_factor=3)
    cluster.refresh_schema_metadata()
    rs = cluster.metadata.keyspaces[KS].replication_strategy.export_for_schema()
    print("Réplication du keyspace :", rs)
    key = TITLE_ID.bytes
    replicas = cluster.metadata.get_replicas(KS, key)
    print(f"Réplicas de la partition title_id={TITLE_ID} :", ", ".join(str(r.endpoint) for r in replicas))

    for cl in (ConsistencyLevel.ONE, ConsistencyLevel.QUORUM, ConsistencyLevel.ALL):
        name = ConsistencyLevel.value_to_name[cl]
        stmt = SimpleStatement(
            f"UPDATE {KS}.title_stats SET view_count = view_count + 1 WHERE title_id = %s", consistency_level=cl)
        try:
            session.execute(stmt, (TITLE_ID,))
            row = session.execute(SimpleStatement(
                f"SELECT view_count FROM {KS}.title_stats WHERE title_id = %s", consistency_level=cl), (TITLE_ID,)).one()
            print(f"  {name:<6} : écriture + lecture OK (vues = {row.view_count})")
        except Unavailable as e:
            print(f"  {name:<6} : REFUSÉ — {e.alive_replicas} réplica(s) vivant(s) sur {e.required_replicas} requis")
        except Exception as e:  # noqa: BLE001 — on affiche l'erreur telle quelle pour la démo
            print(f"  {name:<6} : ERREUR {type(e).__name__} — {str(e)[:120]}")
    print("Horodatage :", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    cluster.shutdown()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "état courant")

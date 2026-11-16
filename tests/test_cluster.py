"""Phase 1 : vérifie que l'infrastructure distribuée fonctionne (pas encore de code applicatif)."""
from cassandra import ConsistencyLevel
from cassandra.query import SimpleStatement

KEYSPACE = "phase1_check"


def test_version_cassandra_5(session):
    version = session.execute("SELECT release_version FROM system.local").one().release_version
    assert version.startswith("5."), version


def test_trois_noeuds_visibles_et_up(cluster, session):
    hosts = cluster.metadata.all_hosts()
    assert len(hosts) == 3
    assert all(h.is_up for h in hosts)
    assert {h.datacenter for h in hosts} == {"dc1"}


def test_replication_rf3(cluster, session):
    session.execute(f"DROP KEYSPACE IF EXISTS {KEYSPACE}")
    session.execute(
        f"CREATE KEYSPACE {KEYSPACE} WITH replication = "
        "{'class': 'NetworkTopologyStrategy', 'dc1': 3}"
    )
    try:
        session.execute(f"CREATE TABLE {KEYSPACE}.t (id int PRIMARY KEY, v text)")
        session.execute(
            SimpleStatement(
                f"INSERT INTO {KEYSPACE}.t (id, v) VALUES (1, 'ok')",
                consistency_level=ConsistencyLevel.ALL,
            )
        )
        # Lecture en ALL : réussit seulement si les 3 réplicas répondent.
        row = session.execute(
            SimpleStatement(
                f"SELECT v FROM {KEYSPACE}.t WHERE id = 1",
                consistency_level=ConsistencyLevel.ALL,
            )
        ).one()
        assert row.v == "ok"

        # La clé de partition (int 1) est stockée sur les 3 nœuds.
        cluster.refresh_schema_metadata()
        routing_key = (1).to_bytes(4, "big", signed=True)
        replicas = cluster.metadata.get_replicas(KEYSPACE, routing_key)
        assert len(replicas) == 3
    finally:
        session.execute(f"DROP KEYSPACE IF EXISTS {KEYSPACE}")

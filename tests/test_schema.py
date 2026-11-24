"""Tests pour le module :pymod:`streaming.schema`.

Ces tests utilisent un keyspace dédié (``streaming_test_schema``) afin de ne jamais toucher
au keyspace de production ``streaming``.
"""

import pytest
from streaming.schema import TABLES, create_schema, drop_schema

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_KEYSPACE = "streaming_test_schema"


@pytest.fixture(autouse=True)
def _cleanup_keyspace(session):
    """Supprime le keyspace de test après chaque fonction de test.

    Le fixture ``session`` provient de ``tests/conftest.py``.
    """
    yield
    drop_schema(session, TEST_KEYSPACE)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_schema_and_idempotence(cluster, session):
    """Création du keyspace, existence des tables et idempotence de ``create_schema``.
    """
    # Nettoyage éventuel préalable
    drop_schema(session, TEST_KEYSPACE)

    # 1️⃣ première création
    create_schema(session, keyspace=TEST_KEYSPACE, replication_factor=3)
    cluster.refresh_schema_metadata()
    ks_meta = cluster.metadata.keyspaces.get(TEST_KEYSPACE)
    assert ks_meta is not None, f"Le keyspace {TEST_KEYSPACE} doit exister."

    # 2️⃣ stratégie de réplication – on utilise la chaîne exportée par le driver
    replication_cql = ks_meta.replication_strategy.export_for_schema()
    assert "NetworkTopologyStrategy" in replication_cql
    assert "'dc1': '3'" in replication_cql or "dc1': '3" in replication_cql

    # 3️⃣ toutes les tables attendues sont présentes
    for tbl in TABLES:
        assert tbl in ks_meta.tables, f"Table {tbl} manquante dans le keyspace."

    # 4️⃣ appel idempotent – aucune exception ne doit être levée
    create_schema(session, keyspace=TEST_KEYSPACE, replication_factor=3)


def test_primary_keys_and_clustering(cluster, session):
    """Vérifie la structure (clés de partition / clustering) de quelques tables clés.
    """
    drop_schema(session, TEST_KEYSPACE)
    create_schema(session, keyspace=TEST_KEYSPACE, replication_factor=3)
    cluster.refresh_schema_metadata()
    ks_meta = cluster.metadata.keyspaces[TEST_KEYSPACE]

    # Q2 – titles_by_genre : partition = genre, clustering = release_year DESC, title_id ASC
    t_q2 = ks_meta.tables["titles_by_genre"]
    assert [c.name for c in t_q2.partition_key] == ["genre"]
    assert [c.name for c in t_q2.clustering_key] == ["release_year", "title_id"]
    assert t_q2.columns["release_year"].is_reversed is True
    assert t_q2.columns["title_id"].is_reversed is False

    # Q4 – reviews_by_title : partition = title_id, clustering = created_at DESC, user_id ASC
    t_q4 = ks_meta.tables["reviews_by_title"]
    assert [c.name for c in t_q4.partition_key] == ["title_id"]
    assert [c.name for c in t_q4.clustering_key] == ["created_at", "user_id"]
    assert t_q4.columns["created_at"].is_reversed is True
    assert t_q4.columns["user_id"].is_reversed is False

    # Q7 – title_stats : table de compteurs, uniquement des colonnes counter en plus de la PK
    t_q7 = ks_meta.tables["title_stats"]
    assert [c.name for c in t_q7.partition_key] == ["title_id"]
    counter_names = {c.name for c in t_q7.columns.values() if c.cql_type == "counter"}
    assert counter_names == {"view_count", "rating_sum", "rating_count"}
    # aucune autre colonne que les compteurs et la clé primaire
    non_counter = {c.name for c in t_q7.columns.values() if c.cql_type != "counter" and c.name != "title_id"}
    assert not non_counter


def test_drop_schema(cluster, session):
    """Vérifie que ``drop_schema`` supprime correctement le keyspace de test."""
    create_schema(session, keyspace=TEST_KEYSPACE, replication_factor=3)
    drop_schema(session, TEST_KEYSPACE)
    cluster.refresh_schema_metadata()
    assert TEST_KEYSPACE not in cluster.metadata.keyspaces

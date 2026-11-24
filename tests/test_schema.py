"""Tests pour le module streaming.schema."""

import pytest
from streaming.schema import TABLES, create_schema, drop_schema

TEST_KEYSPACE = "streaming_test_schema"


@pytest.fixture(autouse=True)
def cleanup_test_keyspace(session):
    """S'assure que le keyspace de test est nettoyé après chaque test."""
    yield
    drop_schema(session, TEST_KEYSPACE)


def test_create_schema_and_verify_tables(cluster, session):
    """Vérifie la création du keyspace, l'existence des tables et l'idempotence."""
    # Nettoyage initial au cas où
    drop_schema(session, TEST_KEYSPACE)

    # 1. Premier appel : création du schéma
    create_schema(session, keyspace=TEST_KEYSPACE, replication_factor=3)

    # Rafraîchir les métadonnées
    cluster.refresh_schema_metadata()
    keyspace_meta = cluster.metadata.keyspaces.get(TEST_KEYSPACE)
    assert keyspace_meta is not None, f"Le keyspace {TEST_KEYSPACE} doit exister."

    # Vérification de la stratégie de réplication
    assert keyspace_meta.replication_strategy.name == "org.apache.cassandra.locator.NetworkTopologyStrategy"
    assert keyspace_meta.replication_strategy.options.get("dc1") == "3"

    # Vérification de l'existence de toutes les tables
    for table_name in TABLES:
        assert table_name in keyspace_meta.tables, f"La table {table_name} doit exister dans le keyspace."

    # 2. Deuxième appel : vérifier l'idempotence (ne doit pas lever d'erreur)
    create_schema(session, keyspace=TEST_KEYSPACE, replication_factor=3)


def test_table_primary_keys_and_clustering(cluster, session):
    """Vérifie la structure (clés de partition et clustering) sur quelques tables clés."""
    drop_schema(session, TEST_KEYSPACE)
    create_schema(session, keyspace=TEST_KEYSPACE, replication_factor=3)

    cluster.refresh_schema_metadata()
    keyspace_meta = cluster.metadata.keyspaces[TEST_KEYSPACE]

    # Vérification Q2 : titles_by_genre
    # Partition key: genre ; Clustering key: release_year DESC, title_id ASC
    t_q2 = keyspace_meta.tables["titles_by_genre"]
    partition_cols = [c.name for c in t_q2.partition_key]
    clustering_cols = [c.name for c in t_q2.clustering_key]
    clustering_orders = t_q2.clustering_orders

    assert partition_cols == ["genre"]
    assert clustering_cols == ["release_year", "title_id"]
    assert clustering_orders[0] == "DESC"  # release_year DESC
    assert clustering_orders[1] == "ASC"   # title_id ASC

    # Vérification Q4 : reviews_by_title
    # Partition key: title_id ; Clustering key: created_at DESC, user_id ASC
    t_q4 = keyspace_meta.tables["reviews_by_title"]
    assert [c.name for c in t_q4.partition_key] == ["title_id"]
    assert [c.name for c in t_q4.clustering_key] == ["created_at", "user_id"]
    assert t_q4.clustering_orders[0] == "DESC"  # created_at DESC

    # Vérification Q7 : title_stats (counters)
    t_q7 = keyspace_meta.tables["title_stats"]
    assert [c.name for c in t_q7.partition_key] == ["title_id"]
    counter_cols = {c.name for c in t_q7.columns.values() if c.data_type.name == "counter"}
    assert counter_cols == {"view_count", "rating_sum", "rating_count"}


def test_drop_schema(cluster, session):
    """Vérifie que drop_schema supprime correctement le keyspace."""
    create_schema(session, keyspace=TEST_KEYSPACE, replication_factor=3)
    drop_schema(session, TEST_KEYSPACE)

    cluster.refresh_schema_metadata()
    assert TEST_KEYSPACE not in cluster.metadata.keyspaces

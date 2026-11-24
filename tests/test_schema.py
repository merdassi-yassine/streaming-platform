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

    # Vérification de la stratégie de réplication (nom court ou nom complet selon la version du driver/cluster)
    strat_name = keyspace_meta.replication_strategy.name
    assert "NetworkTopologyStrategy" in strat_name
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

    assert partition_cols == ["genre"]
    assert clustering_cols == ["release_year", "title_id"]
    # Vérification de l'ordre de clustering via is_reversed sur les colonnes de clustering
    assert t_q2.columns["release_year"].is_reversed is True   # release_year DESC
    assert t_q2.columns["title_id"].is_reversed is False      # title_id ASC

    # Vérification Q4 : reviews_by_title
    # Partition key: title_id ; Clustering key: created_at DESC, user_id ASC
    t_q4 = keyspace_meta.tables["reviews_by_title"]
    assert [c.name for c in t_q4.partition_key] == ["title_id"]
    assert [c.name for c in t_q4.clustering_key] == ["created_at", "user_id"]
    assert t_q4.columns["created_at"].is_reversed is True     # created_at DESC
    assert t_q4.columns["user_id"].is_reversed is False       # user_id ASC

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

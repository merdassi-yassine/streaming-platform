"""Définition du schéma Cassandra pour la plateforme de streaming.

Modélisation orientée requêtes (une table par requête Q1..Q8).
"""

KEYSPACE = "streaming"

TABLES = [
    "title_by_id",
    "titles_by_genre",
    "user_by_id",
    "reviews_by_title",
    "reviews_by_user",
    "watch_history_by_user",
    "title_stats",
    "daily_views_by_title",
]


def create_schema(session, keyspace: str = KEYSPACE, replication_factor: int = 3) -> None:
    """Crée le keyspace et les tables de la plateforme de streaming (idempotent).

    Args:
        session: Session cassandra-driver ouverte.
        keyspace: Nom du keyspace à créer/utiliser.
        replication_factor: Facteur de réplication pour le datacenter 'dc1'.
    """
    create_keyspace_cql = f"""
    CREATE KEYSPACE IF NOT EXISTS {keyspace}
    WITH replication = {{
        'class': 'NetworkTopologyStrategy',
        'dc1': {replication_factor}
    }}
    """
    session.execute(create_keyspace_cql)

    # Q1 : Fiche d'un titre (film ou série) par son identifiant.
    # Clé de partition : title_id.
    create_q1 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.title_by_id (
        title_id uuid,
        title text,
        kind text,
        release_year int,
        genres set<text>,
        synopsis text,
        duration_minutes int,
        episodes_count int,
        PRIMARY KEY (title_id)
    )
    """

    # Q2 : Titres d'un genre, du plus récent au plus ancien.
    # Clé de partition : genre. Clé de clustering : release_year DESC, title_id ASC.
    create_q2 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.titles_by_genre (
        genre text,
        release_year int,
        title_id uuid,
        title text,
        kind text,
        PRIMARY KEY (genre, release_year, title_id)
    ) WITH CLUSTERING ORDER BY (release_year DESC, title_id ASC)
    """

    # Q3 : Profil d'un utilisateur par son identifiant.
    # Clé de partition : user_id.
    create_q3 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.user_by_id (
        user_id uuid,
        email text,
        username text,
        created_at timestamp,
        PRIMARY KEY (user_id)
    )
    """

    # Q4 : Avis (note 1 à 5 + commentaire) d'un titre, du plus récent au plus ancien.
    # Clé de partition : title_id. Clé de clustering : created_at DESC, user_id ASC.
    create_q4 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.reviews_by_title (
        title_id uuid,
        created_at timestamp,
        user_id uuid,
        rating int,
        comment text,
        username text,
        PRIMARY KEY (title_id, created_at, user_id)
    ) WITH CLUSTERING ORDER BY (created_at DESC, user_id ASC)
    """

    # Q5 : Avis donnés par un utilisateur, du plus récent au plus ancien.
    # Clé de partition : user_id. Clé de clustering : created_at DESC, title_id ASC.
    create_q5 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.reviews_by_user (
        user_id uuid,
        created_at timestamp,
        title_id uuid,
        rating int,
        comment text,
        title text,
        PRIMARY KEY (user_id, created_at, title_id)
    ) WITH CLUSTERING ORDER BY (created_at DESC, title_id ASC)
    """

    # Q6 : Historique de visionnage d'un utilisateur, du plus récent au plus ancien.
    # Clé de partition : user_id. Clé de clustering : watched_at DESC, title_id ASC.
    create_q6 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.watch_history_by_user (
        user_id uuid,
        watched_at timestamp,
        title_id uuid,
        title text,
        duration_watched_seconds int,
        completed boolean,
        PRIMARY KEY (user_id, watched_at, title_id)
    ) WITH CLUSTERING ORDER BY (watched_at DESC, title_id ASC)
    """

    # Q7 : Statistiques d'un titre : nombre de vues, somme et nombre des notes (compteurs).
    # Clé de partition : title_id.
    # Remarque Cassandra : Une table avec des counters ne doit contenir QUE des colonnes counter et la clé primaire.
    create_q7 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.title_stats (
        title_id uuid,
        view_count counter,
        rating_sum counter,
        rating_count counter,
        PRIMARY KEY (title_id)
    )
    """

    # Q8 : Nombre de vues de chaque titre pour un jour donné (pour calculer le Top 10 du jour).
    # Clé de partition : view_date. Clé de clustering : title_id.
    # Remarque Cassandra : Une table avec des counters ne doit contenir QUE des colonnes counter et la clé primaire.
    create_q8 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.daily_views_by_title (
        view_date date,
        title_id uuid,
        view_count counter,
        PRIMARY KEY (view_date, title_id)
    )
    """

    queries = [
        create_q1,
        create_q2,
        create_q3,
        create_q4,
        create_q5,
        create_q6,
        create_q7,
        create_q8,
    ]

    for q in queries:
        session.execute(q)


def drop_schema(session, keyspace: str) -> None:
    """Supprime le keyspace spécifié (idempotent avec IF EXISTS).

    Args:
        session: Session cassandra-driver ouverte.
        keyspace: Nom du keyspace à supprimer.
    """
    session.execute(f"DROP KEYSPACE IF EXISTS {keyspace}")

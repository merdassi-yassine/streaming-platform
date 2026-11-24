"""Définition du schéma Cassandra pour la plateforme de streaming.

Modélisation orientée requêtes (une table par requête Q1..Q8).
"""

# Nom du keyspace principal de l'application (production).
KEYSPACE = "streaming"

# Liste ordonnée des tables créées – utilisée par les tests.
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
    """Crée le keyspace et les tables (idempotent).

    Tous les ``CREATE ... IF NOT EXISTS`` garantissent que l'appel est sûr à répéter.
    Le keyspace utilise ``NetworkTopologyStrategy`` avec le datacenter ``dc1``.
    """
    # ---------------------------------------------------------------------
    # Keyspace
    # ---------------------------------------------------------------------
    create_keyspace_cql = f"""
    CREATE KEYSPACE IF NOT EXISTS {keyspace}
    WITH replication = {{
        'class': 'NetworkTopologyStrategy',
        'dc1': {replication_factor}
    }}
    """
    session.execute(create_keyspace_cql)

    # ---------------------------------------------------------------------
    # Tables – une par requête (Q1..Q8). Chaque table possède un COMMENT
    # indiquant la requête qu'elle sert.
    # ---------------------------------------------------------------------
    # Q1 : fiche d'un titre (film ou série) par son identifiant.
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
    ) WITH comment = 'Q1: fiche d''un titre (film ou série) par son identifiant.'
    """

    # Q2 : titres d'un genre, du plus récent au plus ancien.
    create_q2 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.titles_by_genre (
        genre text,
        release_year int,
        title_id uuid,
        title text,
        kind text,
        PRIMARY KEY (genre, release_year, title_id)
    ) WITH CLUSTERING ORDER BY (release_year DESC, title_id ASC)
      AND comment = 'Q2: titres d''un genre, du plus récent au plus ancien.'
    """

    # Q3 : profil d'un utilisateur par son identifiant.
    create_q3 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.user_by_id (
        user_id uuid,
        email text,
        username text,
        created_at timestamp,
        PRIMARY KEY (user_id)
    ) WITH comment = 'Q3: profil d''un utilisateur par son identifiant.'
    """

    # Q4 : avis (note 1 à 5 + commentaire) d'un titre, du plus récent au plus ancien.
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
      AND comment = 'Q4: avis (note 1 à 5 + commentaire) d''un titre, du plus récent au plus ancien.'
    """

    # Q5 : avis donnés par un utilisateur, du plus récent au plus ancien.
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
      AND comment = 'Q5: avis donnés par un utilisateur, du plus récent au plus ancien.'
    """

    # Q6 : historique de visionnage d'un utilisateur, du plus récent au plus ancien.
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
      AND comment = 'Q6: historique de visionnage d''un utilisateur, du plus récent au plus ancien.'
    """

    # Q7 : statistiques d'un titre (compteurs uniquement).
    create_q7 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.title_stats (
        title_id uuid,
        view_count counter,
        rating_sum counter,
        rating_count counter,
        PRIMARY KEY (title_id)
    ) WITH comment = 'Q7: statistiques d''un titre (nombre de vues, somme et nombre des notes).'
    """

    # Q8 : nombre de vues de chaque titre pour un jour donné (compteurs uniquement).
    create_q8 = f"""
    CREATE TABLE IF NOT EXISTS {keyspace}.daily_views_by_title (
        view_date date,
        title_id uuid,
        view_count counter,
        PRIMARY KEY (view_date, title_id)
    ) WITH comment = 'Q8: nombre de vues de chaque titre pour un jour donné.'
    """

    for query in [
        create_q1,
        create_q2,
        create_q3,
        create_q4,
        create_q5,
        create_q6,
        create_q7,
        create_q8,
    ]:
        session.execute(query)


def drop_schema(session, keyspace: str) -> None:
    """Supprime le keyspace (idempotent)."""
    session.execute(f"DROP KEYSPACE IF EXISTS {keyspace}")

"""Crée le keyspace de production « streaming » et y insère un petit jeu de données de démonstration.

Script d'exploitation écrit par l'orchestrateur (Claude) ; il n'utilise que le code des agents (schema + DAO).
Données FICTIVES (titres, utilisateurs, avis, vues) : à présenter comme telles.
Lancement : docker compose --profile tests run --rm tests python -m demo.seed
"""
import os
import uuid
from datetime import datetime, timezone

from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile
from cassandra.policies import DCAwareRoundRobinPolicy

from streaming.dao import RatingDAO, TitleDAO, UserDAO, ViewDAO
from streaming.models import Title, User
from streaming.schema import KEYSPACE, create_schema

TITLES = [
    ("Le Dernier Signal", "film", 2024, {"science-fiction"}),
    ("Médina Secrète", "serie", 2023, {"drame", "thriller"}),
    ("Rires de Bizerte", "film", 2022, {"comedie"}),
    ("Orbite Basse", "serie", 2025, {"science-fiction", "drame"}),
    ("La Route du Sel", "film", 2021, {"aventure"}),
]


def main() -> None:
    points = os.environ.get("CASSANDRA_CONTACT_POINTS", "cassandra1").split(",")
    profile = ExecutionProfile(load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"), request_timeout=60)
    cluster = Cluster(points, execution_profiles={EXEC_PROFILE_DEFAULT: profile}, protocol_version=5)
    session = cluster.connect()
    create_schema(session, KEYSPACE, replication_factor=3)
    titles, users = TitleDAO(session, KEYSPACE), UserDAO(session, KEYSPACE)
    ratings, views = RatingDAO(session, KEYSPACE), ViewDAO(session, KEYSPACE)

    ids = []
    for name, kind, year, genres in TITLES:
        t = Title(uuid.uuid4(), name, kind, year, genres, f"Synopsis fictif de {name}.", 100, None)
        titles.save(t)
        ids.append(t.title_id)
    now = datetime.now(timezone.utc)
    user_ids = []
    for i in range(1, 4):
        u = User(uuid.uuid4(), f"demo{i}@example.com", f"spectateur{i}", now)
        users.save(u)
        user_ids.append(u.user_id)
    for n, tid in enumerate(ids):  # nombre de vues décroissant : le Top 10 du jour a un ordre clair
        for k in range(len(ids) - n):
            views.record_view(user_ids[k % 3], tid, now)
    ratings.add(user_ids[0], ids[0], 5, "Excellent")
    ratings.add(user_ids[1], ids[0], 4, "Très bon")
    ratings.add(user_ids[2], ids[1], 3, "Correct")
    print("Keyspace :", KEYSPACE)
    print("Titres   :", ", ".join(f"{t[0]}={i}" for t, i in zip(TITLES, ids)))
    print("Utilisateurs :", ", ".join(map(str, user_ids)))
    print("Jour     :", now.date().isoformat())
    cluster.shutdown()


if __name__ == "__main__":
    main()

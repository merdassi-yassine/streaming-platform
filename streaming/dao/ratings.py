"""DAO des évaluations (tables Q4, Q5 et compteurs Q7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Dict

from cassandra.query import BatchStatement

from ..models import User, Title


class RatingDAO:
    """Accès aux avis d'utilisateurs.

    - ``add`` écrit les deux tables d'avis et met à jour les compteurs de notes.
    - ``list_for_title`` et ``list_for_user`` lisent les avis par partition.
    """

    def __init__(self, session, keyspace: str) -> None:
        self._session = session
        self._ks = keyspace
        # INSERT Q4 : reviews_by_title
        self._stmt_insert_title = session.prepare(
            f"INSERT INTO {keyspace}.reviews_by_title "
            "(title_id, created_at, user_id, rating, comment, username) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        # INSERT Q5 : reviews_by_user
        self._stmt_insert_user = session.prepare(
            f"INSERT INTO {keyspace}.reviews_by_user "
            "(user_id, created_at, title_id, rating, comment, title) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        # UPDATE Q7 : compteurs rating_sum et rating_count
        self._stmt_update_counters = session.prepare(
            f"UPDATE {keyspace}.title_stats SET rating_sum = rating_sum + ?, rating_count = rating_count + 1 WHERE title_id = ?"
        )
        # SELECT Q4
        self._stmt_list_by_title = session.prepare(
            f"SELECT created_at, user_id, rating, comment, username FROM {keyspace}.reviews_by_title "
            "WHERE title_id = ? LIMIT ?"
        )
        # SELECT Q5
        self._stmt_list_by_user = session.prepare(
            f"SELECT created_at, title_id, rating, comment, title FROM {keyspace}.reviews_by_user "
            "WHERE user_id = ? LIMIT ?"
        )

    def add(
        self,
        user_id: uuid.UUID,
        title_id: uuid.UUID,
        rating: int,
        comment: str | None = None,
        username: str | None = None,
        title: str | None = None,
    ) -> None:
        """Ajoute un avis.

        ``rating`` doit être compris entre 1 et 5, sinon ``ValueError`` est levée.
        L'insertion dans les tables d'avis est faite dans un ``BatchStatement`` LOGGED.
        Les compteurs sont mis à jour séparément (les compteurs ne peuvent pas être dans le même batch).
        """
        if not 1 <= rating <= 5:
            raise ValueError("rating must be between 1 and 5")

        created_at = datetime.utcnow()
        # Batch normal inserts
        batch = BatchStatement()
        batch.add(self._stmt_insert_title, (title_id, created_at, user_id, rating, comment, username))
        batch.add(self._stmt_insert_user, (user_id, created_at, title_id, rating, comment, title))
        self._session.execute(batch)
        # Counter update (separate)
        self._session.execute(self._stmt_update_counters, (rating, title_id))

    def list_for_title(self, title_id: uuid.UUID, limit: int = 20) -> List[Dict]:
        """Retourne les avis d'un titre, du plus récent au plus ancien."""
        rows = self._session.execute(self._stmt_list_by_title, (title_id, limit))
        return [
            {
                "created_at": r.created_at,
                "user_id": r.user_id,
                "rating": r.rating,
                "comment": r.comment,
                "username": r.username,
            }
            for r in rows
        ]

    def list_for_user(self, user_id: uuid.UUID, limit: int = 20) -> List[Dict]:
        """Retourne les avis d'un utilisateur, du plus récent au plus ancien."""
        rows = self._session.execute(self._stmt_list_by_user, (user_id, limit))
        return [
            {
                "created_at": r.created_at,
                "title_id": r.title_id,
                "rating": r.rating,
                "comment": r.comment,
                "title": r.title,
            }
            for r in rows
        ]

"""DAO des historiques de visionnage et des compteurs de vues (tables Q6, Q7, Q8)."""

from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Dict, List

from cassandra.query import BatchStatement


class ViewDAO:
    """Accès aux tables d'historique et de statistiques de vues."""

    def __init__(self, session, keyspace: str) -> None:
        self._session = session
        self._ks = keyspace
        # INSERT Q6 : watch_history_by_user
        self._stmt_insert_history = session.prepare(
            f"INSERT INTO {keyspace}.watch_history_by_user "
            "(user_id, watched_at, title_id, title, duration_watched_seconds, completed) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        # UPDATE Q7 : title_stats.view_count
        self._stmt_update_view_count = session.prepare(
            f"UPDATE {keyspace}.title_stats SET view_count = view_count + 1 WHERE title_id = ?"
        )
        # UPDATE Q8 : daily_views_by_title.view_count
        self._stmt_update_daily_view_count = session.prepare(
            f"UPDATE {keyspace}.daily_views_by_title SET view_count = view_count + 1 "
            "WHERE view_date = ? AND title_id = ?"
        )
        # SELECT Q6 : history per user
        self._stmt_history = session.prepare(
            f"SELECT watched_at, title_id, title, duration_watched_seconds, completed FROM {keyspace}.watch_history_by_user "
            "WHERE user_id = ? LIMIT ?"
        )
        # SELECT Q8 : views per day
        self._stmt_views_of_day = session.prepare(
            f"SELECT title_id, view_count FROM {keyspace}.daily_views_by_title WHERE view_date = ?"
        )

    def record_view(self, user_id: uuid.UUID, title_id: uuid.UUID, viewed_at: datetime) -> None:
        """Enregistre une visionnage et incrémente les compteurs."""
        # Normal insert into history
        batch = BatchStatement()
        batch.add(self._stmt_insert_history, (
            user_id,
            viewed_at,
            title_id,
            "",  # title text not provided
            0,    # duration_watched_seconds placeholder
            False,  # completed placeholder
        ))
        self._session.execute(batch)
        # Counter updates (separate)
        self._session.execute(self._stmt_update_view_count, (title_id,))
        self._session.execute(self._stmt_update_daily_view_count, (viewed_at.date(), title_id))

    def history(self, user_id: uuid.UUID, limit: int = 20) -> List[Dict]:
        """Retourne l'historique de visionnage d'un utilisateur."""
        rows = self._session.execute(self._stmt_history, (user_id, limit))
        return [
            {
                "watched_at": r.watched_at,
                "title_id": r.title_id,
                "title": r.title,
                "duration_watched_seconds": r.duration_watched_seconds,
                "completed": r.completed,
            }
            for r in rows
        ]

    def views_of_day(self, day: date) -> Dict[uuid.UUID, int]:
        """Retourne un dictionnaire title_id -> nombre de vues pour le jour donné."""
        rows = self._session.execute(self._stmt_views_of_day, (day,))
        return {r.title_id: r.view_count for r in rows}

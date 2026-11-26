"""DAO des titres (tables Q1 et Q2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from cassandra.query import BatchStatement

from ..models import Title


class TitleDAO:
    """Accès aux tables ``title_by_id`` (Q1) et ``titles_by_genre`` (Q2)."""

    def __init__(self, session, keyspace: str) -> None:
        self._session = session
        self._ks = keyspace
        # INSERT Q1
        self._stmt_save_q1 = session.prepare(
            f"INSERT INTO {keyspace}.title_by_id "
            "(title_id, title, kind, release_year, genres, synopsis, "
            "duration_minutes, episodes_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        # INSERT Q2 (une ligne par genre)
        self._stmt_save_q2 = session.prepare(
            f"INSERT INTO {keyspace}.titles_by_genre "
            "(genre, release_year, title_id, title, kind) VALUES (?, ?, ?, ?, ?)"
        )
        # SELECT Q1
        self._stmt_get_q1 = session.prepare(
            f"SELECT title_id, title, kind, release_year, genres, synopsis, "
            f"duration_minutes, episodes_count FROM {keyspace}.title_by_id WHERE title_id = ?"
        )
        # SELECT Q2 (liste par genre)
        self._stmt_list_by_genre = session.prepare(
            f"SELECT title_id, title, kind, release_year FROM {keyspace}.titles_by_genre "
            "WHERE genre = ? LIMIT ?"
        )

    def save(self, title: Title) -> None:
        """Enregistre la fiche du titre et les entrées par genre.

        Utilise un ``BatchStatement`` LOGGED pour garantir l'atomicité entre Q1 et Q2.
        """
        batch = BatchStatement()
        batch.add(self._stmt_save_q1, (
            title.title_id,
            title.title,
            title.kind,
            title.release_year,
            set(title.genres),
            title.synopsis,
            title.duration_minutes,
            title.episodes_count,
        ))
        for genre in title.genres:
            batch.add(self._stmt_save_q2, (
                genre,
                title.release_year,
                title.title_id,
                title.title,
                title.kind,
            ))
        self._session.execute(batch)

    def get(self, title_id: uuid.UUID) -> Optional[Title]:
        """Retourne la fiche d'un titre ou ``None`` s'il n'existe pas."""
        row = self._session.execute(self._stmt_get_q1, (title_id,)).one()
        if row is None:
            return None
        return Title(
            title_id=row.title_id,
            title=row.title,
            kind=row.kind,
            release_year=row.release_year,
            genres=set(row.genres),
            synopsis=row.synopsis,
            duration_minutes=row.duration_minutes,
            episodes_count=row.episodes_count,
        )

    def list_by_genre(self, genre: str, limit: int = 20) -> List[dict]:
        """Liste les titres d'un genre, du plus récent au plus ancien.

        Retourne une liste de dictionnaires contenant ``title_id``, ``title``, ``kind`` et ``release_year``.
        """
        rows = self._session.execute(self._stmt_list_by_genre, (genre, limit))
        return [
            {
                "title_id": r.title_id,
                "title": r.title,
                "kind": r.kind,
                "release_year": r.release_year,
            }
            for r in rows
        ]

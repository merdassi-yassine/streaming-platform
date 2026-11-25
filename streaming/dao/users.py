"""DAO des utilisateurs (table Q3)."""

from __future__ import annotations

import uuid
from typing import Optional

from ..models import User


class UserDAO:
    """Accès à la table ``user_by_id`` (Q3)."""

    def __init__(self, session, keyspace: str) -> None:
        self._session = session
        self._ks = keyspace
        self._stmt_save = session.prepare(
            f"INSERT INTO {keyspace}.user_by_id "
            "(user_id, email, username, created_at) VALUES (?, ?, ?, ?)"
        )
        self._stmt_get = session.prepare(
            f"SELECT user_id, email, username, created_at "
            f"FROM {keyspace}.user_by_id WHERE user_id = ?"
        )

    def save(self, user: User) -> None:
        """Enregistre ou met à jour le profil d'un utilisateur."""
        self._session.execute(self._stmt_save, (
            user.user_id,
            user.email,
            user.username,
            user.created_at,
        ))

    def get(self, user_id: uuid.UUID) -> Optional[User]:
        """Retourne le profil d'un utilisateur ou ``None`` s'il n'existe pas."""
        row = self._session.execute(self._stmt_get, (user_id,)).one()
        if row is None:
            return None
        return User(
            user_id=row.user_id,
            email=row.email,
            username=row.username,
            created_at=row.created_at,
        )
"""DAO pour la table title_stats.

La classe ne fait que lire les compteurs d'un titre.
"""

from __future__ import annotations

from cassandra.cluster import Session
from typing import Tuple


class StatsDAO:
    """Accès aux statistiques d'un titre.

    La table ``title_stats`` contient uniquement des compteurs.  La méthode
    :py:meth:`get` renvoie un tuple ``(view_count, rating_sum, rating_count)``.
    """

    def __init__(self, session: Session, keyspace: str):
        self._session = session
        self._keyspace = keyspace
        self._get_stmt = session.prepare(
            f"SELECT view_count, rating_sum, rating_count FROM {keyspace}.title_stats WHERE title_id = ?"
        )

    def get(self, title_id) -> Tuple[int, int, int]:
        """Renvoie les compteurs pour *title_id*.

        Si le titre n'existe pas, la méthode renvoie ``(0, 0, 0)``.
        """
        row = self._session.execute(self._get_stmt, (title_id,)).one()
        if row is None:
            return 0, 0, 0
        return row.view_count, row.rating_sum, row.rating_count

"""Modèles de données simples utilisés par les DAO.

Ces dataclasses ne contiennent que les champs nécessaires aux tables Cassandra.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Optional, Set


@dataclass(frozen=True)
class Title:
    """Représente la fiche d'un titre (film ou série)."""

    title_id: uuid.UUID
    title: str
    kind: str  # "movie" ou "series"
    release_year: int
    genres: Set[str]
    synopsis: Optional[str] = None
    duration_minutes: Optional[int] = None  # pour les films
    episodes_count: Optional[int] = None  # pour les séries


@dataclass(frozen=True)
class User:
    """Profil d'un utilisateur."""

    user_id: uuid.UUID
    email: str
    username: str
    created_at: datetime.datetime

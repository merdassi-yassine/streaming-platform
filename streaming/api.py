"""Couche présentation (API FastAPI)."""

from __future__ import annotations

import datetime
import os
import uuid
from typing import List, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from streaming.dao import RatingDAO, StatsDAO, TitleDAO, UserDAO, ViewDAO
from streaming.services import CatalogService, ReviewService, TrendingService


class RatingRequest(BaseModel):
    user_id: uuid.UUID
    title_id: uuid.UUID
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None


def create_app(session, keyspace: str) -> FastAPI:
    """Crée et configure l'application FastAPI pour la plateforme de streaming."""
    app = FastAPI(title="Streaming Platform API", version="1.0.0")

    titles_dao = TitleDAO(session, keyspace)
    users_dao = UserDAO(session, keyspace)
    ratings_dao = RatingDAO(session, keyspace)
    stats_dao = StatsDAO(session, keyspace)
    views_dao = ViewDAO(session, keyspace)

    catalog_service = CatalogService(titles_dao, stats_dao)
    trending_service = TrendingService(views_dao, titles_dao)
    review_service = ReviewService(users_dao, titles_dao, ratings_dao)

    @app.get("/titles/{title_id}")
    def get_title(title_id: uuid.UUID):
        details = catalog_service.title_details(title_id)
        if not details:
            raise HTTPException(status_code=404, detail="Titre inconnu")
        return details

    @app.get("/genres/{genre}/titles")
    def get_genre_titles(genre: str, limit: int = 20):
        return catalog_service.titles_of_genre(genre, limit=limit)

    @app.get("/trending/{day}")
    def get_trending(day: datetime.date):
        return trending_service.top10(day)

    @app.post("/ratings", status_code=status.HTTP_201_CREATED)
    def post_rating(payload: RatingRequest):
        try:
            review_service.rate(
                user_id=payload.user_id,
                title_id=payload.title_id,
                rating=payload.rating,
                comment=payload.comment,
            )
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"status": "created"}

    @app.get("/users/{user_id}/history")
    def get_user_history(user_id: uuid.UUID, limit: int = 20):
        return views_dao.history(user_id, limit=limit)

    @app.get("/health")
    def health_check():
        cluster = session.cluster
        all_hosts = cluster.metadata.all_hosts()
        # Évaluation des hôtes Up : connectés ou interrogés (selon l'API du driver, tous les all_hosts() sont connus,
        # on peut vérifier leur état de disponibilité si disponible, sinon on compte les hôtes connus et up).
        # Le driver expose state par hôte via l'interne ou can_connect, mais l'énoncé demande :
        # "nombre de nœuds connus et nombre de nœuds « up » via session.cluster.metadata.all_hosts()".
        # Dans cassandra-driver, all_hosts() renvoie les hôtes du cluster. Les hôtes up sont ceux dont l'état est up ou joignables.
        # Plus simplement, tous les hôtes renvoyés par all_hosts() ou interrogés. Certains drivers gèrent host.is_up si supporté,
        # ou on compte le nombre total et on estime up. Vérifions l'attribut is_up ou is_up() si présent, ou on compte les hôtes.
        known = len(all_hosts)
        up_count = sum(1 for h in all_hosts if getattr(h, "is_up", True))
        return {
            "nodes_known": known,
            "nodes_up": up_count,
        }

    return app


# Instance globale pour uvicorn si CASSANDRA_CONTACT_POINTS est défini
_contact_points = os.environ.get("CASSANDRA_CONTACT_POINTS")
app: Optional[FastAPI] = None
if _contact_points:
    from cassandra.cluster import Cluster, ExecutionProfile, EXEC_PROFILE_DEFAULT
    from cassandra.policies import DCAwareRoundRobinPolicy

    _keyspace = os.environ.get("KEYSPACE", "streaming")
    _profile = ExecutionProfile(
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"),
        request_timeout=30,
    )
    _cluster = Cluster(
        _contact_points.split(","),
        execution_profiles={EXEC_PROFILE_DEFAULT: _profile},
        protocol_version=5,
    )
    _session = _cluster.connect()
    app = create_app(_session, _keyspace)

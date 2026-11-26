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
        known = len(all_hosts)
        up_count = sum(1 for h in all_hosts if h.is_up)
        return {
            "nodes_known": known,
            "nodes_up": up_count,
        }

    return app


def build_app() -> FastAPI:
    """Factory pour uvicorn (--factory streaming.api:build_app).

    Initialise la connexion Cluster/Session à partir des variables d'environnement
    sans rien exécuter au moment de l'import du module.
    """
    contact_points = os.environ.get("CASSANDRA_CONTACT_POINTS", "cassandra1").split(",")
    keyspace = os.environ.get("KEYSPACE", "streaming")

    from cassandra.cluster import Cluster, ExecutionProfile, EXEC_PROFILE_DEFAULT
    from cassandra.policies import DCAwareRoundRobinPolicy

    profile = ExecutionProfile(
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"),
        request_timeout=30,
    )
    cluster = Cluster(
        contact_points,
        execution_profiles={EXEC_PROFILE_DEFAULT: profile},
        protocol_version=5,
    )
    session = cluster.connect()
    return create_app(session, keyspace)

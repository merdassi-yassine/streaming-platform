"""Client HTTP (httpx) pour communiquer avec l'API FastAPI."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

import httpx
from django.conf import settings


def _get_client() -> httpx.Client:
    """Retourne un client httpx configuré avec l'URL de base et un timeout."""
    return httpx.Client(base_url=settings.API_BASE_URL, timeout=10.0)


def health() -> Dict[str, Any]:
    """Récupère l'état de santé et les nœuds du cluster."""
    with _get_client() as client:
        response = client.get("/health")
        response.raise_for_status()
        return response.json()


def trending(day: Optional[str] = None) -> List[Dict[str, Any]]:
    """Récupère le top 10 des titres pour une date donnée (YYYY-MM-DD) ou la date du jour."""
    if not day:
        day = datetime.date.today().isoformat()
    with _get_client() as client:
        response = client.get(f"/trending/{day}")
        response.raise_for_status()
        return response.json()


def genre_titles(genre: str) -> List[Dict[str, Any]]:
    """Récupère la liste des titres pour un genre donné."""
    with _get_client() as client:
        response = client.get(f"/genres/{genre}/titles")
        response.raise_for_status()
        return response.json()


def get_title(title_id: str) -> Optional[Dict[str, Any]]:
    """Récupère la fiche détaillée d'un titre, ou None si 404."""
    with _get_client() as client:
        response = client.get(f"/titles/{title_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


def history(user_id: str) -> List[Dict[str, Any]]:
    """Récupère l'historique de visionnage d'un utilisateur."""
    with _get_client() as client:
        response = client.get(f"/users/{user_id}/history")
        response.raise_for_status()
        return response.json()


def post_rating(user_id: str, title_id: str, rating: int, comment: Optional[str] = None) -> int:
    """Envoie un avis / note sur un titre et retourne le code HTTP."""
    payload: Dict[str, Any] = {
        "user_id": user_id,
        "title_id": title_id,
        "rating": rating,
    }
    if comment:
        payload["comment"] = comment

    with _get_client() as client:
        response = client.post("/ratings", json=payload)
        return response.status_code

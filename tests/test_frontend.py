"""Tests unitaires et fonctionnels pour l'interface web frontend (Django)."""

import os
import pytest
import httpx

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "frontend.settings")
import django
django.setup()

from django.test import Client
from frontend import api_client


@pytest.fixture
def client():
    """Client de test Django."""
    return Client()


def test_home_view(monkeypatch, client):
    """Teste la vue d'accueil avec affichage du cluster et du top 10."""
    monkeypatch.setattr(api_client, "health", lambda: {"nodes_known": 3, "nodes_up": 3})
    monkeypatch.setattr(
        api_client,
        "trending",
        lambda day: [
            {
                "title": {
                    "title_id": "123e4567-e89b-12d3-a456-426614174000",
                    "title": "Film Test",
                    "kind": "movie",
                    "release_year": 2024,
                    "genres": ["Action"],
                },
                "views": 42,
            }
        ],
    )

    response = client.get("/")
    assert response.status_code == 200
    assert b"Film Test" in response.content
    assert b"3" in response.content


def test_genre_view(monkeypatch, client):
    """Teste la vue des titres d'un genre."""
    monkeypatch.setattr(
        api_client,
        "genre_titles",
        lambda genre: [
            {
                "title_id": "123e4567-e89b-12d3-a456-426614174000",
                "title": "Action Movie",
                "kind": "movie",
                "release_year": 2023,
            }
        ],
    )

    response = client.get("/genres/Action/")
    assert response.status_code == 200
    assert b"Action Movie" in response.content
    assert b"Action" in response.content


def test_title_detail_view(monkeypatch, client):
    """Teste la fiche détaillée d'un titre existant (vérifie le formatage localisé fr-fr ex: 4,5)."""
    monkeypatch.setattr(
        api_client,
        "get_title",
        lambda title_id: {
            "title": {
                "title_id": title_id,
                "title": "Super Film",
                "kind": "movie",
                "release_year": 2022,
                "genres": ["Drama"],
            },
            "views": 150,
            "average_rating": 4.5,
            "rating_count": 10,
        },
    )

    response = client.get("/titles/123e4567-e89b-12d3-a456-426614174000/")
    assert response.status_code == 200
    assert b"Super Film" in response.content
    # En fr-fr, 4.5 est formaté par défaut en '4,5' par le moteur de gabarit Django
    assert b"4,5" in response.content


def test_title_detail_not_found(monkeypatch, client):
    """Teste qu'un titre inconnu renvoie une erreur 404."""
    monkeypatch.setattr(api_client, "get_title", lambda title_id: None)

    response = client.get("/titles/00000000-0000-0000-0000-000000000000/")
    assert response.status_code == 404


def test_post_rating_success(monkeypatch, client):
    """Teste l'envoi réussi d'une note valide (POST 201) et la présence du message de succès."""
    monkeypatch.setattr(
        api_client,
        "get_title",
        lambda title_id: {
            "title": {"title_id": title_id, "title": "Super Film", "genres": []},
            "views": 10,
            "average_rating": 5.0,
            "rating_count": 1,
        },
    )
    monkeypatch.setattr(
        api_client,
        "post_rating",
        lambda user_id, title_id, rating, comment: 201,
    )

    response = client.post(
        "/titles/123e4567-e89b-12d3-a456-426614174000/",
        {
            "user_id": "8b9e6a20-0000-0000-0000-000000000000",
            "rating": "5",
            "comment": "Génial",
        },
    )
    assert response.status_code == 200
    assert "Avis enregistré" in response.content.decode("utf-8")


def test_post_rating_unprocessable(monkeypatch, client):
    """Teste l'envoi d'une note refusée (422)."""
    monkeypatch.setattr(
        api_client,
        "get_title",
        lambda title_id: {
            "title": {"title_id": title_id, "title": "Super Film", "genres": []},
            "views": 10,
        },
    )
    monkeypatch.setattr(
        api_client,
        "post_rating",
        lambda user_id, title_id, rating, comment: 422,
    )

    response = client.post(
        "/titles/123e4567-e89b-12d3-a456-426614174000/",
        {
            "user_id": "8b9e6a20-0000-0000-0000-000000000000",
            "rating": "6",
        },
    )
    assert response.status_code == 200
    assert b"Note invalide" in response.content


def test_api_unavailable(monkeypatch, client):
    """Teste que l'indisponibilité de l'API renvoie un code 503."""
    def mock_health():
        raise httpx.ConnectError("Connexion refusée")

    monkeypatch.setattr(api_client, "health", mock_health)

    response = client.get("/")
    assert response.status_code == 503
    assert b"503" in response.content


def test_user_history(monkeypatch, client):
    """Teste l'affichage de l'historique utilisateur."""
    monkeypatch.setattr(
        api_client,
        "history",
        lambda user_id: [
            {
                "watched_at": "2026-03-30 12:00:00",
                "title_id": "123e4567-e89b-12d3-a456-426614174000",
                "title": "Film Vu",
                "duration_watched_seconds": 3600,
                "completed": True,
            }
        ],
    )

    response = client.get("/users/8b9e6a20-0000-0000-0000-000000000000/history/")
    assert response.status_code == 200
    assert b"Film Vu" in response.content
    assert b"3600" in response.content

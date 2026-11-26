"""Vues de l'interface web Django pour la plateforme de streaming."""

from __future__ import annotations

import datetime
import httpx
from django.http import Http404, HttpResponse
from django.shortcuts import render, redirect

from frontend import api_client


def _handle_api_error(func):
    """Décorateur pour intercepter les erreurs réseau de l'API et afficher la page 503."""
    def wrapper(request, *args, **kwargs):
        try:
            return func(request, *args, **kwargs)
        except (httpx.HTTPError, ValueError):
            return render(request, "frontend/error.html", {
                "message": "Impossible de contacter l'API de streaming. Service temporairement indisponible."
            }, status=503)
    return wrapper


@_handle_api_error
def home(request):
    """Page d'accueil : état du cluster et top 10 du jour."""
    day = request.GET.get("day")
    if not day:
        day = datetime.date.today().isoformat()

    cluster_health = api_client.health()
    try:
        trending_list = api_client.trending(day)
    except httpx.HTTPStatusError:
        trending_list = []

    return render(request, "frontend/home.html", {
        "cluster": cluster_health,
        "trending": trending_list,
        "current_day": day,
    })


@_handle_api_error
def genre_detail(request, genre):
    """Liste des titres d'un genre."""
    titles = api_client.genre_titles(genre)
    return render(request, "frontend/genre.html", {
        "genre": genre,
        "titles": titles,
    })


@_handle_api_error
def title_detail(request, title_id):
    """Fiche détaillée d'un titre et traitement du formulaire d'avis."""
    data = api_client.get_title(title_id)
    if data is None:
        raise Http404("Titre inconnu")

    success_msg = None
    error_msg = None
    form_data = {}

    if request.method == "POST":
        user_id = request.POST.get("user_id", "").strip()
        rating_str = request.POST.get("rating", "").strip()
        comment = request.POST.get("comment", "").strip()

        form_data = {"user_id": user_id, "rating": rating_str, "comment": comment}

        if not user_id or not rating_str:
            error_msg = "Veuillez renseigner l'identifiant utilisateur et la note."
        else:
            try:
                rating = int(rating_str)
                status_code = api_client.post_rating(user_id, title_id, rating, comment if comment else None)
                if status_code == 201:
                    success_msg = "Avis enregistré avec succès."
                    # Recharger les détails pour refléter la nouvelle note moyenne
                    data = api_client.get_title(title_id)
                    form_data = {}
                elif status_code == 404:
                    error_msg = "Utilisateur ou titre inconnu."
                elif status_code == 422:
                    error_msg = "Note invalide (doit être comprise entre 1 et 5)."
                else:
                    error_msg = f"Erreur inattendue lors de l'enregistrement (code {status_code})."
            except ValueError:
                error_msg = "La note doit être un nombre entier."

    return render(request, "frontend/title.html", {
        "title_data": data,
        "success_msg": success_msg,
        "error_msg": error_msg,
        "form_data": form_data,
    })


@_handle_api_error
def user_history(request, user_id):
    """Historique de visionnage d'un utilisateur."""
    hist = api_client.history(user_id)
    return render(request, "frontend/history.html", {
        "user_id": user_id,
        "history": hist,
    })

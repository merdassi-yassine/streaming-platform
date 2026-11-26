"""Configuration des URL pour l'interface web frontend."""

from __future__ import annotations

from django.urls import path
from frontend import views

urlpatterns = [
    path("", views.home, name="home"),
    path("genres/<str:genre>/", views.genre_detail, name="genre_detail"),
    path("titles/<str:title_id>/", views.title_detail, name="title_detail"),
    path("users/<str:user_id>/history/", views.user_history, name="user_history"),
]

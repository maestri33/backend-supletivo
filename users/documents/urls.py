"""Rotas DMZ do `documents`. Montadas em /users/documents/ pelo core/urls.py.

`photo/<slot>/` antes do catch-all `<external_id>/` não é necessário (prefixos distintos), mas
a rota de foto é mais específica e vem primeiro por clareza.
"""

from django.urls import path

from users.documents import views

urlpatterns = [
    path("<str:external_id>/photo/<str:slot>/", views.photo, name="documents_photo"),
    path("<str:external_id>/", views.detail, name="documents_detail"),
]

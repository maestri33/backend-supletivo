"""Rotas DMZ do auth. Montadas em /users/auth/ pelo core/urls.py. O JWKS vai na raiz (well-known)."""

from django.urls import path

from users.auth import views

urlpatterns = [
    path("register/", views.register, name="auth_register"),
    path("check/", views.check, name="auth_check"),
    path("recover/", views.recover, name="auth_recover"),
    path("login/", views.login, name="auth_login"),
]

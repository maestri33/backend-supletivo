"""Rotas do auth (register/check/recover/login). Montadas em /users/auth/ pelo core/urls.py.
O JWKS foi removido no swap p/ django-ninja-jwt (sem consumidor externo de JWKS)."""

from django.urls import path

from users.auth import views

urlpatterns = [
    path("register/", views.register, name="auth_register"),
    path("check/", views.check, name="auth_check"),
    path("recover/", views.recover, name="auth_recover"),
    path("login/", views.login, name="auth_login"),
]

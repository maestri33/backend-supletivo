"""Rotas DMZ do `address`. Montadas em /users/address/ pelo core/urls.py.

Ordem importa: `list/` e `id/<int>/` antes do catch-all `<external_id>/` (senão o str-converter
engoliria "list"/"id").
"""

from django.urls import path

from users.address import views

urlpatterns = [
    path("list/", views.listing, name="address_list"),
    path("id/<int:address_id>/", views.by_id, name="address_by_id"),
    path("<str:external_id>/cep/", views.set_cep, name="address_set_cep"),
    path("<str:external_id>/", views.detail, name="address_detail"),
]

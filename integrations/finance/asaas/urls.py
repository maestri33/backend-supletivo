from django.urls import path

from . import views

app_name = "asaas"

urlpatterns = [
    path("status/", views.status, name="status"),
]

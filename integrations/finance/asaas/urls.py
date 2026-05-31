from django.urls import path

from . import views

app_name = "asaas"

urlpatterns = [
    # DMZ (rede interna) — onboarding/health da integração
    path("status/", views.status, name="status"),
    # público — o que o Asaas chama de volta (auth = asaas-access-token)
    path("webhook/", views.webhook, name="webhook"),
    path("transfer-validation/", views.transfer_validation, name="transfer-validation"),
]

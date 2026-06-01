from django.urls import path

from . import views

app_name = "asaas"

urlpatterns = [
    # DMZ (rede interna) — onboarding/health da integração
    path("status/", views.status, name="status"),
    # público — o que o Asaas chama de volta (auth = asaas-access-token)
    path("webhook/", views.webhook, name="webhook"),
    path("transfer-validation/", views.transfer_validation, name="transfer-validation"),
    # cobrança PIX (DMZ) — consumida depois por fees/enrollment
    path("charge/", views.charge, name="charge"),
    path("charge/<str:payment_id>/", views.charge_detail, name="charge-detail"),
    path("charge/<str:payment_id>/cancel/", views.charge_cancel, name="charge-cancel"),
    path("charge/<str:payment_id>/refund/", views.charge_refund, name="charge-refund"),
]

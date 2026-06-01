from django.urls import path

from . import views

app_name = "asaas"

urlpatterns = [
    # DMZ (rede interna) — onboarding/health da integração
    path("status/", views.status, name="status"),  # read-only
    path("setup/", views.setup, name="setup"),  # roda a bateria + auto-cadastra o webhook
    # público — o que o Asaas chama de volta (auth = asaas-access-token)
    path("webhook/", views.webhook, name="webhook"),
    path("transfer-validation/", views.transfer_validation, name="transfer-validation"),
    # público — echo do ping de verificação da URL (auth = nonce single-use)
    path("url-verify/<str:nonce>/", views.url_verify_echo, name="url-verify"),
    # cobrança PIX (DMZ) — consumida depois por fees/enrollment
    path("charge/", views.charge, name="charge"),
    path("charge/<str:payment_id>/", views.charge_detail, name="charge-detail"),
    path("charge/<str:payment_id>/cancel/", views.charge_cancel, name="charge-cancel"),
    path("charge/<str:payment_id>/refund/", views.charge_refund, name="charge-refund"),
    # payout PIX (saída, DMZ) — 1a-vi
    path("payout/", views.payout, name="payout"),
    path("payout/<str:payment_id>/", views.payout_detail, name="payout-detail"),
]

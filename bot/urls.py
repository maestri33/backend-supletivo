from django.urls import path

from . import views

app_name = "bot"

# Endpoint PÚBLICO chamado de fora pela Evolution (igual aos webhooks dos gateways). Auth = header
# x-webhook-token == WHATSAPP_WEBHOOK_SECRET (fail-closed). Registrado em core/urls.py como sibling
# de integrations/asaas e integrations/infinitepay.
urlpatterns = [
    path("webhook/", views.webhook, name="webhook"),
]

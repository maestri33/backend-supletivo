from django.urls import path

from . import views

app_name = "infinitepay"

urlpatterns = [
    # DMZ (rede interna) — onboarding/health da integração
    path("status/", views.status, name="status"),
    # DMZ — link de pagamento (consumido depois por lead/enrollment)
    path("checkout/", views.checkout, name="checkout"),
    path("checkout/<uuid:external_id>/", views.checkout_detail, name="checkout-detail"),
    # público — o que a InfinitePay chama de volta (sem auth; trava = order_nsu opaco + payment_check)
    path("webhook/", views.webhook, name="webhook"),
]

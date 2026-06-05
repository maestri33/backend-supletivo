"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

# API pública (Django Ninja, in-process) — 4 grupos por público, versionados sob /api/v1/.
# Nomes = PLACEHOLDER (CONVENTION §1; Victor decide depois). Ver plan/api-ninja-transicao.
from api.clients import api as clients_api
from api.collaborators import api as collaborators_api
from api.leadership import api as leadership_api
from api.staff import api as staff_api
from users.roles.lead.checkout_links import checkout_redirect

urlpatterns = [
    path("admin/", admin.site.urls),
    # link curto do checkout: /lead/checkout/<token> → 302 pro checkout do gateway (manda por WhatsApp).
    path("lead/checkout/<str:token>", checkout_redirect),
    # views DMZ das integrações (internas — <servico>.prod)
    path("integrations/asaas/", include("integrations.finance.asaas.urls")),
    path("integrations/infinitepay/", include("integrations.finance.infinitepay.urls")),
    # users — auth (register/check/recover/login). JWKS removido no swap p/ django-ninja-jwt (sem consumidor externo).
    path("users/auth/", include("users.auth.urls")),
    path("users/address/", include("users.address.urls")),
    path("users/documents/", include("users.documents.urls")),
    # API Ninja versionada — /api/v1/<grupo>/ (cada grupo serve /docs e /openapi.json).
    path("api/v1/clients/", clients_api.urls),
    path("api/v1/collaborators/", collaborators_api.urls),
    path("api/v1/leadership/", leadership_api.urls),
    path("api/v1/staff/", staff_api.urls),
]

# Em dev (DEBUG) o Django serve /media/ (ex.: PNG do QR das cobranças); em prod é a infra/proxy.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

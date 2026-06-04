"""Grupo `staff` — administração da plataforma (o "boss": cadastra hub, define coordenador).

Todas as rotas exigem SUPERUSER (staff = superuser nativo do Django — Victor 2026-06-03), via
`require_superuser`. Casca fina (CONVENTION §3): valida a borda e chama o `interface/` do `hub` e do
`users/roles`. Zero regra de negócio aqui.
"""

from __future__ import annotations

from ninja import Schema
from ninja.errors import HttpError

from api.auth import require_superuser
from api.base import build_group
from hub import interface as hub_iface
from users.profiles import interface as profiles
from users.roles import interface as roles

api = build_group(
    "staff", "Administração da plataforma: hub, coordenador, saúde dos serviços."
)


# ── schemas ──────────────────────────────────────────────────────────────
class HubCreateIn(Schema):
    brand: str
    coordinator_external_id: str | None = None


class SetCoordinatorIn(Schema):
    coordinator_external_id: str


class HubOut(Schema):
    external_id: str
    brand: str
    coordinator_external_id: str | None
    is_default: bool


class PromoterOut(Schema):
    external_id: str
    name: str | None


def _hub_out(hub) -> dict:
    return {
        "external_id": str(hub.external_id),
        "brand": hub.brand,
        "coordinator_external_id": (
            str(hub.coordinator.external_id) if hub.coordinator else None
        ),
        "is_default": hub.is_default,
    }


# ── rotas (todas exigem superuser) ─────────────────────────────────────────
@api.post("/hubs", response=HubOut, tags=["staff"])
def create_hub(request, payload: HubCreateIn):
    """Cria um polo: marca (do catálogo) + coordenador opcional (um promotor)."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.create_hub(
            brand=payload.brand,
            coordinator_external_id=payload.coordinator_external_id,
        )
    except hub_iface.HubError as exc:
        raise HttpError(422, str(exc)) from exc
    return _hub_out(hub)


@api.get("/hubs", response=list[HubOut], tags=["staff"])
def list_hubs(request):
    """Lista todos os polos."""
    require_superuser(request.auth)
    return [_hub_out(h) for h in hub_iface.list_hubs()]


@api.get("/promoters", response=list[PromoterOut], tags=["staff"])
def list_promoters(request):
    """Lista os promotores (pra escolher quem será coordenador de um polo)."""
    require_superuser(request.auth)
    out = []
    for user in roles.users_with_role("promoter"):
        profile = profiles.get(user)
        out.append(
            {
                "external_id": str(user.external_id),
                "name": profile.name if profile else None,
            }
        )
    return out


@api.put("/hubs/{external_id}/coordinator", response=HubOut, tags=["staff"])
def set_coordinator(request, external_id: str, payload: SetCoordinatorIn):
    """Designa/troca o coordenador de um polo (um promotor)."""
    require_superuser(request.auth)
    try:
        hub = hub_iface.set_coordinator(
            hub_external_id=external_id,
            coordinator_external_id=payload.coordinator_external_id,
        )
    except hub_iface.HubError as exc:
        status = 404 if exc.args and exc.args[0] == "hub_not_found" else 422
        raise HttpError(status, str(exc)) from exc
    return _hub_out(hub)

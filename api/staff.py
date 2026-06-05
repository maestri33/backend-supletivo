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
from users.roles.lead import interface as lead_iface
from users.roles.training import interface as training_iface

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


# ── autoria de matéria do treino (staff — também o coordenador, no grupo leadership) ──
class MaterialIn(Schema):
    title: str
    text_content: str
    question: str
    expected_answer: str
    order: int = 0


class MaterialUpdateIn(Schema):
    title: str | None = None
    text_content: str | None = None
    question: str | None = None
    expected_answer: str | None = None
    order: int | None = None
    active: bool | None = None


@api.post("/training/materials", tags=["staff"])
def create_material(request, payload: MaterialIn):
    """Cria uma matéria do treino (texto+questão+gabarito)."""
    require_superuser(request.auth)
    m = training_iface.create_material(**payload.dict())
    return training_iface.material_to_dict(m, include_answer=True)


@api.put("/training/materials/{external_id}", tags=["staff"])
def update_material(request, external_id: str, payload: MaterialUpdateIn):
    """Edita uma matéria (campos enviados; `active=False` desativa)."""
    require_superuser(request.auth)
    try:
        m = training_iface.update_material(external_id, **payload.dict())
    except training_iface.TrainingError as exc:
        raise HttpError(404, str(exc)) from exc
    return training_iface.material_to_dict(m, include_answer=True)


@api.get("/training/materials", tags=["staff"])
def list_materials(request):
    """Lista todas as matérias (com gabarito — visão de autoria)."""
    require_superuser(request.auth)
    return [
        training_iface.material_to_dict(m, include_answer=True)
        for m in training_iface.list_materials(active_only=False)
    ]


# ── leads (staff vê TODOS; filtra por polo) ──────────────────────────────────
@api.get("/leads", tags=["lead"])
def list_all_leads(request, hub: str | None = None, status: str | None = None):
    """Lista TODOS os leads (link de pagamento + comprovante). Filtros: `hub` (external_id) e `status`."""
    require_superuser(request.auth)
    hub_obj = None
    if hub:
        # hub passado mas inexistente → 404 (não cair silenciosamente em "todos os leads")
        hub_obj = hub_iface.get_by_external_id(hub)
        if hub_obj is None:
            raise HttpError(404, "hub_not_found")
    leads = lead_iface.list_leads(hub=hub_obj, status=status)
    return [lead_iface.lead_to_dict(lead) for lead in leads]

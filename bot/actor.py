"""O bot agindo COMO O USUÁRIO (FASE 2). Identidade pelo número verificado, capacidade por JWT.

DESENHO (dono confirmou):
- A identidade é o NÚMERO do WhatsApp (mesma âncora do OTP: controle do número). O worker já
  resolveu phone→Profile→User; aqui NÃO há OTP — o número que mandou a msg é a prova.
- O bot age COMO O USUÁRIO via a MESMA superfície que a API usa: o backend emite INTERNAMENTE um
  JWT curto daquele usuário (reusa `jwt_service.issue`, a MESMA função que o `login` chama), e a
  ação passa pelo MESMO gate de role que as rotas Ninja rodam (`decode` → `version_matches` →
  `Principal` → `require_roles`) antes de tocar a interface canônica daquela etapa.

GARANTIA: o bot é estruturalmente limitado ao que o usuário poderia fazer pela API. NUNCA ORM cru,
NUNCA privilégio extra. O token é emitido, validado e USADO no mesmo processo, na mesma chamada, e
descartado — nunca é persistido nem trafega pra fora (single-use in-process = curto na prática,
independente da expiração nominal do `NINJA_JWT`).

Cada método de ESCRITA roda `require_roles` com o MESMO gate da rota equivalente (defesa em
profundidade — o motor só chega aqui no público certo, mas o gate é a prova). As escritas expostas
são SÓ as canônicas e idempotentes de cada etapa (endereço por CEP, tipo sanguíneo). Leitura de
status/checkout é do PRÓPRIO usuário.
"""

from __future__ import annotations

import structlog

from api.auth import Principal, require_roles
from users.auth.jwt import service as jwt_service

logger = structlog.get_logger()

# Gates espelhando as rotas Ninja (api/clients.py):
_FUNNEL_ROLES = (
    "veteran",
    "student",
    "enrollment",
    "lead",
)  # gate do grupo lead/checkout


class Actor:
    """Um usuário autenticado COMO PELA API. Construído a partir do `User` resolvido pelo telefone.

    `for_user` emite o JWT (igual ao login) e o VALIDA pelo mesmo caminho do `JWTAuth.authenticate`
    — se a validação não bater (ex.: token_version mudou no meio), devolve None (fail-closed). Os
    métodos de escrita rodam `require_roles` com o gate da rota equivalente e chamam a interface.
    """

    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        self.external_id = principal.external_id

    @classmethod
    def for_user(cls, user) -> "Actor | None":
        """Emite JWT curto do usuário (reuse `jwt_service.issue`, igual ao login) e valida-o pelo
        MESMO gate da API. None se a validação falhar (fail-closed)."""
        from users.roles import interface as roles_iface

        external_id = str(user.external_id)
        active = roles_iface.active_roles(user)
        try:
            tokens = jwt_service.issue(external_id, active)
            payload = jwt_service.decode(
                tokens["access_token"]
            )  # mesmo caminho do JWTAuth
        except jwt_service.TokenError as exc:
            logger.warning(
                "bot.actor.token_invalid", external_id=external_id, error=str(exc)[:120]
            )
            return None
        if not jwt_service.version_matches(external_id, payload.get("token_version")):
            logger.warning("bot.actor.version_stale", external_id=external_id)
            return None
        principal = Principal(payload.get("external_id", ""), payload.get("roles", []))
        return cls(principal)

    # ── LEITURAS do próprio usuário (sem dado sensível na borda do bot) ──────
    def lead(self):
        """O lead do próprio usuário (ou None). Gate = grupo lead (mesma rota /lead/me)."""
        from users.roles.lead import interface as lead_iface

        require_roles(self.principal, *_FUNNEL_ROLES)
        return lead_iface.get_for_user_external_id(self.external_id)

    def checkout_url(self) -> str | None:
        """A URL ÚNICA (link curto) do checkout do próprio lead — REENVIO, nunca nova cobrança.

        Espelha `GET /lead/checkout-url`: `checkout_url_for` resolve checkout↔recibo. NÃO gera
        cobrança, NÃO chama provider — só devolve o link curto JÁ existente (ou None)."""
        from users.roles.lead import interface as lead_iface

        require_roles(self.principal, *_FUNNEL_ROLES)
        lead = lead_iface.get_for_user_external_id(self.external_id)
        return lead_iface.checkout_url_for(lead) if lead is not None else None

    def enrollment_status(self) -> str | None:
        """Status CRU da matrícula do próprio usuário (pro motor decidir a etapa). None se não há."""
        from users.roles.enrollment import interface as enr_iface

        require_roles(self.principal, "enrollment", "student", "veteran")
        enr = enr_iface.get_for_user_external_id(self.external_id)
        return getattr(enr, "status", None) if enr is not None else None

    def student_status(self) -> str | None:
        """Status CRU do aluno do próprio usuário (pro motor decidir a etapa). None se não há."""
        from users.roles.student import interface as student_iface

        require_roles(self.principal, "student", "veteran")
        student = student_iface.get_for_user_external_id(self.external_id)
        return getattr(student, "status", None) if student is not None else None

    # ── ESCRITAS canônicas e idempotentes (gate = rota equivalente) ─────────
    def set_address_cep(self, cep: str) -> dict:
        """POST /enrollment/address (body {cep}). Idempotente: re-validar o MESMO CEP dá o MESMO
        estado. Devolve o EnrollmentMe canônico (tem `address.missing_fields`). Gate: enrollment."""
        from users.roles.enrollment import interface as enr_iface

        require_roles(self.principal, "enrollment")
        return enr_iface.set_address_cep(user_external_id=self.external_id, cep=cep)

    def set_blood_type(self, blood_type: str):
        """POST /student/blood-type. Idempotente: setar o MESMO tipo dá o MESMO estado. Gate: student."""
        from users.roles.student import interface as student_iface

        require_roles(self.principal, "student")
        return student_iface.set_blood_type(
            user_external_id=self.external_id, blood_type=blood_type
        )

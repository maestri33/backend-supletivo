"""Enrollment — a 2ª role do funil do ALUNO (matrícula): nasce quando o LEAD PAGA.

Gatilho: o webhook do pagamento dispara o `hook` do lead (CONVENTION §7), que cria o Enrollment
**já ligado ao HUB herdado do promotor** (palavra do Victor 2026-06-04: ao virar matrícula, a
responsabilidade passa do promotor pro hub). Depois vem o funil de coleta (perfil→endereço→RG→dados
escolares→selfie até `awaiting_release`) e a liberação do coordenador (`awaiting_release`→student).

Sub-pacote de `users` (app_label `users`, 1 migration set — igual lead/address/documents; CONVENTION §2).
FK real (§4): `user` 1-1, `promoter` e `hub` por FK de verdade.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import ExternalIdModel
from users.roles._selfie import SelfieStatus


class Enrollment(ExternalIdModel):
    """A matrícula de um aluno (1-1 com o User). Carrega o hub herdado do promotor que indicou."""

    class Status(models.TextChoices):
        # status = a seção que o aluno preenche AGORA (vocabulário do wizard do front).
        # Ordem nova (plan/13, Victor 2026-06-11): DOCUMENTO primeiro — a extração povoa o
        # perfil (a etapa `started`/perfil morreu). Concluir uma seção avança pro NOME da próxima.
        RG = "rg", "RG (fotos + dados)"
        ADDRESS = "address", "endereço"
        EDUCATION = "education", "dados escolares"
        SELFIE = "selfie", "selfie (assinatura da matrícula)"
        AWAITING_RELEASE = "awaiting_release", "aguardando liberação"
        # fase da TAXA (plan/14, Victor 2026-06-12) — INTERNA do polo: o aluno NUNCA vê estas duas
        # (na visão dele aparecem como `awaiting_release` — política interna; máscara no service).
        FEE_PAID = "fee_paid", "1ª parcela da taxa paga"
        FEE_SCHEDULED = "fee_scheduled", "2ª parcela da taxa agendada"
        COMPLETED = "completed", "concluída"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollment",
    )
    # o promotor que captou o lead (snapshot — a obrigação dele acaba aqui; ganha a comissão no pagamento).
    promoter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="enrollments_promoted",
    )
    # HUB herdado do promotor: a partir da matrícula, é o hub (coordenador) que cuida do aluno.
    hub = models.ForeignKey(
        "hub.Hub",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RG,
        db_index=True,
    )
    # dados da plataforma externa que o COORDENADOR posta na liberação (6c). Schema livre por ora
    # (legado guardava sem schema fixo); modelar campos exatos com o Victor no ciclo `student`.
    study_platform = models.JSONField(null=True, blank=True)
    # dados pessoais extras da matrícula (etapa `profile`, 6b) — porte do legado (referência do Victor).
    # «PENDÊNCIA»: confirmar o conjunto exato + se migram pro Profile (reuso) ou ficam aqui (Victor).
    mother_name = models.CharField(max_length=255, null=True, blank=True)
    father_name = models.CharField(max_length=255, null=True, blank=True)
    marital_status = models.CharField(max_length=32, null=True, blank=True)
    birthplace = models.CharField(max_length=128, null=True, blank=True)
    nationality = models.CharField(max_length=64, null=True, blank=True)
    # selfie/ASSINATURA (etapa `selfie`, 6b) — foto em media/enrollment/<ext>/ + validação IA
    # 3 estados + revisão. `taken_at` = quando o aluno enviou (GET /selfie, plan/13).
    selfie_image = models.CharField(max_length=255, null=True, blank=True)
    selfie_taken_at = models.DateTimeField("selfie enviada em", null=True, blank=True)
    selfie_verified = models.BooleanField(
        default=False
    )  # = selfie_status aprovado (compat)
    selfie_status = models.CharField(
        max_length=20,
        choices=SelfieStatus.choices,
        default=SelfieStatus.PENDING,
        db_index=True,
    )
    selfie_description = models.TextField(
        null=True, blank=True
    )  # justificativa da IA/coordenador
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_enrollment"
        verbose_name = "matrícula"
        verbose_name_plural = "matrículas"

    def __str__(self) -> str:
        return f"enrollment<{self.external_id}:{self.status}>"


class EducationalData(models.Model):
    """Dados escolares coletados na matrícula (etapa `education`, 6b). 1-1 com o Enrollment."""

    enrollment = models.OneToOneField(
        Enrollment,
        on_delete=models.CASCADE,
        related_name="educational_data",
    )
    last_year_studied = models.CharField("último ano/série cursado", max_length=64)
    last_year_when = models.CharField("quando", max_length=64, null=True, blank=True)
    last_school = models.CharField("qual escola", max_length=255)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_enrollment_education"
        verbose_name = "dados escolares"
        verbose_name_plural = "dados escolares"

    def __str__(self) -> str:
        return f"education<{self.enrollment_id}>"

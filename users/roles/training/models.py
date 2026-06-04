"""Training — o LMS do funil do colaborador (candidato em treino → promotor).

3 models: `Material` (matéria: texto+questão+gabarito, +vídeo/foto; autoria staff+coordenador) · `Submission`
(resposta do aluno → IA corrige: nota 0-10 + justificativa; `pending→approved|rejected`; reenvio sem limite) ·
`Trainee` (estado global: `training→awaiting_interview→approved|rejected`). Todas as matérias aprovadas →
aguarda entrevista → coordenador aprova → promove a **promotor**. Sub-pacote de `users` (app_label `users`).
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Material(models.Model):
    """Uma matéria do treino: 1 texto + 1 questão + 1 gabarito (+ vídeo/foto opcionais)."""

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=255)
    text_content = models.TextField()
    question = models.TextField()
    expected_answer = models.TextField()  # gabarito (a IA compara a resposta com isto)
    video = models.CharField(max_length=255, null=True, blank=True)  # media/training/
    photo = models.CharField(max_length=255, null=True, blank=True)
    order = models.PositiveIntegerField(default=0, db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_training_material"
        verbose_name = "matéria do treino"
        verbose_name_plural = "matérias do treino"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"material<{self.external_id}:{self.title}>"


class Trainee(models.Model):
    """Estado global do candidato no treino (1-1 com o User). Criado na transição candidate→training."""

    class Status(models.TextChoices):
        TRAINING = "training", "em treino"
        AWAITING_INTERVIEW = "awaiting_interview", "aguardando entrevista"
        APPROVED = "approved", "aprovado"
        REJECTED = "rejected", "rejeitado"

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trainee",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TRAINING,
        db_index=True,
    )
    coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trainees_decided",
    )
    awaiting_interview_at = models.DateTimeField(null=True, blank=True)
    decision_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_trainee"
        verbose_name = "trainee"
        verbose_name_plural = "trainees"

    def __str__(self) -> str:
        return f"trainee<{self.external_id}:{self.status}>"


class Submission(models.Model):
    """Uma resposta a uma matéria, corrigida pela IA (nota 0-10 + justificativa)."""

    class Status(models.TextChoices):
        PENDING = "pending", "corrigindo"
        APPROVED = "approved", "aprovada"
        REJECTED = "rejected", "reprovada"

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        related_name="submissions",
    )
    answer = models.TextField()
    grade = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )  # 0-10
    justification = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_training_submission"
        verbose_name = "submissão do treino"
        verbose_name_plural = "submissões do treino"

    def __str__(self) -> str:
        return f"submission<{self.external_id}:{self.status}>"

"""Documents — agregado de documentos do usuário (spec documents; VISAO §serviços-de-apoio).

`Document` é a raiz, 1-1 com o `User`, criada no provisionamento do `auth`. Os sub-documentos
(`RG`, `CNH`, `Certificate`, `Military`) são 1-1 com o `Document` (carregam `document_id`, §4) e
nascem TODOS junto, com campos null — vão sendo preenchidos depois. Foto = path relativo no DB
(arquivo físico em `media/documents/<external_id>/<slot>.<ext>`).

Só RG/CNH/certidão/serviço-militar (palavra do dono) — WorkCard/Passport do legado ficam de fora.
Vive sob o app_label `users` (sub-pacote, igual auth/profiles/roles).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Document(models.Model):
    """Raiz dos documentos, 1-1 com o User. Criada (com sub-docs null) no provisionamento."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_document"
        verbose_name = "documento"
        verbose_name_plural = "documentos"

    def __str__(self) -> str:
        return f"document<{self.pk}>"


class RG(models.Model):
    """Carteira de identidade (RG). Todos os campos null (preenchidos depois)."""

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="rg"
    )
    number = models.CharField("número", max_length=30, null=True, blank=True)
    issuing_agency = models.CharField(
        "órgão emissor", max_length=50, null=True, blank=True
    )
    issue_date = models.DateField("data de emissão", null=True, blank=True)
    front_photo = models.CharField("foto frente", max_length=500, null=True, blank=True)
    back_photo = models.CharField("foto verso", max_length=500, null=True, blank=True)

    class Meta:
        app_label = "users"
        db_table = "users_document_rg"
        verbose_name = "RG"
        verbose_name_plural = "RGs"


class CNH(models.Model):
    """Carteira de habilitação (CNH) — porte do conjunto do legado (palavra do dono)."""

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="cnh"
    )
    number = models.CharField("número", max_length=30, null=True, blank=True)
    category = models.CharField("categoria", max_length=5, null=True, blank=True)
    date_of_birth = models.DateField("data de nascimento", null=True, blank=True)
    expires_on = models.DateField("validade", null=True, blank=True)
    national_register = models.CharField(
        "registro nacional", max_length=30, null=True, blank=True
    )
    front_photo = models.CharField("foto frente", max_length=500, null=True, blank=True)
    back_photo = models.CharField("foto verso", max_length=500, null=True, blank=True)

    class Meta:
        app_label = "users"
        db_table = "users_document_cnh"
        verbose_name = "CNH"
        verbose_name_plural = "CNHs"


class Certificate(models.Model):
    """Certidão — nascimento/casamento/óbito; só UMA por document (1-1). Campos null."""

    KIND_CHOICES = (
        ("nascimento", "nascimento"),
        ("casamento", "casamento"),
        ("obito", "óbito"),
    )

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="certificate"
    )
    kind = models.CharField(
        "tipo", max_length=20, choices=KIND_CHOICES, null=True, blank=True
    )
    number = models.CharField("número", max_length=50, null=True, blank=True)
    registry_office = models.CharField(
        "cartório", max_length=100, null=True, blank=True
    )
    book = models.CharField("livro", max_length=20, null=True, blank=True)
    page = models.CharField("folha", max_length=20, null=True, blank=True)
    entry = models.CharField("termo", max_length=20, null=True, blank=True)
    issue_date = models.DateField("data de emissão", null=True, blank=True)
    photo = models.CharField("foto", max_length=500, null=True, blank=True)

    class Meta:
        app_label = "users"
        db_table = "users_document_certificate"
        verbose_name = "certidão"
        verbose_name_plural = "certidões"


class Military(models.Model):
    """Documento de serviço militar (reservista). Criado pra todos; só `gender='M'` preenche (Q4)."""

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="military"
    )
    number = models.CharField("número", max_length=30, null=True, blank=True)
    series = models.CharField("série", max_length=20, null=True, blank=True)
    category = models.CharField("categoria", max_length=20, null=True, blank=True)
    ra = models.CharField("RA", max_length=20, null=True, blank=True)
    photo = models.CharField("foto", max_length=500, null=True, blank=True)

    class Meta:
        app_label = "users"
        db_table = "users_document_military"
        verbose_name = "documento militar"
        verbose_name_plural = "documentos militares"

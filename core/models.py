"""Models base comuns do core (CONVENTION §2)."""

import uuid

from django.db import models


class ExternalIdModel(models.Model):
    """Base abstrata com o ÚNICO external_id de borda do projeto (CONVENTION §4).

    Todo model exposto na API herda daqui em vez de redeclarar o campo. `external_id` (UUID, imutável) é
    o id opaco da borda — nunca a PK. As relações INTERNAS continuam por FK de verdade; este campo só
    aparece na fronteira da API. Como é abstrato, cada filho ganha sua própria coluna idêntica — então
    quem já declarava o campo igual NÃO muda de schema.
    """

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        abstract = True


class UnroutedEvent(models.Model):
    """Evento que chegou validado mas não tinha consumidor real ainda.

    Fallback rastreável (pedido do Victor): quando um webhook/evento é destinado a um serviço que
    ainda não existe (fees/commissions etc.), gravamos aqui + logamos, em vez de descartar em
    silêncio. Permite auditar e reprocessar depois que o app destino existir.
    """

    source = models.CharField(max_length=64, db_index=True)  # ex.: "asaas"
    event = models.CharField(max_length=255, db_index=True)
    reason = models.CharField(max_length=255)  # por que não roteou (ex.: no_matching_charge)
    payload = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return f"{self.source}:{self.event} @ {self.received_at:%Y-%m-%d %H:%M:%S}"


class ValidationCheck(models.Model):
    """Registro persistente de teste/validação que a gente fez, com flag + horário.

    Pedido do Victor: todo teste que rodarmos fica salvo, com a respectiva flag, pra **rastrear no
    futuro** se algo der errado. Append-only (cada execução grava uma linha = histórico); o `/status/`
    de cada integração mostra o ÚLTIMO resultado por `(scope, name)`. Ex.: `scope=asaas`,
    `name=webhook_external`, `passed=True`, `mode=artificial` (testado via link externo, ainda não por
    evento real do Asaas).
    """

    scope = models.CharField(max_length=64, db_index=True)  # ex.: asaas
    name = models.CharField(max_length=128, db_index=True)  # ex.: webhook_external
    passed = models.BooleanField()
    mode = models.CharField(max_length=32, blank=True)  # artificial | real | link | ...
    detail = models.TextField(blank=True)
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["scope", "name", "-checked_at"])]

    def __str__(self):
        flag = "OK" if self.passed else "FAIL"
        return f"{self.scope}:{self.name}={flag} @ {self.checked_at:%Y-%m-%d %H:%M}"

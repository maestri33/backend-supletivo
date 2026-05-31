"""Models base comuns do core (CONVENTION §2)."""

from django.db import models


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

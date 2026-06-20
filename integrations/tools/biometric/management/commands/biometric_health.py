"""Saúde da biometria: importa deps e CARREGA o modelo (baixa no 1º uso).

Uso: python manage.py biometric_health
Fecha parte do Portão 3 (§8 — integração validada de verdade, com o modelo carregado em CPU).
Grava o resultado no ledger `core.ValidationCheck` (scope=biometric).
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from core.validation import record_check


class Command(BaseCommand):
    help = "Verifica deps + carrega o modelo InsightFace (CPU); grava ValidationCheck."

    def handle(self, *args, **options):
        from integrations.tools.biometric import face_match
        from integrations.tools.biometric.exceptions import BiometricError

        self.stdout.write(
            f"modelo={settings.BIOMETRIC_MODEL_NAME} root={settings.BIOMETRIC_MODEL_ROOT} "
            f"enabled={settings.BIOMETRIC_ENABLED} "
            f"match≥{settings.BIOMETRIC_MATCH_THRESHOLD} review≥{settings.BIOMETRIC_REVIEW_THRESHOLD}"
        )
        try:
            face_match._get_app()  # carrega/baixa o modelo (CPU)
        except BiometricError as exc:
            self.stderr.write(self.style.ERROR(f"modelo NÃO carregou: {exc}"))
            record_check("biometric", "health", False, mode="real", detail=str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(
                self.style.ERROR(f"falha inesperada ao carregar: {exc!r}")
            )
            record_check("biometric", "health", False, mode="real", detail=repr(exc))
            return

        self.stdout.write(self.style.SUCCESS("modelo carregado (CPU) ✓"))
        record_check(
            "biometric", "health", True, mode="real", detail="modelo carregado (CPU)"
        )

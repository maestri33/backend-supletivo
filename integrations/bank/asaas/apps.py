import os
import sys
import threading
import time

from django.apps import AppConfig


class AsaasConfig(AppConfig):
    name = "integrations.bank.asaas"
    label = "asaas"

    def ready(self):
        # Registra os system checks de env no boot. Rodam em todo runserver/manage, então "ficam
        # printando" enquanto faltar env essencial (E001 = api-key trava; W001 = webhook-secret avisa).
        from django.core.checks import register

        from .checks import check_asaas_env, check_asaas_webhook_secret

        register(check_asaas_env)
        register(check_asaas_webhook_secret)

        # Bateria de testes + auto-cadastro do webhook em TODO boot (1a-v), NÃO-bloqueante.
        self._maybe_start_selftest()

    def _maybe_start_selftest(self):
        """Dispara a bateria (onboarding.setup) numa thread daemon — não trava o boot.

        Só quando o comando é "subir o servidor" (runserver/qcluster) — pula migrate/test/shell/etc.,
        que não devem falar com o Asaas. Sob o autoreload do runserver, ready() roda 2x (launcher +
        worker): dispara só no worker (RUN_MAIN == "true"). Com --noreload não há launcher nem
        RUN_MAIN, então o processo único é o worker -> dispara.
        """
        argv = sys.argv
        if not any(cmd in argv for cmd in ("runserver", "qcluster")):
            return
        reloader_launcher = (
            "runserver" in argv
            and "--noreload" not in argv
            and os.environ.get("RUN_MAIN") != "true"
        )
        if reloader_launcher:
            return
        threading.Thread(
            target=self._run_selftest, name="asaas-selftest", daemon=True
        ).start()

    def _run_selftest(self):
        """Espera o servidor subir e roda setup(): testa a key, pinga a URL e auto-cadastra o webhook.

        Falha de rede só loga + carimba o ledger — NUNCA derruba o processo.
        """
        import structlog

        from . import onboarding

        logger = structlog.get_logger()
        time.sleep(2)  # deixa o servidor escutar antes de pingar a própria EXTERNAL_URL
        try:
            report = onboarding.setup()
        except Exception as exc:  # boot nunca cai por causa do self-test
            logger.error("asaas_boot_selftest_failed", error=str(exc))
            return
        logger.info(
            "asaas_boot_selftest",
            api_key_tested_ok=report.get("api_key_tested_ok"),
            url_verified=report.get("url_verified"),
            webhook_action=report.get("webhook_action"),
            webhook_registered=bool(report.get("webhook_registered")),
            ready=report.get("ready"),
        )

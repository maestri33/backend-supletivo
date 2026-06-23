from django.apps import AppConfig


class TodoConfig(AppConfig):
    """App `todo` — casca de funcionalidades A DESENVOLVER (mocks que respondem "não
    implementado"). Hoje hospeda o `bot_matriculador` (mock) e conecta, no `ready()`, o
    receiver do signal `enrollment_ready_for_matricula` (padrão `ready()` igual hub/apps.py).
    Sem models (sem migration)."""

    name = "core.todo"
    label = "todo"

    def ready(self):
        from core.todo import receivers  # noqa: F401  (conecta o receiver do signal)

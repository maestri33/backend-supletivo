from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = "users"
    label = "users"
    verbose_name = "usuários"

    def ready(self):
        # Valida o catálogo de roles cedo (ImproperlyConfigured derruba o boot se ROLE_RULES quebrado)
        # e garante o par de chaves JWT (gera em keys/ se faltar). Registra os system checks.
        from django.core.checks import register

        from users.auth.jwt import keys
        from users.roles import catalog  # noqa: F401 — import valida ROLE_RULES no boot

        from .checks import check_users

        keys.ensure_keys()
        register(check_users)

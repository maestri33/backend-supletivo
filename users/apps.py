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

        # Hook de pagamento do lead (CONVENTION §7.3): o webhook do asaas/infinitepay dispara
        # 'payment.paid' → o lead casa o checkout e marca pago. Registra no boot (apps já carregados).
        from core import hooks as core_hooks
        from users.roles.lead.hooks import on_payment_paid

        core_hooks.register("payment.paid", on_payment_paid)

        # Hooks da TAXA da matrícula (plan/14): o worker do finance dispara 'fee.paid'/'fee.problem'
        # → a matrícula avança o status (1ª paga → fee_paid) e o COORDENADOR é notificado.
        from users.roles.enrollment.hooks import on_fee_paid, on_fee_problem

        core_hooks.register("fee.paid", on_fee_paid)
        core_hooks.register("fee.problem", on_fee_problem)

"""Validação de email — formato (regex), DNS MX e opcional handshake SMTP RCPT.

Porte do legado (notify/utils/email_validator), com a correção do método smtplib (`mail()`, não o
inexistente `mailfrom()`). Consumo in-process pelo futuro users/auth p/ a unicidade do §9 (email
válido + não-falso). smtp_check default off: muitos MX (Gmail) bloqueiam o probe RCPT → resultado
inconclusivo e lento; liga sob demanda.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
from dataclasses import dataclass, field

import dns.exception
import dns.resolver
import structlog

logger = structlog.get_logger()

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _mask_email(email: str) -> str:
    """Mascara o local-part p/ log sem PII: 'victor@gmail.com' → 'v***@gmail.com'."""
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    head = local[0] if local else ""
    return f"{head}***@{domain}"


@dataclass
class EmailValidation:
    email: str
    valid_format: bool = False
    domain: str | None = None
    has_mx: bool = False
    mx_hosts: list[str] = field(default_factory=list)
    smtp_checked: bool = False
    smtp_valid: bool = False
    smtp_detail: str = ""
    is_valid: bool = False


def _check_format(email: str) -> tuple[bool, str | None]:
    if not _EMAIL_RE.match(email):
        return False, None
    return True, email.rsplit("@", 1)[-1].lower()


def _check_mx(domain: str) -> tuple[bool, list[str]]:
    """Resolve MX do domínio → (tem_mx, [hosts ordenados por preferência])."""
    try:
        answers = dns.resolver.resolve(domain, "MX")
    except (
        dns.resolver.NoAnswer,
        dns.resolver.NXDOMAIN,
        dns.resolver.NoNameservers,
        dns.exception.Timeout,
    ) as exc:
        logger.info("mail.mx_not_found", domain=domain, error=str(exc))
        return False, []
    hosts = [(int(r.preference), str(r.exchange).rstrip(".")) for r in answers]
    mx_hosts = [h for _, h in sorted(hosts, key=lambda t: t[0])]
    return bool(mx_hosts), mx_hosts


def _check_smtp(mx_host: str, email: str, timeout: int = 10) -> tuple[bool, str]:
    """Tenta RCPT TO no MX. Retorna (válido, detalhe). Muitos MX bloqueiam → inconclusivo."""
    try:
        with smtplib.SMTP(mx_host, timeout=timeout) as smtp:
            smtp.helo()
            smtp.mail("verify@v7m.org")
            code, msg = smtp.rcpt(email)
            return code < 400, f"{code} {msg.decode(errors='replace')}"
    except (smtplib.SMTPException, OSError) as exc:
        return False, str(exc)


async def validate_email(email: str, *, smtp_check: bool = False) -> EmailValidation:
    """Valida um email: formato, MX e (opcional) handshake SMTP RCPT."""
    result = EmailValidation(email=email)

    ok, domain = _check_format(email)
    if not ok or not domain:
        return result
    result.valid_format = True
    result.domain = domain

    has_mx, mx_hosts = await asyncio.to_thread(_check_mx, domain)
    result.has_mx = has_mx
    result.mx_hosts = mx_hosts
    if not has_mx:
        return result

    if smtp_check and mx_hosts:
        valid, detail = await asyncio.to_thread(_check_smtp, mx_hosts[0], email)
        result.smtp_checked = True
        result.smtp_valid = valid
        result.smtp_detail = detail
        result.is_valid = valid
        logger.info("mail.smtp_checked", email=_mask_email(email), valid=valid)
    else:
        result.is_valid = has_mx
        logger.info("mail.validated", email=_mask_email(email), domain=domain, has_mx=has_mx)
    return result

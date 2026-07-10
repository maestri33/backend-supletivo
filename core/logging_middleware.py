"""Middleware de logging estruturado — request_id + method/path/status/duration."""

import time
import uuid

import structlog

logger = structlog.get_logger("http")


def _safe_path(path: str) -> str:
    """G1/#31: o nome do arquivo de mídia É a credencial (token aleatório, sem gate de dono ainda),
    então logá-lo em claro vaza o acesso. `/media/<prefixo>/<token>.<ext>` → loga só até o prefixo.
    O resto do site loga o path inteiro (é o que serve pra diagnóstico)."""
    if path.startswith("/media/"):
        head, sep, tail = path.rpartition("/")
        if sep and tail:
            return f"{head}/<redacted>"
    return path


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.request_id = request_id
        t0 = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - t0) * 1000)
        logger.info(
            "request",
            request_id=request_id,
            method=request.method,
            path=_safe_path(request.path),
            status=response.status_code,
            duration_ms=duration_ms,
        )
        response["x-request-id"] = request_id
        return response

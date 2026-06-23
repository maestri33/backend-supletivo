"""Signals do enrollment.

`enrollment_ready_for_matricula`: disparado quando a matrícula entra em `awaiting_release` — o
ponto onde o bot matriculador (futuro) tentaria fazer a matrícula no SIGA externo. É o 1º signal
do repo (o padrão da casa é call explícito); introduzido de propósito pra **desacoplar** a casca
do bot (`core/todo`) do funil do enrollment, sem o enrollment depender de `core.todo`.

kwargs do envio: `enrollment` (a instância `Enrollment`).
"""

from __future__ import annotations

import django.dispatch

enrollment_ready_for_matricula = django.dispatch.Signal()

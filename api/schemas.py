"""Schemas compartilhados entre grupos da API Ninja (CONVENTION §12: reusar, não duplicar).

Schemas aqui:
- `MaterialIn` / `MaterialUpdateIn` — autoria de matéria (staff + leadership, plan/15 A7).
- `RefreshIn` / `TokenOut` — tokens (dedup #4, todos os grupos).
- Schemas de candidato / endereço / selfie compartilhados entre `collaborators` e `leadership`
  (dedup #5 — shapes idênticos, fonte única evita drift).
"""

from __future__ import annotations

from ninja import Field, Schema


class MaterialIn(Schema):
    """Criação de uma matéria do treino: conteúdo (texto/blocos) + questão + gabarito.

    `kind` fixa (todo promotor novo recebe) ou transitória (staff publica p/ os existentes);
    `blocking` = obrigatória (trava o painel); `ephemeral` = descartável; `content_blocks` =
    conteúdo rico (texto/imagem/vídeo/arquivo) que o front renderiza em ordem."""

    title: str
    question: str
    expected_answer: str
    text_content: str = ""
    content_blocks: list[dict] = []
    order: int = 0
    kind: str = "fixed"
    blocking: bool = True
    ephemeral: bool = False
    video: str | None = None
    photo: str | None = None


class MaterialUpdateIn(Schema):
    """Edição de uma matéria — só os campos enviados; `active=False` desativa."""

    title: str | None = None
    text_content: str | None = None
    content_blocks: list[dict] | None = None
    question: str | None = None
    expected_answer: str | None = None
    order: int | None = None
    active: bool | None = None
    kind: str | None = None
    blocking: bool | None = None
    ephemeral: bool | None = None
    video: str | None = None
    photo: str | None = None


class RefreshIn(Schema):
    """Body do `POST /auth/refresh` — compartilhado pelos 3 grupos (dedup #4)."""

    refresh_token: str


class TokenOut(Schema):
    """Par de tokens devolvido por `login`/`refresh` — compartilhado pelos grupos (dedup #4)."""

    access_token: str
    refresh_token: str
    token_type: str


# ── schemas de candidato/endereço/selfie (dedup #5) ──────────────────────────
# Usados por `collaborators` (funil do candidato) e `leadership` (coordenador decide).
# Mesma fonte → nunca desincronizam.


class SharedCandidateProfileOut(Schema):
    """Perfil do candidato (name/birth_date do CPFHub + dados complementares)."""

    mother_name: str | None = None
    father_name: str | None = None
    birthplace: str | None = None
    marital_status: str | None = None
    nationality: str | None = None
    name: str | None = None
    birth_date: str | None = None


class SharedCandidateDocSubOut(Schema):
    """Sub-documento genérico (RG/CNH/certidão/militar): foto + número básico + validação."""

    number: str | None = None
    issuing_agency: str | None = None
    issue_date: str | None = None
    category: str | None = None
    date_of_birth: str | None = None
    expires_on: str | None = None
    national_register: str | None = None
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    validation_status: str | None = None
    validation_reason: str | None = None
    # campos extras do leadership (kind/registry_office/book/page/entry/photo/series/ra)
    kind: str | None = None
    registry_office: str | None = None
    book: str | None = None
    page: str | None = None
    entry: str | None = None
    photo: str | None = None
    series: str | None = None
    ra: str | None = None


class SharedCandidateDocumentsOut(Schema):
    """Bloco de documentos do candidato."""

    external_id: str
    rg: SharedCandidateDocSubOut | None = None
    cnh: SharedCandidateDocSubOut | None = None
    certificate: SharedCandidateDocSubOut | None = None
    military: SharedCandidateDocSubOut | None = None


class SharedCandidateSelfieOut(Schema):
    """Selfie/assinatura do candidato: foto + análise IA + TTL."""

    exists: bool
    photo: str | None = None
    taken_at: str | None = None
    status: str | None = None
    analysis_status: str | None = None
    analysis_reason: str | None = None
    expires_at: str | None = None
    verified: bool
    description: str | None = None


class SharedAddressOut(Schema):
    """Endereço com `cep`/`zipcode` (alias compat) e `missing_fields`."""

    cep: str | None = None
    zipcode: str | None = None
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    missing_fields: list[str] = []


class SharedCandidateMeOut(Schema):
    """/me RICO do candidato — devolvido por TODA mutação do wizard e por decisões do coordenador."""

    external_id: str
    status: str
    hub_external_id: str
    pix_validated: bool
    selfie_verified: bool
    selfie_status: str | None = None
    profile: SharedCandidateProfileOut | None = None
    address: SharedAddressOut | None = None
    documents: SharedCandidateDocumentsOut | None = None
    selfie: SharedCandidateSelfieOut | None = None


class SharedAnalysisAckOut(Schema):
    """Ack de upload que dispara análise assíncrona (documento ou selfie)."""

    stored: bool | str
    analysis_status: str | None = None
    poll_after_ms: int
    expires_at: str | None = None

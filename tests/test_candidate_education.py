from __future__ import annotations

import uuid

import pytest


def _candidate_at_pix():
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User
    from users.profiles.models import Profile
    from users.documents import service as documents
    from users.roles.candidate.models import Candidate

    coordinator = User.objects.create_user(external_id=uuid.uuid4())
    hub = Hub.objects.create(
        address=Address.objects.create(city="Ponta Grossa", state="PR"),
        brand="test",
        coordinator=coordinator,
        is_default=True,
    )
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(
        user=user,
        cpf=str(uuid.uuid4().int)[:11],
        phone=str(uuid.uuid4().int)[:13],
        address=Address.objects.create(),
    )
    documents.create_empty(user)
    Candidate.objects.create(user=user, hub=hub, status=Candidate.Status.PIX)
    return user


@pytest.mark.django_db
def test_primeiro_medio_concluido_nao_vira_medio_completo():
    from users.profiles.models import Profile
    from users.roles.candidate import service

    user = _candidate_at_pix()
    service.set_education(
        user_external_id=str(user.external_id),
        level="medio",
        grade=1,
        education_status="completed",
        completed=False,
        year=2026,
        city=" Ponta Grossa ",
        school=" Colégio Exemplo ",
    )

    profile = Profile.objects.get(user=user)
    assert profile.education_completed is False
    assert profile.education_grade == 1
    assert profile.education_status == "completed"
    assert profile.education_city == "Ponta Grossa"
    assert profile.education_school == "Colégio Exemplo"


@pytest.mark.django_db
def test_terceiro_medio_concluido_vira_medio_completo():
    from users.profiles import interface as profiles
    from users.roles.candidate import service

    user = _candidate_at_pix()
    service.set_education(
        user_external_id=str(user.external_id),
        level="medio",
        grade=3,
        education_status="completed",
        completed=True,
        year=2026,
    )

    assert profiles.has_medio_completo(user) is True


@pytest.mark.django_db
def test_serie_incompativel_retorna_erro_recuperavel():
    from users.roles.candidate import service

    user = _candidate_at_pix()
    with pytest.raises(service.CandidateError) as exc:
        service.set_education(
            user_external_id=str(user.external_id),
            level="medio",
            grade=8,
            education_status="stopped",
            completed=False,
            year=2026,
        )

    assert exc.value.code == "EDUCATION_GRADE_INVALID"

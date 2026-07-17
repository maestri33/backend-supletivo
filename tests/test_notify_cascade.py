"""Cascade delete: Trigger é OneToOne com Template (on_delete=CASCADE).
Deletar Template deve deletar o Trigger vinculado."""

import pytest

from notify.models import Template, Trigger

pytestmark = pytest.mark.django_db


def test_trigger_cascade_com_template():
    t = Template.objects.create(event="test.cascade.1", body_md="oi")
    Trigger.objects.create(template=t, fires_on="teste")
    assert Trigger.objects.count() == 1
    t.delete()
    assert Trigger.objects.count() == 0, "Trigger sobreviveu ao delete do Template (cascade quebrado)"


def test_template_sem_trigger_deleta_normal():
    t = Template.objects.create(event="test.cascade.2", body_md="oi")
    t.delete()  # sem trigger vinculado — não deve explodir
    assert Template.objects.filter(event="test.cascade.2").count() == 0

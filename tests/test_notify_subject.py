"""Assunto de e-mail derivado do corpo quando o template não traz subject/title.

Regressão do "e-mail sem assunto": 48 templates do seed nascem com subject/title vazios; o dispatch
passava a mandar o literal "(sem assunto)". Agora deriva um assunto real da 1ª frase do corpo.
"""

from notify.dispatch import _subject_from_body


def test_deriva_1a_frase_e_tira_saudacao():
    got = _subject_from_body(
        "Marilu, um candidato concluiu o cadastro e aguarda a aprovação. Confira no painel."
    )
    assert got == "Um candidato concluiu o cadastro e aguarda a aprovação"


def test_tira_markdown_e_link():
    got = _subject_from_body(
        "Diandra, seu **documento** foi [aprovado](http://x)! Vamos."
    )
    assert got == "Seu documento foi aprovado"


def test_nunca_vazio_quando_ha_corpo():
    # invariante que mata o bug: com corpo, jamais volta "" (o caller cai pro brand, não "(sem assunto)")
    assert _subject_from_body("Precisamos de uma nova foto do seu documento.")
    assert _subject_from_body("") == ""


def test_corta_em_78_chars():
    got = _subject_from_body("A" + " palavra" * 40)
    assert len(got) <= 79  # 78 + reticências

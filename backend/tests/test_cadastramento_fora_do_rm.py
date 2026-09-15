"""Convenio estadual em CADASTRAMENTO nao entra no RM (dono, 15/09/2026).

O RM de Araujos imprimia "Seapa - SIGCON · Convenio 002567/2026 · Valor global
R$ 0,00 · Situacao atual: Cadastramento · sem alteracoes registradas no SIGCON".
O dono mandou a tela e decidiu: fora. A regra de ano (`_fed_retem`) so barrava
pre-empenho de ANOS ANTERIORES — para ela Cadastramento e 'ativa', e do ano
corrente entra, no anual e no completo. Por isso o corte e proprio, de ESTAGIO,
e vem antes da regra de ano.
"""
import os

from services.rm_builder import _em_cadastramento, _fed_retem, _fed_status

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER = os.path.join(RAIZ, "services", "rm_builder.py")


def test_cadastramento_em_qualquer_grafia():
    for s in ("Cadastramento", "CADASTRAMENTO", "cadastramento", "Em Cadastramento",
              " Cadastramento ", "Cadastramento · sem alterações"):
        assert _em_cadastramento(s), s


def test_CONVENIO_CADASTRADO_do_ckan_NAO_e_cadastramento():
    """⚠️ Instrumento CELEBRADO que o backfill insere com a situacao verbatim do
    Estado — e com repasse. A substring 'cadastr' o derrubaria junto, calado."""
    assert not _em_cadastramento("CONVENIO CADASTRADO")
    assert not _em_cadastramento("Convênio Cadastrado")
    assert not _em_cadastramento("Cadastrado")


def test_outras_situacoes_e_vazio_nao_classificam():
    for s in ("Em vigor", "Encerrado", "Cancelado", "Análise", "Celebração", "", None):
        assert not _em_cadastramento(s), repr(s)


def test_a_regra_de_ano_sozinha_DEIXAVA_o_cadastramento_do_ano_passar():
    """O motivo de existir um corte proprio: para `_fed_retem`, Cadastramento e
    'ativa' e do ano corrente ENTRA — anual e completo. Se um dia `_fed_retem`
    passar a barrar, este teste avisa que o corte ficou redundante (nao errado)."""
    assert _fed_status("Cadastramento") == "ativa"
    assert _fed_retem(2026, 2026, "Cadastramento", completo=False) is True
    assert _fed_retem(2026, 2026, "Cadastramento", completo=True) is True
    assert _fed_retem(2026, 2026, "Cadastramento", completo=True, anos_sel={2026}) is True


def test_so_sobre_a_coluna_crua__a_narrativa_da_alteracao_casaria():
    """Documenta o LIMITE da funcao: a ultima alteracao de um convenio VIGENTE
    pode ser "CADASTRAMENTO DA ALTERACAO" (termo aditivo em cadastro), e a regex
    casa. Passada a narrativa de `_situacao_estadual`, um convenio em vigor
    cairia por causa do aditivo — por isso o call-site le `c.situacao`."""
    assert _em_cadastramento("Em vigor · CADASTRAMENTO DA ALTERAÇÃO (Termo aditivo)") is True
    src = open(BUILDER, encoding="utf-8").read()
    assert "if _em_cadastramento(c.situacao):" in src
    assert "_em_cadastramento(_situacao_estadual" not in src


def test_o_corte_vem_ANTES_da_regra_de_ano_no_bloco_estadual():
    """Corte de ESTAGIO antes do corte de ANO: vale para os dois relatorios e
    para qualquer selecao de anos, e nao depende de `nr_instr`/vigencia."""
    src = open(BUILDER, encoding="utf-8").read()
    bloco = src[src.index("=== SIGCON-MG (estadual)"):src.index("=== TransfereGov Voluntarias")]
    i_corte = bloco.index("if _em_cadastramento(c.situacao):")
    i_ano = bloco.index("_fed_retem(ano_est")
    assert i_corte < i_ano
    assert "continue" in bloco[i_corte:i_corte + 120]

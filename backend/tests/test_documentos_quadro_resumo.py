"""A aba Documentos do TransfereGov — a coluna "Ações" não é dado.

A grade do portal tem uma coluna de BOTÕES do PrimeFaces, e `textContent`
devolve o `onclick` inteiro como se fosse texto:

    Baixar arquivoPrimeFaces.cw("CommandButton","widget_tabViewMandatarias_frm…

Isso era gravado no JSONB e impresso, campo a campo, no modal que o gestor abre
para LER o parecer. Relatado com print (Arapuá/MG, 26/08/2026).

⚠️ O JS injetado não pode ser exercitado aqui (jsdom não está no projeto), então
o que estes testes fixam é o CRITÉRIO — o mesmo regex nos dois lados — e a sua
presença nos dois arquivos. O critério é o que decide, e é ele que estava errado.
"""
import io
import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
_COLETOR = _RAIZ / "ingestion" / "transferegov_voluntarias.py"
_TELA = _RAIZ.parent / "frontend" / "src" / "components" / "TransfereGovPropostas.tsx"

# O critério, escrito em Python com a MESMA semântica das duas cópias em JS.
_CAB_ACAO = re.compile(r"^\s*a[çc][ãaõo](o|es)\s*$", re.I)
_VAL_JS = re.compile(r"PrimeFaces\.|CommandButton|widget_")


def _descarta(cabecalho: str, valor: str) -> bool:
    return bool(_CAB_ACAO.match(cabecalho or "") or _VAL_JS.search(valor or ""))


# ------------------------------------------------------------- o critério ----
@pytest.mark.parametrize("cab", ["Ações", "AÇÕES", "Ação", "AÇÃO", "acoes", "acao",
                                 " Ações "])
def test_toda_grafia_de_acao_e_descartada(cab):
    """O portal escreve em caixa alta; o acento some quando a codificação quebra;
    e existe a forma singular. As quatro variações têm de cair."""
    assert _descarta(cab, "qualquer coisa")


@pytest.mark.parametrize("cab", ["Descrição", "Tipo", "Data de Envio", "Perfil",
                                 "Enviado por", "Nome do Arquivo", "Situação"])
def test_as_colunas_de_VERDADE_ficam(cab):
    """Os campos do print. `Situação` é o caso perigoso: começa com as mesmas
    letras de `Ações` numa comparação preguiçosa."""
    assert not _descarta(cab, "Parecer")


def test_o_ONCLICK_do_print_e_descartado_pelo_VALOR():
    """⚠️ A defesa que aguenta. O NOME da coluna pode mudar, ou vir vazio (`col5`),
    mas a assinatura do PrimeFaces no valor não engana. É o texto literal do
    print de 26/08/2026."""
    v = ('Baixar arquivoPrimeFaces.cw("CommandButton","widget_tabViewMandatarias_'
         'frmQuadroResumo_quadro_resumodtListaArquivos_0_quadro_resumobtnDownload"')
    assert _descarta("col5", v)
    assert _descarta("", v)


def test_o_conteudo_util_do_print_NAO_e_descartado():
    for cab, val in [("Descrição", "Parecer"),
                     ("Tipo", "Documento Quadro Resumo"),
                     ("Perfil", "Mandatária"),
                     ("Enviado por", "ADRIANA MARA DA SILVEIRA"),
                     ("Data de Envio", "21/01/2026"),
                     ("Nome do Arquivo",
                      "PM Arapua - 1103633-22 - Parecer de Area_assinado.pdf")]:
        assert not _descarta(cab, val), (cab, val)


# ------------------------------------------- o critério existe NOS DOIS lados --
def test_o_coletor_descarta_a_coluna_de_acao():
    """Sem isto o lixo volta a ser GRAVADO na próxima passagem do lote."""
    s = io.open(_COLETOR, encoding="utf-8").read()
    assert "ehAcao" in s
    assert "PrimeFaces" in s and "CommandButton" in s
    assert "a[çc][ãaõo](o|es)" in s


def test_a_tela_TAMBEM_descarta():
    """⚠️ Os dois, e não só o coletor. O JSONB de todas as propostas já coletadas
    continua com o lixo até a próxima passagem do lote (2 em 2h, e só as
    celebradas) — sem o filtro na tela, ela seguiria feia por dias."""
    s = io.open(_TELA, encoding="utf-8").read()
    assert "a[çc][ãaõo](o|es)" in s
    assert "PrimeFaces" in s and "CommandButton" in s


def test_registro_que_so_tinha_botao_nao_vira_cartao_vazio():
    """Nos dois lados: no coletor a linha não entra, e na tela o cartão some."""
    assert "if (Object.keys(o).length) out.push(o);" in io.open(_COLETOR, encoding="utf-8").read()
    assert "if (!vals.length) return null;" in io.open(_TELA, encoding="utf-8").read()

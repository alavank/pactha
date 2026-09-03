"""O RM passa a LER a coluna `valor_empenhado` do dado aberto.

O #333 criou a coluna e o coletor a preencheu; o RM continuou calculando o
empenho SO pela listagem de NEs da aba logada. Resultado medido em producao
(freitas, 31/08/2026): o convenio 932836 tinha R$ 819.375,12 gravados em
`valor_empenhado` e o relatorio nao dizia nada — porque `notas_empenho` e NULA
nele, como em 2.741 das 3.199 propostas do tenant.

Coluna preenchida que ninguem le nao muda nada na tela. Estes testes existem
para que a ponta do consumo nao se solte de novo.
"""
import os
import re

from services.rm_builder import (_empenhado_rotulo, _empenho_total,
                                 _empenho_valor, _sem_empenho)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER = os.path.join(RAIZ, "services", "rm_builder.py")

# Uma NE real, no formato que o coletor DE FATO grava.
#
# ⚠️ A primeira versao deste fixture usava "200000,00" — a string com virgula,
# como aparece na tela. Errado: `transferegov_voluntarias` grava
# `"valor": _num_br(...)`, ja convertido, e o `_money` do rm_builder e um
# `float(x)` seco que devolve None para a string brasileira. O teste reprovava
# codigo que funciona, e "consertar" o codigo para atender o fixture teria
# quebrado o caso real.
_NE = [{"numero": "2021NE651547", "valor": 200000.0}]
_SO_MINUTA = [{"numero": "—", "valor": 500.0, "minuta_apenas": True}]


def _codigo(caminho):
    """Sem comentario de Python (#) NEM de SQL (--).

    ⚠️ Os dois precisam sair. O SELECT das voluntarias mora dentro de uma string
    e leva comentarios `--` que citam nomes de coluna; filtrar so `#` deixava
    esse texto entrar na lista de colunas e a ultima "coluna" virava um paragrafo
    inteiro de comentario."""
    return "\n".join(l for l in open(caminho, encoding="utf-8").read().splitlines()
                     if not l.lstrip().startswith(("#", "--")))


# --------------------------------------------------------------------------
# A regra de precedencia
# --------------------------------------------------------------------------
def test_o_agregado_preenche_quando_a_listagem_nunca_foi_consultada():
    """O caso do 932836: `notas_empenho` NULA e o portal publicando o valor."""
    assert _empenho_valor(None) is None, "premissa: listagem nao consultada"
    assert _empenho_total(None, 819375.12) == 819375.12


def test_a_listagem_manda_quando_existe():
    """Ela tem nota, data e situacao; o agregado e um numero solto."""
    assert _empenho_total(_NE, 999999.99) == 200000.00


def test_listagem_consultada_e_VAZIA_vence_o_agregado():
    """⚠️ `0.0` da listagem NAO e ausencia: quer dizer 'consultei e nao ha'.
    Deixar o agregado passar por cima apagaria uma medicao de verdade."""
    assert _empenho_valor([]) == 0.0
    assert _empenho_total([], 819375.12) == 0.0


def test_sem_nenhuma_das_duas_continua_calado():
    """None e o que faz o rm_pdf OMITIR a linha, em vez de imprimir R$ 0,00."""
    assert _empenho_total(None, None) is None
    assert _empenho_total(None, "") is None


def test_so_minuta_nao_conta_como_empenho_e_o_agregado_nao_entra():
    """A minuta ja era descartada; a listagem segue 'consultada', entao o
    agregado nao substitui — vale o 0.0 medido."""
    assert _empenho_total(_SO_MINUTA, 819375.12) == 0.0


# --------------------------------------------------------------------------
# O rotulo "Empenhado: Sim"
# --------------------------------------------------------------------------
def test_agregado_positivo_vale_como_prova_de_empenho():
    """Situacao 'Proposta/Plano de Trabalho Aprovados' NAO e ciclo empenhado —
    era por isso que o 932836 nao ganhava nem o 'Sim'."""
    sit = "Proposta/Plano de Trabalho Aprovados"
    assert _empenhado_rotulo(None, sit) == "", "premissa: sem o agregado, calava"
    assert _empenhado_rotulo(None, sit, 819375.12) == "Sim"


def test_agregado_zero_continua_calando():
    """⚠️ Zero nao prova ausencia: pode ser convenio sem empenho OU coluna nunca
    coletada, e os dois chegam iguais. Dizer 'Nao' seria afirmar o nao medido."""
    sit = "Proposta/Plano de Trabalho Aprovados"
    assert _empenhado_rotulo(None, sit, 0) == ""
    assert _empenhado_rotulo(None, sit, None) == ""


def test_o_rotulo_antigo_nao_regride():
    """Sem o parametro novo, a saida tem de ser a de antes — o argumento e
    opcional justamente para nao mexer em quem ja chamava."""
    assert _empenhado_rotulo(_NE, "qualquer") == "Sim"
    assert _empenhado_rotulo(None, "Em execução") == "Sim"
    assert _empenhado_rotulo(None, "Proposta/Plano de Trabalho Rejeitados") == ""


# --------------------------------------------------------------------------
# "PENDENTE DE EMPENHO" nao pode contradizer o portal
# --------------------------------------------------------------------------
def test_pendente_de_empenho_cala_quando_o_portal_diz_que_ha_empenho():
    """⚠️ A afirmacao vai IMPRESSA na mesa do prefeito. Se a listagem voltou
    vazia mas o dado aberto publica valor, as duas fontes discordam — e diante da
    discordancia o relatorio tem de calar, nao escolher.

    A regra vive no laco (nao ha funcao isolada), entao o teste le a expressao."""
    src = _codigo(BUILDER)
    # ⚠️ Nada de regex com `)` como fim: a expressao TEM parenteses dentro
    # (`_sem_empenho(row[25])`), e o nao-guloso parava no primeiro deles — o
    # teste reprovava por corte, nao por defeito. Recorte por posicao.
    i = src.index("_pend_empenho = (")
    expr = " ".join(src[i:i + 260].split())
    assert "_e_termo_compromisso(row[28])" in expr
    assert "_sem_empenho(row[25])" in expr
    assert "row[29]" in expr, "o agregado nao entra na decisao de PENDENTE"
    assert "not (" in expr, "o agregado tem de NEGAR a pendencia, nao confirma-la"
    # e a premissa que a expressao usa continua valendo
    assert _sem_empenho([]) is True


# --------------------------------------------------------------------------
# O indice: a armadilha da casa
# --------------------------------------------------------------------------
def test_a_coluna_nova_e_a_ULTIMA_do_select():
    """⚠️ O laco le por INDICE. `modalidade` era row[28] e cinco colunas ja
    estavam penduradas no fim por esta mesma razao; inserir no meio deslocaria
    todas em silencio — sai relatorio errado, sem excecao."""
    src = _codigo(BUILDER)
    ini = src.index("FROM transferegov_propostas WHERE municipio_id = :m")
    sel = src[src.rindex("SELECT", 0, ini):ini]
    colunas = [c.strip() for c in sel.replace("SELECT", "", 1).split(",")]
    colunas = [c for c in colunas if c and not c.startswith("--")]
    # ⚠️ ESTE GUARDA MORDEU DE VERDADE em 03/09/2026, e a atualizacao e o registro
    # disso: `situacao_projeto_basico` foi pendurada DEPOIS de `valor_empenhado`
    # (o Termo de Referencia do dado aberto, PR do TR), entao `valor_empenhado`
    # deixou de ser a ultima. Nada quebrou porque o teste avisou antes.
    #
    # O que ele protege NAO mudou: as colunas novas entram no FIM, e os indices
    # ja lidos continuam valendo. `valor_empenhado` segue sendo row[29] — o que
    # importa e a POSICAO dele, nao ser o ultimo.
    assert colunas[-1] == "situacao_projeto_basico", \
        f"a ultima coluna virou {colunas[-1]!r} — quem entrar depois vai no FIM"
    assert colunas.index("valor_empenhado") == 29, \
        f"valor_empenhado saiu de row[29] (esta em row[{colunas.index('valor_empenhado')}])"
    assert colunas.index("modalidade") == 28, "modalidade deixou de ser row[28]"
    assert len(colunas) == 31, f"o SELECT tem {len(colunas)} colunas, esperava 31"


def test_o_item_usa_as_duas_fontes_e_nao_so_a_listagem():
    src = _codigo(BUILDER)
    assert '"valor_empenhado": _empenho_total(row[25], row[29])' in src, \
        "o item voltou a ler so a listagem de NEs"
    assert "_empenhado_rotulo(row[25], sit, row[29])" in src

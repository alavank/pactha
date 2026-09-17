"""O radar carrega as DUAS portas: recebimento de proposta e emenda parlamentar.

⚠️ POR QUE ESTE ARQUIVO EXISTE. Ate 02/09/2026 `agrupa()` descartava a linha
olhando so `DT_PROG_FIM_RECEB_PROP`:

    fim = data_br(l.get("DT_PROG_FIM_RECEB_PROP"))
    if fim is None or fim < hoje:
        continue

O `continue` matava a linha ANTES de qualquer gravacao. Medido no arquivo real em
02/09/2026, com o mesmo recorte (DISPONIBILIZADO + natureza municipal): 17
programas com recebimento aberto, 72 com emenda aberta, 112 na uniao. O radar
carregava 17 — 15%. Por UF, que e o que o gestor ve: MG mostrava 9 de 35.

E nao era "temos e nao exibimos": os outros 95 nunca entravam no banco, e a
coleta gravava `success`. Nada acusava.

⚠️ AS PORTAS NAO SAO INTERCAMBIAVEIS, e por isso metade dos testes daqui e sobre
NAO CONFUNDIR as duas. Recebimento e proposta espontanea — a prefeitura
protocola. Emenda parlamentar depende de um deputado ou senador destinar o
recurso: o gestor nao cumpre esse prazo sozinho. Listar as duas sem distinguir
faria o prefeito montar proposta para uma porta que nao depende dele, o que e
pior do que nao mostrar o programa.

BENEF_ESP entrou em 17/09/2026 como terceira porta, so para o municipio
nomeado: ver `test_radar_beneficiario.py`.
"""
import re
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("psycopg2")

from ingestion import programas_captacao as P  # noqa: E402

HOJE = date(2026, 9, 2)
RAIZ = Path(__file__).resolve().parent.parent


def _linha(**kw):
    """Linha do siconv_programa.zip. Padrao: recebimento ABERTO, emenda ausente."""
    base = {
        "ID_PROGRAMA": "900", "COD_PROGRAMA": "2629120260003",
        "NOME_PROGRAMA": "Programa X", "SIT_PROGRAMA": "DISPONIBILIZADO",
        "NATUREZA_JURIDICA_PROGRAMA": "Administração Pública Municipal",
        "DESC_ORGAO_SUP_PROGRAMA": "MINISTERIO DA EDUCACAO",
        "COD_ORGAO_SUP_PROGRAMA": "26000",
        "MODALIDADE_PROGRAMA": "CONVENIO",
        "UF_PROGRAMA": "MG",
        "DT_PROG_INI_RECEB_PROP": "01/01/2026",
        "DT_PROG_FIM_RECEB_PROP": "31/12/2026",
        "DT_PROG_INI_EMENDA_PAR": "",
        "DT_PROG_FIM_EMENDA_PAR": "",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# A porta nova entra
# --------------------------------------------------------------------------

def test_emenda_aberta_entra_mesmo_com_recebimento_vencido():
    """O caso dos 67 programas que estavam invisiveis."""
    l = _linha(DT_PROG_FIM_RECEB_PROP="31/01/2026",      # vencido ha meses
               DT_PROG_INI_EMENDA_PAR="01/08/2026",
               DT_PROG_FIM_EMENDA_PAR="30/11/2026")      # aberta
    assert P.agrupa([l], HOJE), (
        "programa com emenda aberta continua sendo descartado — e o defeito "
        "que deixava 67 de 112 fora do radar")


def test_emenda_sem_data_de_inicio_conta_como_aberta():
    """Ausencia de `dt_ini` nao pode fechar a porta.

    O mesmo criterio que o recebimento ja usava: sem inicio declarado, o que
    manda e o fim. Tratar ausencia como "fechada" esconderia programa valido.
    """
    l = _linha(DT_PROG_FIM_RECEB_PROP="31/01/2026",
               DT_PROG_INI_EMENDA_PAR="",
               DT_PROG_FIM_EMENDA_PAR="30/11/2026")
    assert P.agrupa([l], HOJE)


def test_recebimento_aberto_continua_entrando():
    """A porta antiga nao pode ter sido trocada pela nova."""
    assert P.agrupa([_linha()], HOJE)


# --------------------------------------------------------------------------
# E o que tem de continuar fora
# --------------------------------------------------------------------------

def test_as_duas_portas_fechadas_descarta():
    l = _linha(DT_PROG_FIM_RECEB_PROP="31/01/2026",
               DT_PROG_INI_EMENDA_PAR="01/01/2026",
               DT_PROG_FIM_EMENDA_PAR="28/02/2026")
    assert not P.agrupa([l], HOJE)


def test_emenda_que_ainda_nao_abriu_nao_conta():
    """⚠️ A JANELA TEM DOIS LADOS, e isso vale para a porta nova tambem.

    Um programa cuja emenda so abre em novembro nao esta aberto hoje. Sem esta
    guarda o gestor mobilizaria um parlamentar para uma janela que o sistema
    ainda nao aceita — e a tela promete "aberto hoje".
    """
    l = _linha(DT_PROG_FIM_RECEB_PROP="31/01/2026",
               DT_PROG_INI_EMENDA_PAR="01/11/2026",
               DT_PROG_FIM_EMENDA_PAR="31/12/2026")
    assert not P.agrupa([l], HOJE)


def test_recebimento_que_ainda_nao_abriu_nao_conta():
    l = _linha(DT_PROG_INI_RECEB_PROP="01/11/2026", DT_PROG_FIM_RECEB_PROP="31/12/2026")
    assert not P.agrupa([l], HOJE)


def test_a_porta_nova_nao_afrouxa_situacao_nem_natureza():
    """Abrir uma porta de DATA nao pode abrir as portas de ELEGIBILIDADE."""
    emenda_ok = {"DT_PROG_FIM_RECEB_PROP": "31/01/2026",
                 "DT_PROG_INI_EMENDA_PAR": "01/08/2026",
                 "DT_PROG_FIM_EMENDA_PAR": "30/11/2026"}
    assert not P.agrupa([_linha(SIT_PROGRAMA="CADASTRADO", **emenda_ok)], HOJE)
    # Natureza fora do catalogo continua barrada no coletor.
    assert not P.agrupa([_linha(NATUREZA_JURIDICA_PROGRAMA="Empresa Privada",
                                **emenda_ok)], HOJE)


def test_consorcio_continua_sendo_COLETADO_e_cortado_so_na_rota():
    """⚠️ ESTE TESTE CORRIGE UMA EXPECTATIVA MINHA, e o registro importa.

    Escrevi primeiro `assert not agrupa(consorcio)`, supondo que o coletor
    barrasse consorcio publico. Ele NAO barra, de proposito: `NATUREZAS` inclui
    os dois (programas_captacao.py:69) e quem faz o corte e a rota, com
    `:nat = ANY(naturezas)` — porque consorcio e outra pessoa juridica e o
    prefeito nao assina por ele, mas o dado tem valor e nao se joga fora na
    coleta.

    A divisao e deliberada: coletar largo, exibir estreito. Um teste que exigisse
    o corte no coletor estaria empurrando o sistema para o desenho errado.
    """
    l = _linha(NATUREZA_JURIDICA_PROGRAMA="Consórcio Público",
               DT_PROG_FIM_RECEB_PROP="31/01/2026",
               DT_PROG_INI_EMENDA_PAR="01/08/2026",
               DT_PROG_FIM_EMENDA_PAR="30/11/2026")
    saida = P.agrupa([l], HOJE)
    assert saida, "consorcio deixou de ser coletado"
    assert "Consórcio Público" in next(iter(saida.values()))["naturezas"]
    # E a rota continua cortando pela natureza da prefeitura.
    rota = (RAIZ / "routers" / "programas_captacao.py").read_text(encoding="utf-8")
    assert ":nat = ANY(naturezas)" in rota


def test_benef_esp_entra_na_coleta_e_o_corte_e_na_rota():
    """BENEF_ESP ficava fora "ate alguem decidir", e este teste existia para
    forcar a conversa. Ela aconteceu em 17/09/2026: a porta entra na coleta e
    SO o municipio nomeado a ve, pelo CNPJ, na rota. Os testes da porta nova
    moram em `test_radar_beneficiario.py`."""
    l = _linha(DT_PROG_FIM_RECEB_PROP="31/01/2026",
               DT_PROG_INI_BENEF_ESP="01/08/2026",
               DT_PROG_FIM_BENEF_ESP="30/11/2026")
    assert P.agrupa([l], HOJE)
    rota = (RAIZ / "routers" / "programas_captacao.py").read_text(encoding="utf-8")
    assert ":cnpj = ANY(p.proponentes_cnpj)" in rota


# --------------------------------------------------------------------------
# O router precisa acompanhar
# --------------------------------------------------------------------------

def test_o_router_devolve_a_porta_e_ordena_pelo_prazo_que_vale():
    """⚠️ Sem `porta` na resposta, a tela nao consegue distinguir — e listar as
    duas juntas sem rotulo e o desfecho pior que este PR poderia ter."""
    fonte = (RAIZ / "routers" / "programas_captacao.py").read_text(encoding="utf-8")
    # Desde 17/09/2026 sao tres portas e a resposta leva a LISTA delas.
    assert '"portas"' in fonte, "o router parou de devolver `portas` para a tela"
    for termo in ("porta_receb", "porta_emenda", "porta_benef"):
        assert termo in fonte, f"`{termo}` sumiu do router"
    # A ordenacao nao pode voltar a ser sempre por dt_fim_receb: num programa so
    # de emenda esse campo e data PASSADA, e ele iria para o topo como se fosse
    # o mais urgente.
    assert re.search(r"ORDER BY\s+LEAST", fonte), (
        "a ordenacao voltou a usar um prazo so — programa de emenda seria "
        "ordenado por uma data ja vencida")


def test_a_tela_distingue_as_duas_portas():
    tela = (RAIZ.parent / "frontend" / "src" / "app" / "dashboard"
            / "transferegov-radar" / "page.tsx").read_text(encoding="utf-8")
    assert "emenda parlamentar" in tela.lower()
    assert 'tem(p, "emenda") && !tem(p, "recebimento")' in tela, (
        "a tela nao trata a porta de emenda em separado — o gestor leria a lista "
        "inteira como 'e so protocolar'")
    assert "function prazo(" in tela, (
        "sumiu o helper que escolhe o prazo da porta aberta; o cartao voltaria a "
        "mostrar `dt_fim_receb`, que num programa de emenda e data vencida")

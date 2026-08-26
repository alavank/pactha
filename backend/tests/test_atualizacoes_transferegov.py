"""Painel de ATUALIZAÇÕES da aba TransfereGov — mudanças de status recentes.

O painel lê `status_changes`, que é escrita por um TRIGGER no banco. Isso cria um
acoplamento que nenhum teste de Python pega sozinho: o rótulo que o trigger grava
em `fonte` é uma string literal dentro do arquivo .sql, e o filtro do painel é
outra string literal dentro do .py. Se as duas divergirem, a consulta devolve
ZERO linhas — sem erro, sem log, com um painel que se lê como "nada mudou".

Por isso o primeiro teste lê o .SQL DE VERDADE e compara com a constante.
"""
import asyncio
import io
import re
from pathlib import Path

import pytest

from routers import bi
from routers.status_changes import (
    FONTE_FNS, FONTE_SIGCON, FONTE_VOLUNTARIAS, listar_core,
)

_SQL = (Path(__file__).resolve().parent.parent
        / "migrations" / "add_status_changes.sql")


# ------------------------------------------------- o contrato com o trigger ---
def test_a_constante_bate_com_o_rotulo_QUE_O_TRIGGER_GRAVA():
    """⚠️ O TESTE QUE IMPEDE O PAINEL VAZIO SILENCIOSO.

    O trigger grava `'voluntaria'` para `transferegov_propostas` — e não
    `'transferegov'`, que é o nome que a MESMA coluna `fonte` tem em
    `scraper_municipio_coleta`. Duas tabelas, dois vocabulários, a mesma palavra.
    Filtrar pelo nome errado devolve zero linhas e nada acusa."""
    sql = io.open(_SQL, encoding="utf-8").read()
    m = re.search(r"TG_TABLE_NAME\s*=\s*'transferegov_propostas'\s*THEN"
                  r".*?v_fonte\s*:=\s*'([a-z_]+)'", sql, re.S)
    assert m, "não achei o ramo do transferegov no trigger"
    assert m.group(1) == FONTE_VOLUNTARIAS


def test_as_constantes_das_outras_fontes_tambem_existem_no_trigger():
    sql = io.open(_SQL, encoding="utf-8").read()
    for c in (FONTE_SIGCON, FONTE_FNS):
        assert f"'{c}'" in sql, c


def test_o_trigger_dispara_na_tabela_do_transferegov():
    """Sem o trigger nesta tabela a `status_changes` nunca recebe voluntária, e o
    painel fica vazio para sempre — de novo, sem erro nenhum."""
    sql = io.open(_SQL, encoding="utf-8").read()
    assert re.search(r"CREATE TRIGGER\s+\w+\s+AFTER UPDATE ON transferegov_propostas",
                     sql, re.I)


# -------------------------------------------------------- o filtro por fonte --
class _Res:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Db:
    """Guarda o SQL e os parâmetros — é o que permite afirmar que o filtro entrou
    (e, mais importante, que ele NÃO entra quando ninguém pediu)."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.sql = ""
        self.params = {}

    async def execute(self, stmt, params=None):
        self.sql = " ".join(str(stmt).split())
        self.params = params or {}
        return _Res(self.rows)


def _rodar(db, **kw):
    return asyncio.run(listar_core(db, [1], **kw))


def test_sem_fontes_a_consulta_e_a_DE_ANTES():
    """⚠️ NÃO-REGRESSÃO dos dois chamadores antigos (`/api/status-changes` e a aba
    geral do BI): eles não passam `fontes` e não podem receber filtro nenhum."""
    db = _Db()
    _rodar(db)
    assert "fonte = ANY" not in db.sql
    assert "fontes" not in db.params


def test_com_fontes_o_filtro_entra_e_o_parametro_e_LIGADO():
    db = _Db()
    _rodar(db, fontes=(FONTE_VOLUNTARIAS,))
    assert "fonte = ANY(:fontes)" in db.sql
    # Ligado como parâmetro, nunca interpolado no texto do SQL.
    assert db.params["fontes"] == ["voluntaria"]
    assert "'voluntaria'" not in db.sql


def test_a_janela_de_dias_vai_como_parametro():
    db = _Db()
    _rodar(db, days=15, fontes=(FONTE_VOLUNTARIAS,))
    assert db.params["days"] == 15


def test_carteira_vazia_devolve_vazio_sem_tocar_no_banco():
    db = _Db()
    assert asyncio.run(listar_core(db, [], fontes=(FONTE_VOLUNTARIAS,))) == \
        {"items": [], "total": 0}
    assert db.sql == ""


def test_a_linha_sai_com_o_par_ANTES_e_DEPOIS():
    """O painel mostra a MUDANÇA, não o item — o par tem de chegar inteiro."""
    from datetime import datetime
    db = _Db([(7, "voluntaria", "transferegov_propostas", "048291/2025", "MDS",
               "Reforma da praça", "Em análise", "Aprovada",
               datetime(2026, 8, 20, 10, 0))])
    r = _rodar(db, fontes=(FONTE_VOLUNTARIAS,))
    it = r["items"][0]
    assert it["status_anterior"] == "Em análise"
    assert it["status_novo"] == "Aprovada"
    assert it["ref"] == "048291/2025"
    assert it["changed_at"].startswith("2026-08-20")


# ------------------------------------------------------------- a janela de 15 --
def test_a_janela_do_painel_e_de_15_dias():
    """O número que o dono pediu. Fica em constante porque ele vai para a consulta
    E para o rótulo impresso na tela — cravado nos dois, o painel um dia diria
    "últimos 15 dias" mostrando outra coisa."""
    assert bi._DIAS_ATUALIZACOES == 15


def test_a_aba_manda_a_janela_JUNTO_para_a_tela():
    """A tela imprime `mudancas.dias`, não um 15 escrito no TSX. Este teste é o
    que garante que o campo viaja."""
    import inspect

    fonte = inspect.getsource(bi.aba_transferegov)
    assert '"dias": _DIAS_ATUALIZACOES' in fonte
    assert "FONTE_VOLUNTARIAS" in fonte
    # E a consolidação por instrumento tem de estar no caminho — sem ela o painel
    # volta a mostrar cada escrita, que foi o defeito relatado.
    assert "consolidar_por_ref" in fonte


def test_o_painel_NAO_e_recortado_pelo_filtro_de_ano():
    """⚠️ DECISÃO, não descuido: o filtro de ano da aba recorta o ACERVO; este
    painel responde "o que mexeu nos últimos 15 dias". Uma proposta de 2023 que
    mudou ontem é exatamente a novidade que interessa, e cruzar os dois a
    esconderia justamente de quem filtrou um ano."""
    import inspect

    fonte = inspect.getsource(bi.aba_transferegov)
    # a chamada das mudanças não recebe `periodo`
    chamada = re.search(r"listar_core\((.*?)\)", fonte, re.S)
    assert chamada and "periodo" not in chamada.group(1)


# ---------------------------------------------- consolidacao por instrumento --
# ⭐ O CASO REAL (Nova Serrana/MG, 25/08/2026): a MESMA proposta aparecia quatro
# vezes no painel, indo e voltando entre dois rotulos, porque
# `transferegov_propostas.situacao` tem DOIS escritores (o scraper e o CSV diario)
# e cada um desfazia o do outro. O painel responde "o que mudou na janela", e a
# resposta honesta para uma ida-e-volta e: nada.
from routers.status_changes import consolidar_por_ref, _mesma_situacao  # noqa: E402

A = "Proposta/Plano de Trabalho complementado em Análise"
B = "Proposta Aprovada e Plano de Trabalho Complementado em Análise"


def _m(id_, ant, novo, quando, ref="010532/2026"):
    return {"id": id_, "fonte": "voluntaria", "ref": ref, "orgao": "51000 - ME",
            "objeto": "Projeto Visão de Jogo", "status_anterior": ant,
            "status_novo": novo, "changed_at": quando}


def test_ida_e_volta_NAO_e_noticia():
    """A→B→A: o instrumento voltou para onde estava. Não houve mudança líquida —
    e mostrar isso como três cartões é o defeito que o dono viu na tela."""
    # do mais NOVO para o mais ANTIGO, como o `listar_core` devolve
    itens = [_m(3, A, B, "2026-08-25T10:00"),
             _m(2, B, A, "2026-08-24T22:00"),
             _m(1, A, B, "2026-08-24T08:00")]
    # net: começou em A (o mais antigo) e terminou em B (o mais novo) -> aparece
    assert len(consolidar_por_ref(itens)) == 1
    # agora com uma volta a mais: começa em B e termina em B -> some
    itens2 = [_m(4, B, A, "2026-08-25T23:00")] + itens
    assert consolidar_por_ref(itens2) == []


def test_a_mudanca_liquida_e_do_MAIS_ANTIGO_ao_MAIS_NOVO():
    itens = [_m(3, "Em análise", "Aprovada", "2026-08-25T10:00"),
             _m(2, "Enviada", "Em análise", "2026-08-24T10:00"),
             _m(1, "Rascunho", "Enviada", "2026-08-23T10:00")]
    r = consolidar_por_ref(itens)
    assert len(r) == 1
    assert r[0]["status_anterior"] == "Rascunho"   # o mais ANTIGO da janela
    assert r[0]["status_novo"] == "Aprovada"       # o mais NOVO
    assert r[0]["passos"] == 3                     # e diz que foram 3 escritas


def test_a_data_e_a_do_evento_MAIS_NOVO():
    itens = [_m(2, "X", "Z", "2026-08-25T10:00"), _m(1, "W", "X", "2026-08-20T10:00")]
    assert consolidar_por_ref(itens)[0]["changed_at"] == "2026-08-25T10:00"


def test_instrumentos_DIFERENTES_nao_se_misturam():
    itens = [_m(2, "X", "Y", "2026-08-25T10:00", ref="111/2025"),
             _m(1, "P", "Q", "2026-08-24T10:00", ref="222/2025")]
    r = consolidar_por_ref(itens)
    assert {x["ref"] for x in r} == {"111/2025", "222/2025"}


def test_diferenca_so_de_CAIXA_nao_e_mudanca():
    """Ruído de fonte, não notícia. O trigger compara com `IS DISTINCT FROM` e não
    tem como saber disso — quem sabe é aqui."""
    assert _mesma_situacao("Em Execução", "em execução")
    assert _mesma_situacao("Em  execução", "Em execução")
    assert _mesma_situacao("Prestação de  Contas", "prestação de contas")
    # `�` é o que o portal solta no lugar de acento corrompido
    assert _mesma_situacao("Em execu��o", "Em execuo")
    assert not _mesma_situacao(A, B)      # estes DOIS são estados diferentes


def test_o_teto_e_aplicado_DEPOIS_de_consolidar():
    """⚠️ Cortar antes truncaria um grupo pela metade e inventaria uma mudança
    líquida que não existe — ficaria só a metade nova de uma ida-e-volta."""
    itens = []
    for i in range(60):
        itens.append(_m(i, "X", "Y", f"2026-08-25T{i % 24:02d}:00", ref=f"{i}/2025"))
    assert len(consolidar_por_ref(itens, limite=40)) == 40


def test_lista_vazia_devolve_vazia():
    assert consolidar_por_ref([]) == []

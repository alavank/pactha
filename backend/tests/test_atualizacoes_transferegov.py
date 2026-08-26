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
    assert '"dias"] = _DIAS_ATUALIZACOES' in fonte
    assert "_DIAS_ATUALIZACOES" in fonte
    assert "FONTE_VOLUNTARIAS" in fonte


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

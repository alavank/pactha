"""A FICHA do programa no radar de captação (18/09/2026).

O clique num programa abre: prazos, situação do município (indicado? propôs?),
concorrência na edição aberta, edições anteriores, exemplos aprovados e quem
indica na UF. Tudo de dump aberto do TransfereGov.

⚠️ O QUE ESTE ARQUIVO IMPEDE:
- "edição anterior" casar programa de outro órgão, ou virar a chave por ação
  orçamentária (que junta Água, Mobilidade e Drenagem numa só);
- "Proposta Aprovada e Plano de Trabalho em Análise" contar como não aprovada;
- proposta de estado/OSC entrar como concorrência de prefeitura;
- CPF de pessoa física do arquivo de apoiadores chegar ao banco;
- arquivo ilegível trocar a ficha boa por "ninguém propôs";
- a rota `/{id_programa}` engolir `/contagem`.

Rodar: python -m pytest backend/tests/test_radar_ficha.py -q
"""
import re
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("psycopg2")

from ingestion import programas_captacao as P  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
MUN = "Administração Pública Municipal"


def _prog(pid, nome, orgao="54000", ano="2025", uf="RS"):
    return {"ID_PROGRAMA": pid, "NOME_PROGRAMA": nome, "COD_ORGAO_SUP_PROGRAMA": orgao,
            "ANO_DISPONIBILIZACAO": ano, "UF_PROGRAMA": uf}


def _proposta(ip, **kw):
    base = {"ID_PROPOSTA": ip, "NATUREZA_JURIDICA": MUN,
            "SIT_PROPOSTA": "Proposta/Plano de Trabalho Aprovados", "UF_PROPONENTE": "RS",
            "COD_MUNIC_IBGE": "4316907", "IDENTIF_PROPONENTE": "88488366000100",
            "NM_PROPONENTE": "MUNICIPIO DE SANTA MARIA", "NR_PROPOSTA": "28950/2026",
            "ANO_PROP": "2026", "DIA_PROPOSTA": "22/06/2026", "VL_GLOBAL_PROP": "1933000",
            "VL_REPASSE_PROP": "1913875", "VL_CONTRAPARTIDA_PROP": "19125",
            "OBJETO_PROPOSTA": "Pavimentação da Rua Vermelha"}
    base.update(kw)
    return base


def _apoio(pid="56140", cnpj="88488366000100", **kw):
    base = {"ID_CNPJ_PROGRAMA_EMENDA_APOIADORES_EMENDAS": "1",
            "NUMERO_EMENDA_APOIADORES_EMENDAS": "50070001",
            "NOME_PARLAMENTAR_APOIADORES_EMENDAS": "Com. Turismo",
            "INDICACAO_APOIADORES_EMENDAS": "INDIVIDUAL",
            "PARLAMENTAR_SOLICITANTE_APOIADORES_EMENDAS": "Fulano de Tal",
            "CPF_PF_SOLICITANTE_APOIADORES_EMENDAS": "***123456**",
            "NOME_PF_SOLICITANTE_APOIADORES_EMENDAS": "PESSOA FISICA",
            "CNPJ_PJ_SOLICITANTE_APOIADORES_EMENDAS": "", "NOME_PJ_SOLICITANTE_APOIADORES_EMENDAS": "",
            "CNPJ_PROPONENTE_APOIADORES_EMENDAS": cnpj,
            "NOME_PROPONENTE_APOIADORES_EMENDAS": "MUNICIPIO DE SANTA MARIA",
            "VALOR_REPASSE_PROPOSTA_APOIADORES_EMENDAS": "4350523", "ID_PROGRAMA": pid}
    base.update(kw)
    return base


# ------------------------------------------------------- edições anteriores ---

def test_nome_chave_ignora_ano_acento_e_pontuacao():
    assert (P.nome_chave("Novo PAC - Mobilidade Urbana Sustentável 2025")
            == P.nome_chave("NOVO PAC – MOBILIDADE URBANA SUSTENTAVEL (2026)"))
    # "Programa 2319" não é ano: número de programa fica.
    assert "2319" in P.nome_chave("Programa 2319 - Ação 00T3")


def test_edicao_anterior_e_mesmo_orgao_e_mesmo_nome():
    abertos = {"56448": ("56000", "Novo PAC - Mobilidade Urbana Sustentável")}
    linhas = [
        _prog("40001", "Novo PAC - Mobilidade Urbana Sustentável", "56000", "2024", "RS"),
        _prog("40001", "Novo PAC - Mobilidade Urbana Sustentável", "56000", "2024", "MG"),
        _prog("40002", "Novo PAC - Mobilidade Urbana Sustentável", "56000", "2025"),
        # outro órgão com o mesmo nome: NÃO é edição
        _prog("40003", "Novo PAC - Mobilidade Urbana Sustentável", "53000", "2025"),
        # mesma ação orçamentária, nome diferente: NÃO é edição
        _prog("40004", "Novo PAC - Abastecimento de Água - FIN", "56000", "2025"),
        _prog("56448", "Novo PAC - Mobilidade Urbana Sustentável", "56000", "2026"),
    ]
    ed = P.edicoes_anteriores(abertos, linhas)
    assert [e["id"] for e in ed["56448"]] == ["40002", "40001"], "mais recente primeiro, sem repetir UF"
    assert ed["56448"][0] == {"id": "40002", "ano": 2025,
                              "nome": "Novo PAC - Mobilidade Urbana Sustentável"}


def test_todo_aberto_sai_no_resultado_mesmo_sem_edicao():
    """Lista vazia é "olhamos e não há"; ausência da chave seria "não olhamos"."""
    ed = P.edicoes_anteriores({"1": ("x", "Programa Novo"), "2": ("x", "Outro")},
                              [_prog("9", "Sem relação", "x")])
    assert ed == {"1": [], "2": []}


def test_outro_programa_aberto_nao_vira_edicao_anterior():
    """Dois abertos com o mesmo nome (Ação 00SX sai duas vezes) não são edição
    um do outro — cada um é uma porta própria."""
    abertos = {"55990": ("54000", "Ação 00SX"), "56567": ("54000", "Ação 00SX")}
    ed = P.edicoes_anteriores(abertos, [_prog("55990", "Ação 00SX"), _prog("56567", "Ação 00SX")])
    assert ed == {"55990": [], "56567": []}


def test_edicoes_com_cabecalho_mudado_devolve_None():
    assert P.edicoes_anteriores({"1": ("x", "y")}, [{"ID_PROG": "1"}]) is None


# ------------------------------------------------------------------- fase ---

@pytest.mark.parametrize("sit,esperado", [
    ("Proposta/Plano de Trabalho Aprovados", "aprovada"),
    ("Proposta Aprovada e Plano de Trabalho em Análise", "aprovada"),
    ("Proposta Aprovada/Aguardando Plano de Trabalho", "aprovada"),
    ("Proposta/Plano de Trabalho Rejeitados", "rejeitada"),
    ("Proposta/Plano de Trabalho Rejeitados por Impedimento técnico", "rejeitada"),
    ("Proposta Eliminada em Chamamento Público", "rejeitada"),
    ("Proposta/Plano de Trabalho Enviado para Análise", "andamento"),
    ("Proposta/Plano de Trabalho Cadastrados", "andamento"),
    ("Proposta/Plano de Trabalho em Complementação", "andamento"),
    ("", "andamento"),
])
def test_fase(sit, esperado):
    assert P.fase(sit) == esperado


# --------------------------------------------------------------- propostas ---

def test_so_proposta_de_prefeitura_e_uma_linha_por_programa():
    ligadas = {"1": {"56140"}, "2": {"56140"}, "3": {"56140", "40002"}}
    linhas = [_proposta("1"),
              _proposta("2", NATUREZA_JURIDICA="Administração Pública Estadual ou do Distrito Federal"),
              _proposta("3", SIT_PROPOSTA="Proposta/Plano de Trabalho Rejeitados"),
              _proposta("99")]
    rows = P.propostas_de_prefeitura(linhas, ligadas)
    assert sorted((r[0], r[1]) for r in rows) == [("40002", "3"), ("56140", "1"), ("56140", "3")]
    r = next(r for r in rows if r[1] == "1")
    assert r[2] == 2026 and r[3] == date(2026, 6, 22)
    assert r[4:8] == ("RS", "4316907", "88488366000100", "MUNICIPIO DE SANTA MARIA")
    assert r[10] == "aprovada" and r[12] == 1913875.0


def test_objeto_longo_e_cortado():
    rows = P.propostas_de_prefeitura([_proposta("1", OBJETO_PROPOSTA="x" * 5000)], {"1": {"a"}})
    assert len(rows[0][-1]) == P.OBJETO_MAX


def test_propostas_com_coluna_renomeada_devolve_None():
    linha = _proposta("1")
    linha["VL_REPASSE"] = linha.pop("VL_REPASSE_PROP")
    assert P.propostas_de_prefeitura([linha], {"1": {"a"}}) is None


def test_ligar_propostas():
    linhas = [{"ID_PROGRAMA": "a", "ID_PROPOSTA": "1"}, {"ID_PROGRAMA": "b", "ID_PROPOSTA": "1"},
              {"ID_PROGRAMA": "z", "ID_PROPOSTA": "2"}]
    assert P.ligar_propostas(linhas, {"a", "b"}) == {"1": {"a", "b"}}
    assert P.ligar_propostas([{"PROGRAMA": "a"}], {"a"}) is None


# -------------------------------------------------------------- apoiadores ---

def test_apoiadores_so_dos_abertos_e_sem_CPF():
    ap = P.apoiadores_dos_abertos([_apoio("56140"), _apoio("11111")], {"56140"})
    assert len(ap) == 1
    a = ap[0]
    assert a["parlamentar"] == "Com. Turismo" and a["solicitante"] == "Fulano de Tal"
    assert a["cnpj"] == "88488366000100" and a["valor"] == 4350523.0
    assert not any("cpf" in k.lower() or k == "nome_pf" for k in a), "CPF chegou ao registro"
    assert "123456" not in repr(ap) and "PESSOA FISICA" not in repr(ap)


def test_o_CPF_nao_e_lido_nem_gravado():
    """⚠️ LGPD: o arquivo publica CPF de pessoa física. O que não se lê não vaza."""
    assert not any("CPF" in c for c in P.COLUNAS_APOIADORES)
    mig = (RAIZ / "migrations" / "add_programas_captacao_ficha.sql").read_text(encoding="utf-8")
    ddl = "\n".join(l for l in mig.splitlines() if not l.strip().startswith("--"))
    assert "cpf" not in ddl.lower()


def test_apoiadores_com_cabecalho_mudado_devolve_None():
    linha = _apoio()
    del linha["NOME_PARLAMENTAR_APOIADORES_EMENDAS"]
    assert P.apoiadores_dos_abertos([linha], {"56140"}) is None


def test_ufs_por_cnpj():
    linhas = [{"IDENTIF_PROPONENTE": "88488366000100", "UF_PROPONENTE": "rs"},
              {"IDENTIF_PROPONENTE": "11111111000111", "UF_PROPONENTE": "MG"}]
    assert P.ufs_por_cnpj(linhas, {"88488366000100"}) == {"88488366000100": "RS"}


# ---------------------------------------------------------------- montagem ---

class _Cursor:
    def __init__(self, idade=None, abertos=(("56140", "54000", "Infraestrutura Turística"),),
                 apoiadores_antes=0):
        self.execs, self.many = [], []
        self._idade, self._abertos, self._antes = idade, list(abertos), apoiadores_antes
        self._ultimo = ""

    def execute(self, sql, params=None):
        self.execs.append((sql, params))
        self._ultimo = sql

    def executemany(self, sql, seq):
        self.many.append((sql, list(seq)))

    def fetchone(self):
        if "ficha_em" in self._ultimo:
            return (self._idade,)
        if "count(*)" in self._ultimo:
            return (self._antes,)
        return (0,)

    def fetchall(self):
        return self._abertos

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self._c, self.commits = cur, 0

    def cursor(self):
        return self._c

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _montar(monkeypatch, arquivos, **kw):
    cur = _Cursor(**kw)
    inseridos = {}
    monkeypatch.setattr(P, "_linhas", lambda nome: iter(arquivos[nome]))
    monkeypatch.setattr(P.psycopg2, "connect", lambda _d: _Conn(cur))
    monkeypatch.setattr(P, "execute_values",
                        lambda c, sql, linhas, page_size=100: inseridos.setdefault(
                            sql.split()[2], list(linhas)))
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://x/y")
    status = P.ficha()
    log = next((p for s, p in cur.execs if "ingestion_log" in s), None)
    deletes = [s for s, _ in cur.execs if s.startswith("DELETE")]
    return status, log, deletes, inseridos, cur


def _arquivos_bons():
    return {
        P.ARQUIVO: [_prog("56140", "Infraestrutura Turística", "54000", "2026"),
                    _prog("40002", "Infraestrutura Turística", "54000", "2025")],
        P.ARQUIVO_PROGRAMA_PROPOSTA: [{"ID_PROGRAMA": "56140", "ID_PROPOSTA": "1"},
                                      {"ID_PROGRAMA": "40002", "ID_PROPOSTA": "2"}],
        P.ARQUIVO_PROPOSTA: [_proposta("1"), _proposta("2", ANO_PROP="2025")],
        P.ARQUIVO_APOIADORES: [_apoio("56140")],
        P.ARQUIVO_PROPONENTES: [{"IDENTIF_PROPONENTE": "88488366000100", "UF_PROPONENTE": "RS"}],
    }


def test_ficha_fresca_nao_remonta(monkeypatch):
    status, log, deletes, _, _ = _montar(monkeypatch, _arquivos_bons(), idade=3.0)
    assert status is None and log is None and not deletes


def test_ficha_monta_troca_as_tabelas_e_sai_success(monkeypatch):
    status, log, deletes, ins, cur = _montar(monkeypatch, _arquivos_bons())
    assert status == "success" and log[0] == P.FONTE_FICHA and log[1] == "success"
    assert log[2] == 2
    assert deletes == ["DELETE FROM programas_captacao_propostas",
                       "DELETE FROM programas_captacao_apoiadores"]
    assert len(ins["programas_captacao_propostas"]) == 2
    uf = P._COLS_APOIADORES.replace(" ", "").split(",").index("uf")
    assert ins["programas_captacao_apoiadores"][0][uf] == "RS"
    upd = cur.many[0]
    assert "ficha_em = NOW()" in upd[0]
    assert upd[1] == [('[{"id": "40002", "ano": 2025, "nome": "Infraestrutura Turística"}]', "56140")]


def test_programa_novo_sem_ficha_remonta_antes_das_20h(monkeypatch):
    """`idade` NULL = algum programa ativo sem ficha: monta sem esperar."""
    status, *_ = _montar(monkeypatch, _arquivos_bons(), idade=None)
    assert status == "success"


def test_propostas_ilegiveis_NAO_apagam_a_ficha_anterior(monkeypatch):
    """⚠️ O CASO QUE FARIA TODA FICHA DIZER "NINGUÉM PROPÔS"."""
    arq = _arquivos_bons()
    arq[P.ARQUIVO_PROPOSTA] = [{"COLUNA_NOVA": "x"}]
    status, log, deletes, _, cur = _montar(monkeypatch, arq)
    assert status == "error" and log[1] == "error"
    assert "DELETE FROM programas_captacao_propostas" not in deletes
    assert not cur.many, "ficha_em avançou sem proposta lida"


def test_zero_proposta_tambem_nao_troca(monkeypatch):
    arq = _arquivos_bons()
    arq[P.ARQUIVO_PROPOSTA] = [_proposta("1", NATUREZA_JURIDICA="Organização da Sociedade Civil")]
    status, _, deletes, _, _ = _montar(monkeypatch, arq)
    assert status == "error" and "DELETE FROM programas_captacao_propostas" not in deletes


def test_apoiadores_ilegiveis_mantem_os_anteriores_e_sai_partial(monkeypatch):
    arq = _arquivos_bons()
    arq[P.ARQUIVO_APOIADORES] = [{"OUTRA": "x"}]
    status, log, deletes, _, _ = _montar(monkeypatch, arq)
    assert status == "partial" and "apoiadores" in log[3]
    assert deletes == ["DELETE FROM programas_captacao_propostas"]


def test_zero_apoiador_com_tabela_cheia_mantem_a_anterior(monkeypatch):
    arq = _arquivos_bons()
    arq[P.ARQUIVO_APOIADORES] = [_apoio("fechado")]
    status, _, deletes, _, _ = _montar(monkeypatch, arq, apoiadores_antes=5311)
    assert status == "partial"
    assert "DELETE FROM programas_captacao_apoiadores" not in deletes


def test_ingest_so_monta_ficha_com_lista_e_sobrevive_a_falha_dela(monkeypatch):
    chamadas = []
    monkeypatch.setattr(P, "run", lambda: 0)
    monkeypatch.setattr(P, "ficha", lambda: chamadas.append(1))
    assert P.ingest() == 0 and not chamadas

    def estoura():
        raise RuntimeError("zip ruim")
    monkeypatch.setattr(P, "run", lambda: 7)
    monkeypatch.setattr(P, "ficha", estoura)
    assert P.ingest() == 7


def test_o_upsert_da_ficha_e_sql_valido():
    pglast = pytest.importorskip("pglast")
    pglast.parse_sql(P._SQL_IDADE_FICHA)
    pglast.parse_sql(f"INSERT INTO t ({P._COLS_PROPOSTAS}) VALUES (1)")


# ------------------------------------------------------------------- rota ---

def _router():
    return (RAIZ / "routers" / "programas_captacao.py").read_text(encoding="utf-8")


def test_a_ficha_e_declarada_depois_da_contagem():
    """⚠️ `/{id_programa}` antes de `/contagem` engoliria "contagem" como id."""
    from routers import programas_captacao as R
    caminhos = [r.path for r in R.router.routes]
    assert caminhos.index("/api/programas-captacao/contagem") < caminhos.index(
        "/api/programas-captacao/{id_programa}")


def test_a_ficha_passa_pelo_MESMO_filtro_da_lista():
    rota = _router()
    corpo = rota[rota.index("async def ficha"):]
    assert "_CTE_ABERTOS + _SELECT_FICHA + _FILTRO_ABERTOS" in corpo
    assert 'exige("transferegov_radar.ver")' in rota[rota.index('@router.get("/{id_programa}"'):]


def test_sem_ficha_montada_a_rota_nao_responde_zero():
    """`ficha_em` NULL devolve SÓ o programa — nunca contagem zerada."""
    rota = _router()
    corpo = rota[rota.index("async def ficha"):]
    antes = corpo[:corpo.index('if p["ficha_em"] is None:')]
    assert "programas_captacao_propostas" not in antes
    assert corpo.index('if p["ficha_em"] is None:') < corpo.index("_CONTA_FASES")


def test_proposta_do_municipio_e_por_IBGE_e_indicacao_por_CNPJ():
    rota = _router()
    corpo = rota[rota.index("async def ficha"):]
    assert "AND ibge = :ibge" in corpo
    assert "AND cnpj = :cnpj" in corpo
    assert "proponente ILIKE" not in corpo and "NM_PROPONENTE" not in corpo


def test_as_consultas_da_ficha_sao_sql_valido():
    pglast = pytest.importorskip("pglast")
    rota = _router()
    corpo = rota[rota.index("_SELECT_FICHA = "):]
    blocos = re.findall(r'"""(.*?)"""', corpo, re.S)
    sqls = [b for b in blocos if "SELECT" in b and "FROM" in b]
    assert len(sqls) >= 6
    for sql in sqls:
        if sql.lstrip().startswith("SELECT id_programa, nome"):
            continue  # pedaço da CTE, validado montado abaixo
        pglast.parse_sql(re.sub(r"(?<!:):(\w+)", r"'\1'", sql))
    from routers import programas_captacao as R
    montado = R._CTE_ABERTOS + R._SELECT_FICHA + R._FILTRO_ABERTOS + "  AND id_programa = :id\n"
    pglast.parse_sql(re.sub(r"(?<!:):(\w+)", r"'\1'", montado))


def test_a_tela_nao_chama_repasse_de_valor_do_programa():
    tela = (RAIZ.parent / "frontend" / "src" / "app" / "dashboard" / "transferegov-radar"
            / "FichaPrograma.tsx").read_text(encoding="utf-8")
    # Só o que vai para a tela: os comentários citam a expressão para proibi-la.
    codigo = re.sub(r"/\*.*?\*/|//[^\n]*", "", tela, flags=re.S).lower()
    assert "repasse mediano das aprovadas" in codigo
    assert "valor do programa" not in codigo

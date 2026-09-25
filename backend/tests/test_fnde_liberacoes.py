"""Liberações do FNDE pela consulta `pls/simad` (`ingestion/fnde_liberacoes.py`).

As fixtures são páginas REAIS baixadas em 24/09/2026 (fechamento do FNDE de
23/09/2026) para Monte Sião/MG: a lista de entidades de 2026 (16: 14 caixas
escolares, a prefeitura e a Secretaria de Educação) e as liberações de quatro
delas — a prefeitura, a secretaria e duas caixas que dividem a MESMA OB.

O que se prova:
- o parser lê a lista e as liberações, e confere a soma com a linha "Total:";
- o salário-educação que o SIMEC escondia (R$ 1.168.706,81 na Secretaria) e o
  PNAE de agosto que a CGU mostra (R$ 33.765,50);
- quem recebeu e o que soma no município (a mesma regra da CGU);
- a chave com CNPJ é necessária (a mesma OB paga duas caixas) e suficiente;
- falha nunca vira ausência (lista ignorando o filtro, entidade vazia);
- todo leitor que soma `simec_par_liberacoes` filtra o que é do município.
"""
import ast
import pathlib
import re
from collections import Counter
from datetime import date

import pglast
import pytest

from ingestion import fnde_liberacoes as fl
from ingestion import simec_par
from services import liberacoes_fnde as lf

FIX = pathlib.Path(__file__).parent / "fixtures" / "fnde_simad"
BACKEND = pathlib.Path(__file__).resolve().parents[1]

PREF = "22646525000131"
SEC = "61994863000116"
CX1 = "28545919000180"   # CAIXA ESCOLAR CANTINHO DA FELICIDADE
CX2 = "34330971000111"   # CAIXA ESCOLAR ELVIRA DE CASTRO BERNARDI
PAGINAS = {
    PREF: "entidade_prefeitura_monte_siao_2026.html",
    SEC: "entidade_secretaria_monte_siao_2026.html",
    CX1: "entidade_caixa_escolar_monte_siao_2026.html",
    CX2: "entidade_caixa_escolar_elvira_monte_siao_2026.html",
}
MONTE_SIAO = {"id": 1, "nome": "Monte Sião", "uf": "MG", "ibge": "3143401", "cnpj": PREF}


def _html(nome: str) -> str:
    return fl._decodifica((FIX / nome).read_bytes())


def _entidade(cnpj: str) -> dict:
    return fl.parse_entidade(_html(PAGINAS[cnpj]))


class SimadFalso:
    """O simad servido pelas fixtures. Entidade sem fixture responde a página
    real de "Não foram encontrados dados"."""

    def __init__(self, lista="lista_monte_siao_2026.html"):
        self.lista_html = _html(lista)
        self.falhas_seguidas = 0
        self.pedidos = []

    def lista(self, ano, uf, ibge6):
        self.pedidos.append(("lista", ano, ibge6))
        return self.lista_html

    def entidade(self, ano, cnpj):
        self.pedidos.append(("entidade", ano, cnpj))
        return _html(PAGINAS.get(cnpj, "sem_dados.html"))


# ------------------------------------------------------------------ lista ---

def test_lista_traz_as_16_entidades_com_o_fechamento():
    lista = fl.parse_lista(_html("lista_monte_siao_2026.html"), "314340")
    assert lista["estado"] == "ok"
    assert lista["fechamento"] == date(2026, 9, 23)
    nomes = {e["cnpj"]: e["nome"] for e in lista["entidades"]}
    assert len(nomes) == 16
    assert nomes[PREF] == "PREF MUN DE MONTE SIAO"
    assert nomes[SEC] == "SECRETARIA MUNICIPAL DE EDUCACAO"
    assert sum(1 for n in nomes.values() if n.startswith("CAIXA ESCOLAR")) == 14


def test_lista_de_outro_municipio_e_recusada():
    """Cada linha carrega o município no onclick: se não for o pedido, o filtro
    foi ignorado — nunca gravar a lista de outro."""
    lista = fl.parse_lista(_html("lista_monte_siao_2026.html"), "431310")
    assert lista["estado"] == "invalido"
    assert "filtro" in lista["motivo"]


def test_sem_dados_e_vazio_e_nao_invalido():
    lista = fl.parse_lista(_html("sem_dados.html"), "999999")
    assert lista["estado"] == "vazio" and lista["entidades"] == []
    assert lista["fechamento"] == date(2026, 9, 24)   # baixada depois da meia-noite


def test_pagina_estranha_e_invalida():
    assert fl.parse_lista("<html><body>Erro Oracle ORA-01722</body></html>", "314340")["estado"] == "invalido"
    assert fl.parse_entidade("<html><body>ORA-06502</body></html>")["estado"] == "invalido"


# -------------------------------------------------------------- entidades ---

def test_salario_educacao_da_secretaria_que_o_simec_nao_via():
    e = _entidade(SEC)
    assert e["estado"] == "ok" and e["cnpj"] == SEC and not e["divergencias"]
    assert e["municipio"] == "MONTE SIAO - MG"
    assert {li["programa"] for li in e["liberacoes"]} == {"QUOTA"}
    assert len(e["liberacoes"]) == 7                           # mar a set/2026
    assert round(sum(li["valor"] for li in e["liberacoes"]), 2) == 1168706.81
    assert min(li["dt_pgto"] for li in e["liberacoes"]) == date(2026, 3, 19)


def test_prefeitura_bate_com_o_simec_e_com_a_cgu():
    e = _entidade(PREF)
    assert e["estado"] == "ok" and not e["divergencias"]
    por = Counter(li["programa"] for li in e["liberacoes"])
    assert por == {"ALIMENTAÇÃO ESCOLAR": 40, "PNATE": 3, "QUOTA": 2}   # = SIMEC
    quota = sum(li["valor"] for li in e["liberacoes"] if li["programa"] == "QUOTA")
    assert round(quota, 2) == 444050.84                                 # só jan+fev
    agosto = sum(li["valor"] for li in e["liberacoes"]
                 if li["programa"] == "ALIMENTAÇÃO ESCOLAR"
                 and date(2026, 8, 1) <= li["dt_pgto"] <= date(2026, 8, 31))
    assert round(agosto, 2) == 33765.50                                 # = CGU ago/2026


def test_mesmo_formato_de_linha_do_simec():
    """O simad e o SIMEC passam pelo MESMO parser de linha: o `programa` sai com
    a mesma grafia, e é isso que faz a chave de um casar com a do outro."""
    simec = simec_par.parse_relatorio(
        (pathlib.Path(__file__).parent / "fixtures" / "simec_par_monte_siao_2026-09-25.html")
        .read_bytes().decode("windows-1252", errors="replace"))["liberacoes"]
    simad = _entidade(PREF)["liberacoes"]
    chave = lambda li: (li["programa"], li["dt_pgto"], li["ob"], li["valor"])  # noqa: E731
    assert {chave(li) for li in simec} == {chave(li) for li in simad}


def test_soma_diferente_do_total_vira_divergencia():
    html = _html(PAGINAS[SEC])
    # some com a linha de 17/SET/2026 (174.958,38): a tabela ainda diz 1.168.706,81
    cortado = re.sub(r"<tr[^>]*>(?:(?!</tr>).)*17/SET/2026(?:(?!</tr>).)*</tr>", "", html,
                     count=1, flags=re.S | re.I)
    assert cortado != html
    e = fl.parse_entidade(cortado)
    assert len(e["liberacoes"]) == 6
    assert e["divergencias"] and "1168706.81" in e["divergencias"][0]


# ------------------------------------------------------ favorecido e soma ---

@pytest.mark.parametrize("cnpj,nome,esperado", [
    (PREF, "PREF MUN DE MONTE SIAO", "prefeitura"),
    ("00000000000191", "PREF MUN DE MONTE SIAO", "prefeitura"),        # outro CNPJ, mesmo ente
    (SEC, "SECRETARIA MUNICIPAL DE EDUCACAO", "secretaria"),
    ("29979768000130", "SEC MUN DE EDUC DE NOVA PALMA", "secretaria"),  # Nova Palma
    (CX1, "CAIXA ESCOLAR CANTINHO DA FELICIDADE", "escola"),
    ("89251474000110", "CIRCULO DE PAIS E MESTRES DA EE DE EF ANA LOB", "escola"),  # estadual!
    ("1", "APM  DA ESCOLA MUNICIPAL DE ENSINO FUNDAMENTAL SAO CARLOS", "escola"),
    ("2", "ASSOCIACAO DE PAIS E AMIGOS DOS EXCEPCIONAIS", "escola"),    # APAE: como a CGU
    ("3", "FUNDO MUNICIPAL DE EDUCACAO", "fundo"),
    ("4", "SECRETARIA DE ESTADO DE EDUCACAO", "outro_ente"),
])
def test_tipo_do_favorecido(cnpj, nome, esperado):
    assert lf.tipo_favorecido(cnpj, nome, PREF) == esperado


def test_prefeitura_pelo_nome_quando_o_tenant_nao_tem_cnpj():
    assert lf.tipo_favorecido(PREF, "PREF MUN DE MONTE SIAO", None) == "prefeitura"


def test_o_que_soma_no_municipio():
    assert lf.TIPOS_DO_MUNICIPIO == ("fundo", "orgao_municipal", "prefeitura", "secretaria")
    assert "tipo_favorecido IN ('fundo', 'orgao_municipal', 'prefeitura', 'secretaria')" == lf.SQL_DO_MUNICIPIO
    assert lf.do_municipio(None)                   # linha antiga do SIMEC = prefeitura
    assert not lf.do_municipio("escola")
    # a mesma regra da tela da CGU (Recursos recebidos por pasta)
    from services.transferencias_pasta import DO_MUNICIPIO
    assert set(lf.TIPOS_DO_MUNICIPIO) == set(DO_MUNICIPIO)


def test_coleta_do_ano_soma_prefeitura_e_secretaria_e_separa_as_escolas():
    simad = SimadFalso()
    res = fl.coleta_ano(simad, MONTE_SIAO, 2026)
    assert simad.pedidos[0] == ("lista", 2026, "314340")                # IBGE de 6 dígitos
    assert res["fechamento"] == date(2026, 9, 23) and len(res["entidades"]) == 16
    # 12 caixas sem fixture respondem "Não foram encontrados": a lista disse que
    # receberam, então é FALHA (ano incompleto), nunca "não receberam".
    assert len(res["erros"]) == 12
    libs = res["liberacoes"]
    mun = sum(li["valor"] for li in libs if lf.do_municipio(li["tipo_favorecido"]))
    esc = sum(li["valor"] for li in libs if not lf.do_municipio(li["tipo_favorecido"]))
    assert round(mun, 2) == round(538820.00 + 10344.19 + 444050.84 + 1168706.81, 2)
    assert round(esc, 2) == 8470.00 + 4970.00
    fav = {li["cnpj_favorecido"]: (li["favorecido"], li["tipo_favorecido"]) for li in libs}
    assert fav[SEC] == ("SECRETARIA MUNICIPAL DE EDUCACAO", "secretaria")
    assert fav[CX2] == ("CAIXA ESCOLAR ELVIRA DE CASTRO BERNARDI", "escola")


def test_a_chave_precisa_do_cnpj_e_basta_com_ele():
    """A OB 007948 de 30/04/2026 paga as duas caixas: sem o CNPJ na chave, a
    segunda sobrescreveria a primeira. Com ele, nenhuma chave repete — e duas
    coletas dão exatamente as mesmas chaves (upsert idempotente)."""
    a = fl.coleta_ano(SimadFalso(), MONTE_SIAO, 2026)["liberacoes"]
    antiga = Counter((li["programa"], li["dt_pgto"], li["ob"]) for li in a)
    assert antiga[("PDDE", date(2026, 4, 30), "007948")] == 2
    nova = [(li["cnpj_favorecido"], li["programa"], li["dt_pgto"], li["ob"]) for li in a]
    assert len(nova) == len(set(nova))
    b = fl.coleta_ano(SimadFalso(), MONTE_SIAO, 2026)["liberacoes"]
    assert sorted(nova) == sorted((li["cnpj_favorecido"], li["programa"], li["dt_pgto"], li["ob"]) for li in b)


def test_lista_invalida_levanta_e_conta_para_o_disjuntor():
    simad = SimadFalso(lista="entidade_secretaria_monte_siao_2026.html")   # não é lista
    with pytest.raises(fl.FalhaSimad):
        fl.coleta_ano(simad, MONTE_SIAO, 2026)
    simad = SimadFalso()
    with pytest.raises(fl.FalhaSimad):
        fl.coleta_ano(simad, {**MONTE_SIAO, "ibge": "4313102"}, 2026)       # filtro "ignorado"
    assert simad.falhas_seguidas == 1


def test_status_da_rodada():
    assert fl.status_da_rodada(2, 0, []) == ("success", None)
    st, nota = fl.status_da_rodada(2, 1, ["Nova Palma: ano corrente pelo SIMEC (plano B)"])
    assert st == "partial" and "plano B" in nota
    assert fl.status_da_rodada(2, 2, ["x", "y"])[0] == "error"


# --------------------------------------------------------------- gravação ---

class CursorFalso:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))


def test_grava_escreve_favorecido_e_marca_o_ano_incompleto():
    res = fl.coleta_ano(SimadFalso(), MONTE_SIAO, 2026)
    cur = CursorFalso()
    n = fl.grava(cur, 1, 2026, res)
    assert n == len(res["liberacoes"]) == 45 + 7 + 2 + 2
    ups = [p for s, p in cur.sql if "INSERT INTO simec_par_liberacoes" in s]
    assert {p["tipo_favorecido"] for p in ups} == {"prefeitura", "secretaria", "escola"}
    assert any("DELETE FROM simec_par_liberacoes" in s for s, _ in cur.sql)   # supera o SIMEC
    carga = [p for s, p in cur.sql if "fnde_liberacoes_carga" in s][0]
    assert carga["completo"] is False and carga["fechamento"] == date(2026, 9, 23)
    assert carga["n_entidades"] == 16 and "sem_dados" not in (carga["erro"] or "")


def test_grava_de_lista_que_falhou_nao_apaga_nada():
    cur = CursorFalso()
    assert fl.grava(cur, 1, 2026, None, "lista: HTTP 503") == 0
    assert not any("DELETE" in s for s, _ in cur.sql)
    carga = cur.sql[-1][1]
    assert carga["completo"] is False and carga["erro"] == "lista: HTTP 503"


@pytest.mark.parametrize("sql", [fl._SQL_UPSERT, fl._SQL_SUPERA_SIMEC, fl._SQL_CARGA,
                                 simec_par._SQL_LIB_RESERVA])
def test_sql_dos_coletores_e_postgres_valido(sql):
    pglast.parse_sql(re.sub(r"%\((\w+)\)s", r"'\1'", sql))


def test_upserts_miram_a_chave_nova():
    alvo = "ON CONFLICT (municipio_id, cnpj_favorecido, programa, dt_pgto, ob)"
    assert alvo in fl._SQL_UPSERT and alvo in simec_par._SQL_LIB_RESERVA
    mig = (BACKEND / "migrations" / "add_fnde_liberacoes_favorecido.sql").read_text(encoding="utf-8")
    assert "(municipio_id, cnpj_favorecido, programa, dt_pgto, ob)" in mig
    # o plano B nunca escreve por cima do simad
    assert "WHERE simec_par_liberacoes.fonte = 'simec'" in simec_par._SQL_LIB_RESERVA


def test_migration_registrada_antes_da_auditoria():
    from services.startup import MIGRATION_FILES
    i = MIGRATION_FILES.index("add_fnde_liberacoes_favorecido.sql")
    # ACIMA da auditoria (que é sempre a última) — "logo acima" quebraria com a
    # próxima migration nova (`add_pdde_info.sql`, 25/09/2026, entrou entre as duas).
    assert i < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
    assert MIGRATION_FILES[-1] == "add_auditoria_imutavel.sql"
    assert MIGRATION_FILES.index("add_simec_par.sql") < i
    assert MIGRATION_FILES.index("add_municipio_identificadores.sql") < i


# ------------------------------------------------------------- os leitores ---

def _consultas_que_leem_a_tabela():
    """(arquivo, linha, texto do SQL) de toda string que lê `simec_par_liberacoes`
    em routers/ e services/ (os coletores escrevem; não entram)."""
    for pasta in ("routers", "services"):
        for arq in sorted((BACKEND / pasta).glob("*.py")):
            fonte = arq.read_text(encoding="utf-8")
            if "simec_par_liberacoes" not in fonte:
                continue
            arvore = ast.parse(fonte)
            # os pedaços literais de um f-string são Constants também: sem isto o
            # pedaço "... FROM simec_par_liberacoes WHERE " seria julgado sozinho,
            # sem o `{SQL_DO_MUNICIPIO}` que vem logo depois.
            dentro_de_fstring = {id(v) for n in ast.walk(arvore) if isinstance(n, ast.JoinedStr)
                                 for v in n.values}
            for no in ast.walk(arvore):
                if id(no) in dentro_de_fstring:
                    continue
                if isinstance(no, ast.JoinedStr):
                    txt = ast.get_source_segment(fonte, no) or ""
                elif isinstance(no, ast.Constant) and isinstance(no.value, str):
                    txt = no.value
                else:
                    continue
                if re.search(r"FROM\s+simec_par_liberacoes", txt):
                    yield arq.name, no.lineno, txt


def test_toda_consulta_que_soma_filtra_o_que_e_do_municipio():
    """O PDDE das caixas escolares (escola que pode ser ESTADUAL) está na mesma
    tabela desde 24/09/2026. Consulta nova que lê a tabela sem saber disso
    somaria dinheiro que não é da prefeitura. Toda leitura ou filtra
    (`SQL_DO_MUNICIPIO`) ou devolve o tipo para quem soma decidir."""
    achadas = list(_consultas_que_leem_a_tabela())
    assert len(achadas) >= 6, achadas            # simec (4), ai (2), rm (1)
    sem = [(a, ln) for a, ln, txt in achadas
           if "SQL_DO_MUNICIPIO" not in txt and "tipo_favorecido" not in txt]
    assert not sem, f"consulta a simec_par_liberacoes sem o filtro do município: {sem}"

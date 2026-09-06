"""
As guardas do schema de emendas federais — e uma delas não existe para nenhuma
outra fonte deste repo.

Três coisas são cravadas aqui:

  1. **O NOME NÃO ESTÁ MINADO.** `drop_lean_tables.sql` derruba `emendas`,
     `convenios_federal`, `emendas_camara`, `sancoes_ceis`, `programas_federais`
     e `oportunidades` a CADA BOOT, nos cinco tenants — e continua registrada em
     `MIGRATION_FILES`. O dia em que alguém acrescentar `emendas_federais%` lá, o
     sintoma seria "a tabela esvaziou sozinha" e ninguém iria olhar para um
     arquivo de 2026-05.

  2. **A ORDEM.** Acima está `drop_lean_tables`; abaixo,
     `add_auditoria_imutavel`, que é sempre a última.

  3. ⭐ **COLETOR → MIGRATION.** Toda coluna que o `INSERT` do coletor menciona
     existe no `CREATE TABLE`. `test_migrations_colunas_existem.py` cobre
     migration→migration; **coletor→migration não tem rede nenhuma hoje**, e é
     onde o erro é mais provável — o coletor é editado com muito mais frequência
     que o SQL, e o sintoma de uma coluna a mais é a rodada inteira estourando
     em produção, de madrugada, com o boot saudável.

Rodar:
    python -m pytest backend/tests/test_emendas_federais_migration.py -v
"""
import re
from pathlib import Path

import pglast
import pytest

from services.startup import MIGRATION_FILES

_MIGR = Path(__file__).resolve().parents[1] / "migrations"
_ARQUIVO = "add_emendas_federais.sql"
_SQL = (_MIGR / _ARQUIVO).read_text(encoding="utf-8")
_DROP = (_MIGR / "drop_lean_tables.sql").read_text(encoding="utf-8")

_TABELAS = ("emendas_federais_carteira", "emendas_federais_cgu",
            "emendas_federais_documentos", "emendas_federais_consulta")


def _sem_comentarios(sql: str) -> str:
    """Os comentários citam nome de tabela em prosa — e é justamente sobre
    prosa que as regexes abaixo dariam falso positivo."""
    return "\n".join(l for l in sql.splitlines()
                     if not l.strip().startswith("--"))


def test_o_sql_e_gramaticalmente_valido():
    """`pglast` valida contra a gramática real do Postgres, sem banco. ⚠️ Ele
    valida GRAMÁTICA: nome de coluna inexistente é SQL perfeitamente válido, e é
    por isso que os testes abaixo existem."""
    comandos = pglast.parse_sql(_SQL)
    assert len(comandos) == 14, "4 CREATE TABLE + 10 índices"


def test_as_quatro_tabelas_sao_criadas_de_forma_idempotente():
    """Roda em todo boot, nos cinco bancos. Sem `IF NOT EXISTS` a segunda
    execução falharia — e migration que falha NÃO derruba o boot, então o
    sintoma seria silêncio."""
    corpo = _sem_comentarios(_SQL)
    for t in _TABELAS:
        assert f"CREATE TABLE IF NOT EXISTS {t}" in corpo, t
    assert "DROP TABLE" not in corpo.upper()
    assert "ALTER TABLE" not in corpo.upper()


def test_nenhum_nome_novo_esta_na_lista_de_drop():
    """⚠️⚠️ A ARMADILHA NOMEADA. `drop_lean_tables.sql` continua em
    `MIGRATION_FILES`, ACIMA desta migration, e derruba a cada boot tudo o que
    seu cabeçalho chama de "federal/transferegov/portal-transparencia"."""
    for t in _TABELAS:
        assert not re.search(rf"DROP TABLE IF EXISTS\s+{t}\b", _DROP, re.I), (
            f"{t} entrou na lista de DROP — a tabela esvaziaria a cada deploy")


def test_a_deteccao_realmente_enxerga_a_lista_de_drop():
    """⭐ O TESTE DA FERRAMENTA. Se a regex do teste acima não casasse nada, ele
    passaria para sempre e diria que os nomes estão seguros — o modo de falha
    exato que ele existe para impedir. `emendas` (sem sufixo) ESTÁ lá."""
    assert re.search(r"DROP TABLE IF EXISTS\s+emendas\b", _DROP, re.I), (
        "a lista de DROP mudou de forma; as regexes deste arquivo pararam de "
        "guardar e precisam ser reescritas")
    assert re.search(r"DROP TABLE IF EXISTS\s+convenios_federal\b", _DROP, re.I)


def test_a_migration_esta_registrada_na_ordem_certa():
    """Migration fora de `MIGRATION_FILES` é órfã e nunca roda — foi assim que
    `add_siconv_federal.sql` deixou `routers/transferegov.py` devolvendo 500 num
    tenant novo (`startup.py:221-227`)."""
    assert _ARQUIVO in MIGRATION_FILES
    i = MIGRATION_FILES.index(_ARQUIVO)
    assert i > MIGRATION_FILES.index("drop_lean_tables.sql")
    assert i < MIGRATION_FILES.index("add_auditoria_imutavel.sql"), (
        "add_auditoria_imutavel é sempre a ÚLTIMA: ela instala o gatilho "
        "append-only do audit_log")


def test_as_colunas_da_chave_natural_sao_not_null():
    """⚠️ No Postgres NULL nunca colide com NULL num índice único. Com
    `nr_emenda` nulo o `ON CONFLICT` jamais casaria e cada rodada inseriria de
    novo as 7.059 linhas que vêm sem número: a tabela cresceria, ninguém
    perceberia, e a tela duplicaria."""
    corpo = _sem_comentarios(_SQL)
    for col in ("id_proposta", "cod_programa_emenda", "nr_emenda",
                "beneficiario_cnpj"):
        m = re.search(rf"^\s*{col}\s+VARCHAR\(\d+\)\s+NOT NULL DEFAULT ''",
                      corpo, re.I | re.M)
        assert m, f"{col} precisa ser NOT NULL DEFAULT '' (entra no índice único)"


def test_o_agregado_da_cgu_nao_tem_municipio_id():
    """⚠️⚠️ A GUARDA MAIS IMPORTANTE DO SCHEMA. `/emendas?codigoEmenda=` devolve
    o agregado da emenda INTEIRA, não a fatia do município: uma emenda de
    bancada de R$ 30 mi que passou por Nova Palma com R$ 250 mil traria R$ 30 mi.

    Sem a coluna, o `SUM(valor_pago) GROUP BY municipio_id` que produziria esse
    número é impossível de escrever por acidente. Vale igual para os documentos:
    o documento é da emenda, e uma emenda atende vários municípios."""
    corpo = _sem_comentarios(_SQL)
    for tabela in ("emendas_federais_cgu", "emendas_federais_documentos"):
        bloco = re.search(rf"CREATE TABLE IF NOT EXISTS {tabela}\s*\((.*?)^\);",
                          corpo, re.S | re.M)
        assert bloco, tabela
        assert "municipio_id" not in bloco.group(1), (
            f"{tabela} não pode ter municipio_id — o dado dela é NACIONAL")


def test_a_carteira_tem_municipio_id_e_a_deteccao_funciona():
    """⭐ O par do teste acima: se a regex de bloco não casasse, o anterior
    passaria vazio. A carteira TEM `municipio_id` — ela é o fato nosso."""
    corpo = _sem_comentarios(_SQL)
    bloco = re.search(
        r"CREATE TABLE IF NOT EXISTS emendas_federais_carteira\s*\((.*?)^\);",
        corpo, re.S | re.M)
    assert bloco, ("a regex de bloco parou de casar — o teste irmão virou "
                   "decoração e precisa ser reescrito")
    assert "municipio_id" in bloco.group(1)


# ---------------------------------------------------------------------------
# ⭐ Coletor → migration: a rede que não existe para nenhuma outra fonte
# ---------------------------------------------------------------------------
def _colunas_da_tabela(tabela: str) -> set:
    corpo = _sem_comentarios(_SQL)
    bloco = re.search(rf"CREATE TABLE IF NOT EXISTS {tabela}\s*\((.*?)^\);",
                      corpo, re.S | re.M)
    assert bloco, tabela
    cols = set()
    for linha in bloco.group(1).splitlines():
        m = re.match(r"\s*([a-z_][a-z0-9_]*)\s+[A-Za-z]", linha)
        if m and m.group(1).upper() not in ("PRIMARY", "UNIQUE", "CONSTRAINT",
                                            "FOREIGN", "CHECK"):
            cols.add(m.group(1))
    return cols


def _colunas_do_insert(sql: str) -> tuple[str, set]:
    m = re.search(r"INSERT INTO\s+([a-z_]+)\s*\((.*?)\)\s*VALUES", sql, re.S | re.I)
    assert m, "INSERT não reconhecido"
    cols = {c.strip() for c in m.group(2).split(",") if c.strip()}
    return m.group(1), cols


@pytest.mark.parametrize("nome_sql", ["_SQL_CARTEIRA", "_SQL_CGU", "_SQL_DOC"])
def test_toda_coluna_que_o_coletor_grava_existe_na_migration(nome_sql):
    """⭐ A REDE QUE FALTAVA. `test_migrations_colunas_existem.py` compara
    migration com migration; ninguém compara o COLETOR com a migration — e é o
    coletor que é editado toda semana.

    O sintoma de uma coluna a mais é a rodada inteira estourando em produção, de
    madrugada, com o boot saudável e o painel dizendo apenas "error"."""
    import ingestion.portal_transparencia as pt
    tabela, cols = _colunas_do_insert(getattr(pt, nome_sql))
    existentes = _colunas_da_tabela(tabela)
    faltando = cols - existentes
    assert not faltando, f"{tabela}: o coletor grava colunas inexistentes: {faltando}"


@pytest.mark.parametrize("nome_sql,esperado", [
    ("_SQL_CARTEIRA", {"municipio_id", "id_proposta", "cod_programa_emenda",
                       "nr_emenda", "beneficiario_cnpj"}),
    ("_SQL_CGU", {"codigo_emenda", "localidade_gasto", "funcao", "subfuncao"}),
    ("_SQL_DOC", {"codigo_emenda", "documento_id"}),
])
def test_o_on_conflict_do_coletor_bate_com_o_indice_unico(nome_sql, esperado):
    """⚠️ Alvo de conflito que não casa com nenhum índice faz o UPSERT estourar —
    e alvo que casa com o índice ERRADO faz ele sobrescrever a linha errada em
    silêncio, que é pior. Este teste amarra os dois lados."""
    import ingestion.portal_transparencia as pt
    m = re.search(r"ON CONFLICT\s*\((.*?)\)\s*DO UPDATE",
                  getattr(pt, nome_sql), re.S | re.I)
    assert m, f"{nome_sql} sem ON CONFLICT ... DO UPDATE"
    alvo = {c.strip() for c in m.group(1).split(",") if c.strip()}
    assert alvo == esperado
    # E o índice único correspondente existe na migration, com as MESMAS colunas.
    corpo = _sem_comentarios(_SQL)
    for idx in re.finditer(r"CREATE UNIQUE INDEX IF NOT EXISTS \S+\s+ON\s+"
                           r"([a-z_]+)\s*\((.*?)\);", corpo, re.S | re.I):
        cols = {c.strip() for c in idx.group(2).split(",") if c.strip()}
        if cols == esperado:
            return
    pytest.fail(f"nenhum índice único com {esperado}")


def test_o_upsert_sempre_avanca_o_visto_em():
    """⚠️ `visto_em` é o carimbo da RODADA, e é dele que o monitor de frescor lê.
    A emenda de 2011 não muda mais — sem avançar o carimbo mesmo quando nada
    mudou, a fonte envelheceria no painel com o coletor rodando todo dia."""
    import ingestion.portal_transparencia as pt
    for nome in ("_SQL_CARTEIRA", "_SQL_CGU", "_SQL_DOC"):
        sql = getattr(pt, nome)
        depois = sql.split("DO UPDATE", 1)[1]
        assert re.search(r"visto_em\s*=\s*NOW\(\)", depois, re.I), nome

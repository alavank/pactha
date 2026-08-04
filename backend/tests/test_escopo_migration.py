"""A migration do alcance por linha — e a promessa de que ela nao tira nada de
ninguem.

TRES COISAS SAO TESTADAS AQUI, e as tres tem historico neste repo:

1. O CATALOGO DO SQL BATE COM O DO PYTHON. `services/telas_catalog.py` e
   `frontend/src/lib/telas.ts` ja divergiram em seis chaves. Aqui a divergencia
   e pior do que cosmetica: recurso que existe so no Python NAO E GRAVAVEL (a
   chave estrangeira recusa), e recurso que existe so no SQL e uma restricao que
   o administrador configura e que o codigo nunca aplica — falha silenciosa de
   permissao na direcao que ABRE.

2. NENHUMA LINHA DE USUARIO E ESCRITA. Ausencia de linha e `todos`; escrever
   qualquer coisa aqui exigiria cruzar `migration_backfills`, senao o boot
   seguinte desfaz o que o administrador configurou ontem (o runner roda TODO
   arquivo a CADA boot e engole erro).

3. A MIGRATION ESTA REGISTRADA NO RUNNER. Migration orfa ja aconteceu neste
   repo — add_siconv_federal.sql nasceu fora da lista e nunca rodava.

Rodar:
    python -m pytest backend/tests/test_escopo_migration.py -v
"""
import re
from pathlib import Path

import pytest

from services.permissoes import (
    ESCOPO_PROPRIOS, ESCOPO_RECURSOS, ESCOPO_TODOS, ESCOPOS,
)
from services.startup import MIGRATION_FILES

ARQUIVO = (Path(__file__).resolve().parent.parent / "migrations"
           / "add_escopo_por_modulo.sql")
SQL = ARQUIVO.read_text(encoding="utf-8")

_SEMENTE = re.compile(r"\('([a-z_]+)',\s*'([a-z_]+)',\s*'([a-z_]+)'\)")


def _semente() -> dict:
    trecho = SQL.split("INSERT INTO escopo_recursos", 1)[1]
    return {recurso: (tabela, coluna)
            for recurso, tabela, coluna in _SEMENTE.findall(trecho)}


# ===========================================================================
# 1. O catalogo do SQL x o do Python
# ===========================================================================
def test_a_semente_tem_exatamente_os_recursos_do_python():
    assert set(_semente()) == set(ESCOPO_RECURSOS)


def test_a_semente_repete_tabela_e_coluna_sem_divergir():
    """A autoridade e o Python (`ESCOPO_RECURSOS`), que e o que
    `exigir_dono_da_linha` le para montar o SELECT. Divergir aqui nao quebra
    nada em tempo de execucao — e exatamente por isso que so um teste pega:
    seria uma mentira silenciosa para quem abrir o banco para auditar."""
    for recurso, (tabela, coluna) in _semente().items():
        assert tabela == ESCOPO_RECURSOS[recurso].tabela, recurso
        assert coluna == ESCOPO_RECURSOS[recurso].coluna_dono, recurso


def test_todo_recurso_escopavel_aponta_para_a_coluna_de_criador():
    """A regra que impede o alcance de virar um radio que nao faz nada: recurso
    so entra no catalogo se a tabela dele guardar QUEM criou a linha."""
    for recurso in ESCOPO_RECURSOS.values():
        assert recurso.coluna_dono, recurso.recurso
        migration = (Path(__file__).resolve().parent.parent / "migrations")
        criou = [p for p in migration.glob("*.sql")
                 if re.search(rf"CREATE TABLE IF NOT EXISTS {recurso.tabela}\b",
                              p.read_text(encoding="utf-8"))]
        assert criou, f"{recurso.tabela} nao e criada por migration nenhuma"
        assert any(re.search(rf"^\s*{recurso.coluna_dono}\s",
                             p.read_text(encoding="utf-8"), re.M)
                   for p in criou), \
            f"{recurso.tabela} nao tem a coluna {recurso.coluna_dono}"


# ===========================================================================
# 2. ⭐ A migration nao tira nada de ninguem
# ===========================================================================
def test_a_migration_nao_escreve_linha_de_usuario():
    """⚠️ SE ESTE TESTE QUEBRAR, LEIA ANTES DE "CONSERTAR".

    Hoje esta migration NAO escreve em `user_escopos`: ausencia de linha e
    `todos`, entao ninguem perde a edicao no deploy — a forma mais forte
    possivel da promessa.

    No dia em que ela PRECISAR escrever, o INSERT tem de cruzar
    `migration_backfills` (`WITH marca AS (INSERT ... ON CONFLICT DO NOTHING
    RETURNING nome)`, como em add_role_vira_rotulo.sql). Sem isso o boot
    seguinte DEVOLVE o alcance que o administrador acabou de configurar, e o
    defeito e invisivel ate alguem reclamar que "a restricao voltou sozinha"."""
    escreve = re.search(r"INSERT\s+INTO\s+user_escopos", SQL, re.I)
    if escreve:
        assert "migration_backfills" in SQL, (
            "esta migration passou a escrever em user_escopos e NAO cruza "
            "migration_backfills — o proximo boot vai desfazer a configuracao "
            "do administrador")
        assert "RETURNING nome" in SQL
        assert re.search(r"FROM\s+marca\b", SQL)


def test_o_default_da_coluna_e_o_que_nao_restringe():
    assert re.search(r"escopo\s+TEXT NOT NULL DEFAULT 'todos'", SQL)


def test_o_banco_recusa_valor_fora_do_vocabulario():
    """Terceira trava do vocabulario, junto com `_validar_escopos` e a
    normalizacao do Python. Valor torto e uma restricao que nunca se aplica."""
    assert re.search(r"CHECK \(escopo IN \('todos', 'proprios'\)\)", SQL)
    assert set(ESCOPOS) == {ESCOPO_TODOS, ESCOPO_PROPRIOS}


# ===========================================================================
# 3. As tabelas
# ===========================================================================
def test_user_escopos_tem_chave_estrangeira_para_o_catalogo():
    """Sem a FK, um typo (`gestaoo`) gravaria: uma restricao que o administrador
    jura ter configurado e que nunca vale — falha silenciosa que ABRE."""
    assert re.search(
        r"recurso\s+TEXT NOT NULL REFERENCES escopo_recursos\s*\(recurso\)", SQL)


def test_a_fk_do_catalogo_e_restrict_e_a_do_usuario_e_cascade():
    assert "REFERENCES users(id) ON DELETE CASCADE" in SQL
    assert "ON DELETE RESTRICT" in SQL


def test_as_tabelas_sao_idempotentes():
    """O runner executa o arquivo inteiro a cada boot."""
    assert SQL.count("CREATE TABLE IF NOT EXISTS") == 2
    assert "CREATE INDEX IF NOT EXISTS" in SQL
    assert "ON CONFLICT (recurso) DO NOTHING" in SQL


def test_a_semente_do_catalogo_roda_a_cada_boot_e_nao_tem_marca():
    """Declarar que um modulo ACEITA alcance nao restringe ninguem — e e o que
    faz um modulo novo virar configuravel num tenant no ar, sem migration."""
    trecho = SQL.split("INSERT INTO escopo_recursos", 1)[1]
    assert "migration_backfills" not in trecho


def test_o_sql_e_valido():
    pglast = pytest.importorskip("pglast")
    assert len(pglast.parse_sql(SQL)) >= 4


# ===========================================================================
# 4. A ordem no runner
# ===========================================================================
def test_a_migration_esta_registrada_no_runner():
    assert "add_escopo_por_modulo.sql" in MIGRATION_FILES


def test_a_ordem_das_dependencias():
    """Tem de vir ANTES do append-only da trilha, que e sempre a ultima."""
    indice = MIGRATION_FILES.index("add_escopo_por_modulo.sql")
    assert indice > MIGRATION_FILES.index("add_permissoes_por_acao.sql")
    assert indice < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
    assert MIGRATION_FILES[-1] == "add_auditoria_imutavel.sql"


def test_o_arquivo_existe_com_o_nome_registrado():
    assert ARQUIVO.exists()

"""O registro de migration aplicada (15/09/2026).

Ate aqui o boot rodava a lista INTEIRA de migrations em todo start. Idempotente
nao e sem lock: `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` e
`DROP ... CASCADE` pedem o lock antes de ver que nao ha nada a fazer, e esperam
qualquer coletor com transacao aberta. Em 15/09/2026 o boot da api-freitas ficou
preso atras do `sigcon` ate o healthcheck do Coolify voltar o container antigo.

Agora `migrations_aplicadas` guarda o SHA-256 de cada arquivo, e so roda o que e
novo ou mudou. O que se prova aqui: a decisao por arquivo, que falha nao
registra, que o registro indisponivel volta ao comportamento antigo, e que nada
marcado "a cada boot" carrega DDL — que e justamente o que pede lock forte.
"""
import re
import sys
import types
from pathlib import Path

import pytest

from services import startup
from services.startup import (
    CHAVE_SCHEMA_BASE, MARCA_A_CADA_BOOT, MIGRATION_FILES, checksum_de, decide_migration,
)

_MIGR = Path(__file__).resolve().parents[1] / "migrations"


# ---------------------------------------------------------------------------
# A decisao por arquivo
# ---------------------------------------------------------------------------
def test_decide_migration():
    sql = "ALTER TABLE x ADD COLUMN IF NOT EXISTS y INT;"
    assert decide_migration(None, None) == "ausente"
    assert decide_migration(sql, None) == "nova"
    assert decide_migration(sql, checksum_de(sql)) == "registrada"
    assert decide_migration(sql + "\n-- comentario novo", checksum_de(sql)) == "alterada"
    marcado = MARCA_A_CADA_BOOT + "\nUPDATE x SET y = 1 WHERE y IS NULL;"
    assert decide_migration(marcado, checksum_de(marcado)) == "a-cada-boot"


# ---------------------------------------------------------------------------
# O laco do boot, com o banco de mentira
# ---------------------------------------------------------------------------
class _Banco:
    def __init__(self, registro, falha=()):
        self.registro = registro          # None = registro indisponivel
        self.falha = set(falha)
        self.rodou: list[str] = []
        self.registrou: dict[str, str] = {}


@pytest.fixture
def banco(monkeypatch):
    def montar(registro, falha=()):
        b = _Banco(registro, falha)
        monkeypatch.setattr(startup, "_le_registro", lambda _u: b.registro)

        def _roda(_u, sql, arquivo, checksum):
            nome = arquivo or next((f for f in MIGRATION_FILES
                                    if (_MIGR / f).exists()
                                    and (_MIGR / f).read_text(encoding="utf-8") == sql), sql[:20])
            if nome in b.falha:
                raise RuntimeError(f'relation "{nome}" already exists')
            b.rodou.append(nome)
            if arquivo:
                b.registrou[arquivo] = checksum

        monkeypatch.setattr(startup, "_roda_sql", _roda)
        monkeypatch.setattr(startup, "_bootstrap_control_token", lambda _u: None)
        monkeypatch.setattr(startup, "_log_estado_da_trava", lambda: None)
        # setup_db de mentira: o schema base e as contas
        fake = types.ModuleType("setup_db")
        fake.SCHEMA_BASE_SQL = "CREATE TABLE IF NOT EXISTS municipios (id INT);"
        fake.criou = []
        fake.create_tables = lambda: fake.criou.append(1)
        fake.seed_data = lambda: None
        monkeypatch.setitem(sys.modules, "setup_db", fake)
        b.setup_db = fake
        return b
    return montar


def _tudo_registrado():
    reg = {f: checksum_de((_MIGR / f).read_text(encoding="utf-8"))
           for f in MIGRATION_FILES if (_MIGR / f).exists()}
    reg[CHAVE_SCHEMA_BASE] = checksum_de("CREATE TABLE IF NOT EXISTS municipios (id INT);")
    return reg


def _marcados():
    return [f for f in MIGRATION_FILES
            if MARCA_A_CADA_BOOT in (_MIGR / f).read_text(encoding="utf-8")]


def test_banco_em_dia_so_roda_o_que_e_marcado(banco):
    """⭐ O PONTO DE TUDO: boot sem migration nova nao toca tabela de ninguem
    (e o schema base tambem fica de fora)."""
    b = banco(_tudo_registrado())
    startup._rodar_migrations("postgresql://x")
    assert sorted(b.rodou) == sorted(_marcados())
    assert b.setup_db.criou == []


def test_banco_novo_roda_tudo_e_registra_tudo(banco):
    b = banco({})
    startup._rodar_migrations("postgresql://x")
    existentes = [f for f in MIGRATION_FILES if (_MIGR / f).exists()]
    assert b.rodou[-len(existentes):] == existentes
    assert set(existentes) <= set(b.registrou)
    assert CHAVE_SCHEMA_BASE in b.registrou and b.setup_db.criou == [1]


def test_arquivo_alterado_roda_de_novo(banco):
    reg = _tudo_registrado()
    reg["add_faf_detalhe.sql"] = "checksum-de-uma-versao-antiga"
    b = banco(reg)
    startup._rodar_migrations("postgresql://x")
    assert "add_faf_detalhe.sql" in b.rodou
    assert b.registrou["add_faf_detalhe.sql"] == checksum_de(
        (_MIGR / "add_faf_detalhe.sql").read_text(encoding="utf-8"))


def test_falha_nao_registra_e_tenta_de_novo(banco):
    """⚠️ "already exists" NAO e mais "ja aplicada": um UNIQUE que nao pode ser
    criado porque ha duplicata tambem diz "duplicate" (add_obrasgov.sql, tres
    tenants, ate 15/09/2026). Sem registro, o proximo boot tenta de novo."""
    b = banco({}, falha={"add_faf_detalhe.sql"})
    startup._rodar_migrations("postgresql://x")
    assert "add_faf_detalhe.sql" not in b.registrou
    assert "add_parcerias_detalhe.sql" in b.registrou     # as outras seguem


def test_registro_indisponivel_volta_ao_comportamento_antigo(banco):
    """Sem conseguir ler o registro: roda a lista inteira e nao registra nada.
    Melhor lock de DDL que schema pela metade."""
    b = banco(None)
    startup._rodar_migrations("postgresql://x")
    assert len(b.rodou) >= len([f for f in MIGRATION_FILES if (_MIGR / f).exists()])
    assert b.registrou == {} and b.setup_db.criou == [1]


# ---------------------------------------------------------------------------
# O que pode rodar em todo boot
# ---------------------------------------------------------------------------
_DDL = re.compile(r"\b(ALTER\s+TABLE|CREATE\s+(UNIQUE\s+)?INDEX|DROP\s+(TABLE|INDEX|CONSTRAINT)"
                  r"|CREATE\s+TABLE|TRUNCATE|CREATE\s+(OR\s+REPLACE\s+)?TRIGGER)\b", re.I)


def test_quem_roda_em_todo_boot_nao_carrega_ddl():
    """A marca existe para limpeza AUTOCURATIVA e semente que depende de outra
    tabela — UPDATE/DELETE com guarda, que pedem so RowExclusive. DDL numa
    migration marcada traria de volta o lock de todo boot que o registro tirou."""
    for f in _marcados():
        sql = re.sub(r"--[^\n]*", "", (_MIGR / f).read_text(encoding="utf-8"))
        assert not _DDL.search(sql), f"{f} e a-cada-boot e tem DDL"


def test_os_marcados_sao_os_tres_de_hoje():
    """Mudou a lista? Leia o bloco do registro em services/startup.py antes."""
    assert sorted(_marcados()) == ["fix_fns_valor_pago_na_coluna_certa.sql",
                                   "limpa_prestacao_contas_sei_lixo.sql",
                                   "semeia_super_admin.sql"]


def test_a_semente_do_super_admin_vem_depois_da_coluna():
    assert MIGRATION_FILES.index("semeia_super_admin.sql") == \
        MIGRATION_FILES.index("add_role_vira_rotulo.sql") + 1


def test_o_schema_base_e_um_texto_que_da_para_somar():
    import setup_db as real
    assert "CREATE TABLE IF NOT EXISTS municipios" in real.SCHEMA_BASE_SQL


def test_add_obrasgov_nao_recria_o_indice_que_a_seguinte_derruba():
    sql = re.sub(r"--[^\n]*", "", (_MIGR / "add_obrasgov.sql").read_text(encoding="utf-8"))
    assert "ux_obrasgov_projetos " not in sql and "ux_obrasgov_projetos\n" not in sql
    assert not re.search(r"\bux_obrasgov_projetos\b(?!_)", sql)

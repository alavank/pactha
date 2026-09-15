"""O boot não pode recriar tabela que o próprio boot derruba (15/09/2026).

`migrations/drop_lean_tables.sql` roda a CADA boot e derruba, com CASCADE, as
tabelas do refactor lean (2026-05). Isso só é barato porque elas não existem: DROP
... IF EXISTS de tabela ausente não pede lock.

Até 15/09/2026 o `setup_db.py` recriava oito delas antes daqui. O DROP ... CASCADE
tirava as chaves estrangeiras para `convenios_estadual`/`municipios`/`users` e
precisava de lock nessas tabelas vivas: no deploy do #486, o boot da API da Freitas
ficou esperando o `sigcon` (que escrevia em `convenios_estadual`) até o healthcheck
do Coolify desistir e voltar o container antigo.
"""
import re
from pathlib import Path

from services.startup import MIGRATION_FILES

_RAIZ = Path(__file__).resolve().parents[1]
_DROP_SQL = (_RAIZ / "migrations" / "drop_lean_tables.sql").read_text(encoding="utf-8")
_MORTAS = {m.lower() for m in re.findall(r"DROP TABLE IF EXISTS\s+(\w+)", _DROP_SQL, re.I)}
_CRIA = re.compile(r"CREATE TABLE (?:IF NOT EXISTS\s+)?(\w+)", re.I)


def _sem_comentarios(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def test_a_lista_de_mortas_foi_lida():
    assert {"emendas", "convenios_federal", "prestacao_contas", "edital_acompanhamento"} <= _MORTAS


def test_o_setup_db_nao_recria_tabela_morta():
    fonte = _sem_comentarios((_RAIZ / "setup_db.py").read_text(encoding="utf-8"))
    recriadas = {t.lower() for t in _CRIA.findall(fonte)} & _MORTAS
    assert not recriadas, (
        f"setup_db.py cria {sorted(recriadas)}, que drop_lean_tables.sql derruba a cada "
        "boot: o DROP ... CASCADE espera lock nas tabelas referenciadas e o boot trava "
        "enquanto um coletor escreve nelas (Freitas, 15/09/2026).")


def test_nenhum_modelo_tem_nome_de_tabela_morta():
    """O `create_all` roda antes das migrations: um modelo com o nome recriaria a
    tabela do mesmo jeito."""
    import models  # noqa: F401 — registra os modelos em Base.metadata
    from database import Base
    assert not (set(Base.metadata.tables) & _MORTAS)


def test_nenhuma_migration_recria_tabela_morta():
    for fname in MIGRATION_FILES:
        if fname == "drop_lean_tables.sql":
            continue
        caminho = _RAIZ / "migrations" / fname
        if not caminho.exists():
            continue
        criadas = {t.lower() for t in _CRIA.findall(_sem_comentarios(
            caminho.read_text(encoding="utf-8")))} & _MORTAS
        assert not criadas, f"{fname} cria {sorted(criadas)}, que drop_lean_tables.sql derruba"

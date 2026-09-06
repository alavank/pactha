"""
⚠️⚠️ TODA COLUNA CITADA NUMA MIGRATION EXISTE? — o teste que faltava.

O ACIDENTE QUE O CRIOU (05/09/2026)
-----------------------------------
`add_permissoes_por_tela.sql` escreveu `pc.permissao` num JOIN com
`permissoes_catalogo`. A coluna daquela tabela chama-se `chave`; `permissao` é o
nome que a coluna tem em `user_permissoes`, a tabela VIZINHA, na mesma consulta.

O Postgres respondeu `column pc.permissao does not exist`. E aí a combinação que
tornou o erro caro:

  1. o arquivo inteiro roda numa transação só, então **as cinco partes** do
     backfill voltaram atrás juntas — nada foi aplicado;
  2. `services/startup.py` engole a exceção numa linha de log e **o boot segue**,
     então a API subiu saudável nos cinco tenants;
  3. `pglast` (o validador que a suíte já tinha) só confere a GRAMÁTICA. Um nome
     de coluna inexistente é SQL perfeitamente válido.

Resultado: o backfill não rodou, ninguém foi avisado, e o defeito só apareceu
olhando o dado pela API — um dia depois, e por acaso.

O QUE ESTE ARQUIVO FAZ
----------------------
Monta o schema lendo os próprios `.sql` (`CREATE TABLE` + `ALTER TABLE ... ADD
COLUMN`) e confere que toda referência `alias.coluna` das migrations resolve numa
coluna que existe naquela tabela.

⚠️ NÃO É UM VALIDADOR DE SQL, e não tenta ser: é uma rede para a classe de erro
que já custou um deploy — o nome de coluna trocado entre duas tabelas parecidas.
Onde não consegue resolver o alias com segurança, **fica quieto**: um teste que
acusa falso ensina a ser ignorado, e aí ele deixa de pegar o caso verdadeiro.

Rodar:
    python -m pytest backend/tests/test_migrations_colunas_existem.py -v
"""
import re
from pathlib import Path

MIGRACOES = Path(__file__).resolve().parent.parent / "migrations"

# `CREATE TABLE [IF NOT EXISTS] <nome> ( ... );` — o corpo até o parêntese que
# fecha na coluna 0, que é como todo arquivo deste repo escreve.
_CREATE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\s*\((.*?)^\)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE)
# ⚠️ O STATEMENT INTEIRO, ate o `;` — e nao so o primeiro `ADD COLUMN`.
# `add_agendamentos_compromisso.sql` tem UM `ALTER TABLE` com SEIS `ADD COLUMN`
# separados por virgula; pegar so o primeiro fazia as outras cinco sumirem do
# schema, e o teste acusava `a.coluna_id` como inexistente — falso positivo, que
# e o defeito que mata um teste (uma vez ignorado, ele para de pegar o caso real).
_ALTER_STMT = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([a-z_][a-z0-9_]*)(.*?);",
    re.IGNORECASE | re.DOTALL)
_ADD_COL = re.compile(
    r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)", re.IGNORECASE)
# `FROM <tabela> <alias>` / `JOIN <tabela> <alias>` — só o alias EXPLÍCITO, sem
# `AS`, que é a forma que o repo usa. Alias implícito não entra: resolver errado
# é pior que não resolver.
_ALIAS = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)\s+([a-z][a-z0-9_]{0,3})\b(?!\s*\()",
    re.IGNORECASE)
_REF = re.compile(r"\b([a-z][a-z0-9_]{0,3})\.([a-z_][a-z0-9_]*)\b")

# Palavras que aparecem como `x.y` sem serem coluna (schema, função, número).
_NAO_E_ALIAS = {"pg", "information_schema", "public", "to", "as", "on", "in"}


def _sem_comentario(sql: str) -> str:
    """SQL sem os `--`. Precisa vir ANTES de qualquer regex: em
    `add_agendamentos_compromisso.sql` há um comentário entre o `ALTER TABLE` e o
    `ADD COLUMN`, e sem esta limpeza a coluna some do schema — o teste então
    acusaria `a.coluna_id` como inexistente, que é falso."""
    return re.sub(r"--[^\n]*", "", sql)


def _schema() -> tuple:
    """`({tabela: {colunas}}, {tabelas criadas AQUI})`.

    ⚠️ O SEGUNDO CONJUNTO É O QUE TORNA O TESTE HONESTO. `users`,
    `convenios_estadual` e outras nascem em `setup_db.py` (SQLAlchemy), não numa
    migration — então este parser só enxerga as colunas que ALTERs
    acrescentaram, e concluir "`u.id` não existe" seria mentira. Só se valida
    tabela cuja definição INTEIRA está aqui."""
    tabelas: dict = {}
    criadas: set = set()
    for arq in sorted(MIGRACOES.glob("*.sql")):
        sql = _sem_comentario(arq.read_text(encoding="utf-8"))
        for tabela, corpo in _CREATE.findall(sql):
            criadas.add(tabela.lower())
            cols = tabelas.setdefault(tabela.lower(), set())
            for linha in corpo.splitlines():
                linha = linha.strip()
                if not linha:
                    continue
                m = re.match(r"([a-z_][a-z0-9_]*)\s", linha, re.IGNORECASE)
                if m and m.group(1).upper() not in (
                        "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"):
                    cols.add(m.group(1).lower())
        for tabela, corpo in _ALTER_STMT.findall(sql):
            cols = tabelas.setdefault(tabela.lower(), set())
            for coluna in _ADD_COL.findall(corpo):
                cols.add(coluna.lower())
    return tabelas, criadas


SCHEMA, CRIADAS_AQUI = _schema()


def test_o_leitor_de_schema_funciona():
    """Rede do próprio teste: se o parser parar de achar as tabelas, os testes
    abaixo passariam vazios e não guardariam nada."""
    assert "permissoes_catalogo" in SCHEMA
    assert "chave" in SCHEMA["permissoes_catalogo"]
    assert "permissao" not in SCHEMA["permissoes_catalogo"], (
        "esta e EXATAMENTE a confusao que derrubou add_permissoes_por_tela.sql")
    assert "permissao" in SCHEMA["user_permissoes"]
    assert "tela" in SCHEMA["user_telas"]
    assert len(SCHEMA) > 30, f"so {len(SCHEMA)} tabelas — o parser regrediu?"


def _referencias_invalidas(sql: str) -> list:
    """`[(alias, tabela, coluna)]` que não existem. Alias não resolvido é
    ignorado — ver a nota do cabeçalho."""
    sql = _sem_comentario(sql)
    aliases = {a.lower(): t.lower() for t, a in _ALIAS.findall(sql)}
    ruins = []
    for alias, coluna in _REF.findall(sql):
        alias, coluna = alias.lower(), coluna.lower()
        if alias in _NAO_E_ALIAS:
            continue
        tabela = aliases.get(alias)
        # Alias desconhecido, ou tabela que nasce fora das migrations: não
        # opina. Ver a nota de `CRIADAS_AQUI`.
        if not tabela or tabela not in CRIADAS_AQUI or not SCHEMA.get(tabela):
            continue
        if coluna not in SCHEMA[tabela]:
            ruins.append((alias, tabela, coluna))
    return ruins


def test_nenhuma_migration_cita_coluna_que_nao_existe():
    """⭐ O TESTE QUE TERIA POUPADO O DEPLOY DE 05/09/2026.

    `pglast` valida a gramática e passa por um nome de coluna errado sem
    reclamar — porque `pc.permissao` é SQL perfeitamente válido, só não existe
    naquela tabela. Esta é a diferença entre "compila" e "roda"."""
    erros = {}
    for arq in sorted(MIGRACOES.glob("*.sql")):
        ruins = _referencias_invalidas(arq.read_text(encoding="utf-8"))
        if ruins:
            erros[arq.name] = ruins
    assert not erros, (
        "coluna citada que nao existe na tabela do alias:\n"
        + "\n".join(f"  {nome}: " + ", ".join(
            f"{a}.{c} (o alias {a} e {t}, que nao tem {c})" for a, t, c in v)
            for nome, v in erros.items()))


def test_a_migration_do_incremento_usa_chave_e_nao_permissao():
    """Nominal, porque foi ESTE par que trocou: `permissoes_catalogo.chave` é a
    definição; `user_permissoes.permissao` é a concessão. Duas tabelas na mesma
    consulta, dois nomes para a mesma ideia."""
    # Sem os comentários: o cabeçalho daquele arquivo CITA `pc.permissao` para
    # contar o que deu errado, e o relato tem de poder existir.
    sql = _sem_comentario(
        (MIGRACOES / "add_permissoes_por_tela.sql").read_text(encoding="utf-8"))
    assert "pc.chave" in sql
    assert "pc.permissao" not in sql

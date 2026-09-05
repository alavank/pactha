"""
A migration do Incremento 5 — o BANCO como ultima linha de defesa, e o BACKFILL
que impede o apagao.

DUAS COISAS SAO TESTADAS AQUI, e as duas tem historico neste repo:

1. O CATALOGO DO SQL BATE COM O DO PYTHON. `services/telas_catalog.py` e
   `frontend/src/lib/telas.ts` ja divergiram em seis chaves, e o comentario de
   la ainda avisa que tela nova precisa entrar em TRES lugares. Aqui sao dois
   lugares e uma FK: chave que existe so no Python NAO E GRAVAVEL (a chave
   estrangeira recusa, e o administrador ve um erro que nao entende); chave que
   existe so no SQL e caixinha que nunca aparece na tela. Este arquivo quebra
   antes de qualquer uma das duas chegar em producao.

2. TODA PERMISSAO TEM TRADUCAO DE COMPATIBILIDADE. Permissao nova sem linha no
   mapa de backfill nasce concedida a NINGUEM — e isso so aparece no dia em que
   `AUTHZ_MODO=bloqueio` for ligado, semanas depois, como "sumiu o botao".

Rodar:
    python -m pytest backend/tests/test_permissoes_migration.py -v
"""
import re
from pathlib import Path

import pytest

from services.permissoes import CATALOGO
from services.startup import MIGRATION_FILES

ARQUIVO = (Path(__file__).resolve().parent.parent / "migrations"
           / "add_permissoes_por_acao.sql")
SQL = ARQUIVO.read_text(encoding="utf-8")

# O arquivo tem duas listas de VALUES com formas parecidas. Cortamos no titulo
# da secao 4 em vez de separar por regex esperto: se alguem reorganizar o
# arquivo, o teste falha em vez de ler a lista errada calado.
MARCO = "4. ⭐ BACKFILL"
assert MARCO in SQL, "a secao de backfill mudou de titulo — conferir este teste"
TRECHO_SEMENTE, TRECHO_BACKFILL = SQL.split(MARCO, 1)

_SEMENTE = re.compile(r"\('([a-z_]+\.[a-z_]+)',\s*'([a-z_]+)',\s*(TRUE|FALSE)\)")
_MAPA = re.compile(
    r"\((?:'([a-z_]+)'(?:::text)?|NULL),\s*'([a-z_]+\.[a-z_]+)',\s*(TRUE|FALSE)\)")


def _semente() -> dict:
    return {chave: (secao, escrita == "TRUE")
            for chave, secao, escrita in _SEMENTE.findall(TRECHO_SEMENTE)}


def _mapa() -> list:
    return [(tela or None, permissao, exige_admin == "TRUE")
            for tela, permissao, exige_admin in _MAPA.findall(TRECHO_BACKFILL)]


# ===========================================================================
# 1. O catalogo do SQL x o do Python
# ===========================================================================
def test_a_semente_do_sql_tem_exatamente_as_chaves_do_python():
    sql = set(_semente())
    python = set(CATALOGO)
    assert sql - python == set(), "chave no SQL que nao existe no Python"
    assert python - sql == set(), (
        "chave no Python sem linha na tabela-catalogo do SQL — a chave "
        "estrangeira vai RECUSAR a concessao dela")


def test_a_semente_repete_secao_e_escrita_sem_divergir():
    """Os dois campos que a tabela guarda alem da chave. Divergir aqui nao
    quebra nada em tempo de execucao (quem manda e o Python), e e exatamente por
    isso que so um teste pega: seria uma mentira silenciosa para quem abrir o
    banco para auditar."""
    for chave, (secao, escrita) in _semente().items():
        assert secao == CATALOGO[chave].secao, chave
        assert escrita == CATALOGO[chave].escrita, chave


def test_a_semente_nao_tem_chave_repetida():
    chaves = _SEMENTE.findall(TRECHO_SEMENTE)
    assert len(chaves) == len({c[0] for c in chaves})


# ===========================================================================
# 2. O backfill de compatibilidade
# ===========================================================================
def test_toda_permissao_tem_regra_de_compatibilidade():
    """Ninguem pode perder acesso no deploy — e permissao sem linha no mapa
    nasce concedida a ninguem."""
    traduzidas = {permissao for _, permissao, _ in _mapa()}
    assert set(CATALOGO) - traduzidas == set()


def test_o_mapa_nao_inventa_permissao():
    assert {p for _, p, _ in _mapa()} - set(CATALOGO) == set()


def test_ver_e_exportar_nao_exigem_admin():
    """A regra do dono, palavra por palavra: "quem tem a tela X hoje recebe
    X.ver e X.exportar; os verbos de ESCRITA so para quem e admin hoje".

    As excecoes sao NOMINAIS e cada uma tem motivo escrito na migration:
    `usuarios.*`, `frescor.*` e `parametros.*` nunca foram tela (sempre
    `role == 'admin'`), e `cofre.revelar` e admin desde sempre em
    routers/cofre.py.

    ⚠️ `parametros.ver` entrou na lista em 05/09/2026, quando a aba de
    Parametros ganhou chave propria. Ela e excecao pelo MESMO motivo das outras
    duas — nunca teve tela, era governada pelo papel —, e por isso o backfill de
    banco novo a concede so a admin. A tela `parametros` que a acompanha nasce
    com quem ja era administrador."""
    excecoes = {"usuarios.ver", "frescor.ver", "usuarios.exportar",
                "frescor.exportar", "cofre.revelar", "parametros.ver"}
    for tela, permissao, exige_admin in _mapa():
        verbo = permissao.rsplit(".", 1)[1]
        if verbo in ("ver", "exportar") and permissao not in excecoes:
            assert not exige_admin, permissao
            assert tela is not None, permissao


def test_verbos_de_escrita_exigem_admin():
    """A outra metade da regra. As tres excecoes sao NOMINAIS, e existem porque
    "ninguem pode perder acesso no deploy" vence a simetria da regra:

      ai.usar / ai.exportar   sao `escrita` so pela definicao do guard (o
                              endpoint e POST porque a pergunta vai no corpo).
                              HOJE quem abre a tela da IA conversa e exporta,
                              sem ser admin — exigir admin aqui tiraria a IA da
                              equipe inteira no dia do deploy.
    (`telegram.vincular` era a terceira excecao — o usuario ligando o PROPRIO
    celular, escrita mas sobre a propria conta. Saiu em 05/09/2026 com o modulo.)

    Excecao nova entra nesta lista E ganha comentario na migration, ou o teste
    quebra — que e o ponto: afrouxar a regra tem de ser decisao escrita."""
    excecoes = {"ai.usar", "ai.exportar"}
    for _, permissao, exige_admin in _mapa():
        if CATALOGO[permissao].escrita and permissao not in excecoes:
            assert exige_admin, permissao


def test_cofre_revelar_e_o_crud_continuam_so_para_admin():
    """Hoje `routers/cofre.py` exige `role == 'admin'` em revelar/criar/editar/
    excluir; a tela `cofre` sozinha da so a listagem mascarada. O backfill tem
    de preservar EXATAMENTE isso — nem tirar do operador da Alavank que usa o
    cofre, nem espalhar a senha do gov.br para quem so via a lista."""
    mapa = {permissao: (tela, admin) for tela, permissao, admin in _mapa()}
    assert mapa["cofre.ver"] == ("cofre", False)
    for chave in ("cofre.revelar", "cofre.criar", "cofre.editar", "cofre.excluir"):
        assert mapa[chave] == ("cofre", True), chave


def test_o_backfill_so_roda_uma_vez():
    """⚠️ O runner roda TODA migration a CADA boot e engole erro. Sem a marca em
    `migration_backfills`, o boot seguinte DEVOLVE a permissao que o
    administrador acabou de revogar — e o defeito seria invisivel ate alguem
    reclamar que "a permissao voltou sozinha"."""
    assert "migration_backfills" in TRECHO_BACKFILL
    assert "add_permissoes_por_acao:compat_telas_e_papel" in TRECHO_BACKFILL
    assert "ON CONFLICT (nome) DO NOTHING" in TRECHO_BACKFILL
    assert "RETURNING nome" in TRECHO_BACKFILL
    # A marca so habilita o INSERT se ela for CRUZADA com a consulta.
    assert re.search(r"FROM marca,\s*users", TRECHO_BACKFILL)


def test_o_backfill_ignora_inativo_e_super_admin():
    assert "u.active" in TRECHO_BACKFILL
    assert "NOT u.super_admin" in TRECHO_BACKFILL


def test_a_semente_do_catalogo_roda_a_cada_boot_e_nao_tem_marca():
    """Ao contrario do backfill: declarar que uma chave EXISTE nao concede nada
    a ninguem, e e o que faz permissao nova virar gravavel num tenant que ja
    esta no ar, sem migration nova."""
    assert "migration_backfills" not in TRECHO_SEMENTE.split("INSERT INTO permissoes_catalogo")[1]
    assert "ON CONFLICT (chave) DO NOTHING" in TRECHO_SEMENTE


# ===========================================================================
# 3. As tabelas
# ===========================================================================
def test_user_permissoes_tem_chave_estrangeira_para_o_catalogo():
    """⭐ O ponto do item (B). Hoje `user_telas` aceita QUALQUER string: um typo
    grava, aparece como concedido na tela e nao concede nada — falha silenciosa
    de permissao. Com a FK, chave invalida deixa de ser gravavel."""
    assert re.search(
        r"permissao\s+TEXT NOT NULL REFERENCES permissoes_catalogo\s*\(chave\)",
        SQL)


def test_a_fk_do_catalogo_e_restrict_e_a_do_usuario_e_cascade():
    """Apagou a pessoa, some a permissao dela (CASCADE). Tirar uma permissao do
    catalogo com gente usando tem de DOER (RESTRICT) — senao um DELETE numa
    manutencao levaria junto, em cascata e em silencio, o acesso de todos."""
    assert "REFERENCES users(id) ON DELETE CASCADE" in SQL
    assert "ON DELETE RESTRICT" in SQL


def test_as_tabelas_sao_idempotentes():
    """O runner executa o arquivo inteiro a cada boot."""
    assert SQL.count("CREATE TABLE IF NOT EXISTS") == 2
    assert "CREATE INDEX IF NOT EXISTS" in SQL


def test_o_sql_e_valido():
    pglast = pytest.importorskip("pglast")
    assert len(pglast.parse_sql(SQL)) >= 4


# ===========================================================================
# 4. A ordem no runner
# ===========================================================================
def test_a_migration_esta_registrada_no_runner():
    """Migration orfa ja aconteceu neste repo (add_siconv_federal.sql nasceu
    fora da lista e nunca rodava; a tabela simplesmente nao existia em tenant
    novo)."""
    assert "add_permissoes_por_acao.sql" in MIGRATION_FILES


def test_a_ordem_das_dependencias():
    """Depende de add_role_vira_rotulo (le `users.super_admin` e usa
    `migration_backfills`, criados la) e tem de vir ANTES do append-only da
    trilha, que e sempre a ultima."""
    indice = MIGRATION_FILES.index("add_permissoes_por_acao.sql")
    assert indice > MIGRATION_FILES.index("add_role_vira_rotulo.sql")
    assert indice < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
    assert MIGRATION_FILES[-1] == "add_auditoria_imutavel.sql"


def test_o_arquivo_existe_com_o_nome_registrado():
    assert ARQUIVO.exists()
